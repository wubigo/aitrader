import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Dict, Optional, Set, Any

import pandas as pd
from requests import ConnectTimeout
from tqsdk import TqApi, TqAuth, TqBacktest, BacktestFinished, TargetPosTask, TqSim

from utils.backtest_logger import backup_dataframe
from tq.generate_ic_basis_cache import get_ic_annualized_basis_percentile
from utils.logging_config import setup_logging

# --- Setup Logging ---
setup_logging()
logger = logging.getLogger(__name__)

@dataclass
class StrategyConfig:
    """Strategy configuration parameters."""
    futures_symbol: str = "KQ.m@CFFEX.IC"
    index_symbol: str = "SSE.000905"
    duration: int = 60 * 60 * 24  # Daily K-line
    data_length: int = 100
    initial_balance: float = 1_000_000.0

    # Entry/Exit Thresholds
    annualized_basis_threshold: float = 8.0
    min_days_to_expiry_open: int = 7
    max_days_to_expiry_close: int = 6
    profit_taking_basis_pct: float = 0.5

    # Advanced Filters
    index_sma_period: int = 20
    adaptive_threshold_window: int = 60
    volatility_window: int = 20
    target_volatility: float = 0.15
    default_trade_volume: int = 1

    # Backtest Period
    start_dt: date = date(2018, 1, 1)
    end_dt: date = date(2023, 1, 1)

    # System Config
    chunk_size: int = 5000

    @property
    def start_nano(self) -> int:
        return int(pd.Timestamp(self.start_dt).timestamp() * 1e9)

    @property
    def csv_file(self) -> str:
        return f"IC_main_vs_CSI500_{self.duration}s_{self.start_dt}_{self.end_dt}.csv"


class PerformanceAnalyzer:
    """Helper class to calculate and log strategy performance."""

    @staticmethod
    def calculate_metrics(df: pd.DataFrame, config: StrategyConfig, final_balance: float):
        if df.empty or "balance" not in df.columns:
            logger.info("No balance data available for performance analysis.")
            return

        df["datetime"] = pd.to_datetime(df["datetime"])

        # 1. CAGR
        days = (config.end_dt - config.start_dt).days
        cagr = (final_balance / config.initial_balance) ** (365.0 / max(days, 1)) - 1

        # 2. Max Drawdown
        df["cum_max_balance"] = df["balance"].cummax()
        df["drawdown"] = (df["balance"] - df["cum_max_balance"]) / df["cum_max_balance"]
        max_drawdown = df["drawdown"].min()

        # 3. Sharpe Ratio
        returns = df["balance"].pct_change().dropna()
        sharpe = (returns.mean() / returns.std() * (242 ** 0.5)) if returns.std() > 0 else 0

        logger.info("📈 【策略绩效评估】")
        logger.info(f"   起始资金: {config.initial_balance:,.2f}")
        logger.info(f"   最终资金: {final_balance:,.2f}")
        logger.info(f"   年化收益率 (CAGR): {cagr:.2%}")
        logger.info(f"   最大回撤 (Max Drawdown): {max_drawdown:.2%}")
        logger.info(f"   夏普比率 (Sharpe Ratio): {sharpe:.2f}")

        # 4. Period Analysis
        PerformanceAnalyzer._log_period_returns(df)

    @staticmethod
    def _log_period_returns(df: pd.DataFrame):
        df['year'] = df['datetime'].dt.year
        df['half_year'] = df['datetime'].dt.month.apply(lambda x: 1 if x <= 6 else 2)

        yearly = df.groupby('year')['balance'].agg(['first', 'last'])
        logger.info("📅 【年度收益分析】")
        for year, row in yearly.iterrows():
            logger.info(f"   {year}年度: {(row['last'] / row['first'] - 1):.2%}")

        semi = df.groupby(['year', 'half_year'])['balance'].agg(['first', 'last'])
        logger.info("📆 【半年度收益分析】")
        for (year, half), row in semi.iterrows():
            logger.info(f"   {year} H{half}: {(row['last'] / row['first'] - 1):.2%}")


class ICBasisRollerStrategy:
    """Main strategy implementation class."""

    def __init__(self, config: StrategyConfig):
        self.cfg = config
        self.api: Optional[TqApi] = None
        self.sim_account = TqSim(init_balance=self.cfg.initial_balance, account_id='bigo')

        # State Variables
        self.current_underlying: str = ""
        self.has_opened_in_current_main: bool = False
        self.entry_ann_basis: Optional[float] = None
        self.last_bar_dt: int = 0
        self.processed_trade_ids: Set[str] = set()

        # Windows & Data collection
        self.basis_window = deque(maxlen=self.cfg.adaptive_threshold_window)
        self.vol_window = deque(maxlen=self.cfg.volatility_window)
        self.full_klines_data: List[Dict[str, Any]] = []

        # Tq Objects
        self.target_pos_task: Optional[TargetPosTask] = None
        self.futures_klines = None
        self.index_klines = None
        self.quote_main = None

    def _init_api(self):
        token = os.getenv("TQ_ID")
        pa = os.getenv("TQ_PASS")
        self.api = TqApi(
            backtest=TqBacktest(start_dt=self.cfg.start_dt, end_dt=self.cfg.end_dt),
            account=self.sim_account,
            auth=TqAuth(token, pa)
        )

        # Initialize quotes and klines
        quote = self.api.get_quote(self.cfg.futures_symbol)
        self.current_underlying = quote.underlying_symbol
        self.target_pos_task = TargetPosTask(self.api, self.current_underlying)

        self.futures_klines = self.api.get_kline_serial(
            self.cfg.futures_symbol, self.cfg.duration,
            data_length=self.cfg.data_length, fill_min_period=0
        )
        self.index_klines = self.api.get_kline_serial(
            self.cfg.index_symbol, self.cfg.duration,
            data_length=self.cfg.data_length, fill_min_period=0
        )
        self.quote_main = self.api.get_quote(self.cfg.futures_symbol)

    def _calc_annualized_basis(self, fut_price: float, spot_price: float, days: int) -> Optional[float]:
        if pd.isna(fut_price) or pd.isna(spot_price) or days <= 0 or spot_price == 0:
            return None
        basis_ratio = (spot_price - fut_price) / spot_price
        return round(basis_ratio * 365 / days * 100, 3)

    def _handle_trades(self):
        trades = self.api.get_trade()
        for trade_id, trade in trades.items():
            trade_symbol = f"{trade.exchange_id}.{trade.instrument_id}"
            if trade_symbol == self.current_underlying and trade_id not in self.processed_trade_ids:
                trade_time = datetime.fromtimestamp(trade.trade_date_time / 1e9)
                logger.info(f"--- 交易成功通知 ---")
                logger.info(f"Trade时间:{trade_time.strftime('%Y-%m-%d %H:%M:%S.%f')}, 价格:{trade.price}, 数量:{trade.volume}, 方向:{trade.direction}")
                self.processed_trade_ids.add(trade_id)

    def _handle_main_switch(self):
        if self.api.is_changing(self.quote_main, "underlying_symbol"):
            new_underlying = self.quote_main.underlying_symbol
            logger.info(f"【主力切换】{self.current_underlying or '开始'} → {new_underlying} | 时间: {self.quote_main.datetime}")
            self.current_underlying = new_underlying
            self.target_pos_task = TargetPosTask(self.api, self.current_underlying)
            self.has_opened_in_current_main = False

    def _flush_data_to_disk(self, is_final: bool = False):
        if not self.full_klines_data:
            return

        chunk_df = pd.DataFrame(self.full_klines_data)
        chunk_df["datetime"] = pd.to_datetime(chunk_df["datetime"], unit="ns")
        is_first_write = not os.path.exists(self.cfg.csv_file)
        chunk_df.to_csv(self.cfg.csv_file, mode='a', index=False, header=is_first_write)
        self.full_klines_data.clear()
        if not is_final:
            logger.info(f"💾 已自动同步数据至磁盘，内存已释放")

    def _get_vol_adjusted_volume(self) -> int:
        if len(self.vol_window) >= self.cfg.volatility_window:
            returns = pd.Series(list(self.vol_window)).pct_change().dropna()
            ann_vol = returns.std() * (242 ** 0.5)
            return max(1, int(self.cfg.default_trade_volume * (self.cfg.target_volatility / max(0.01, ann_vol))))
        return self.cfg.default_trade_volume

    def _process_new_bars(self):
        if not self.api.is_changing(self.futures_klines):
            return

        new_bars = self.futures_klines[
            (self.futures_klines["datetime"] > self.last_bar_dt) &
            (self.futures_klines["datetime"] >= self.cfg.start_nano)
        ]

        for _, row in new_bars.iterrows():
            fut_dt, fut_close = row["datetime"], row["close"]
            idx_match = self.index_klines[self.index_klines["datetime"] == fut_dt]

            if idx_match.empty:
                self.full_klines_data.append(row.to_dict())
                continue

            idx_close = idx_match.iloc[0]["close"]
            test_time = pd.to_datetime(fut_dt, unit='ns')

            # Feature calculation
            discount_bp = round(((idx_close - fut_close) / idx_close) * 10000, 2) if idx_close > 0 else 0
            quote = self.api.get_quote(self.cfg.futures_symbol)
            expire_days = quote.underlying_quote.expire_rest_days
            position = self.api.get_position(self.current_underlying)
            ann_basis = self._calc_annualized_basis(fut_close, idx_close, expire_days)

            # Indicators
            index_sma = self.index_klines["close"].rolling(window=self.cfg.index_sma_period).mean().iloc[-1]
            stats = get_ic_annualized_basis_percentile(5, ann_basis) if ann_basis else {"current_percentile": 50, "p75": self.cfg.annualized_basis_threshold}
            basis_percentile = stats["current_percentile"]
            dynamic_threshold = stats["p75"]

            self._evaluate_and_execute(
                ann_basis, dynamic_threshold, expire_days, position,
                test_time, idx_close, fut_close, index_sma, basis_percentile
            )

            # Record Data
            row_dict = {
                **row.to_dict(),
                "index_close": idx_close, "discount_bp": discount_bp,
                "ann_basis": ann_basis, "basis_percentile": basis_percentile,
                "balance": self.api.get_account().balance
            }
            self.full_klines_data.append(row_dict)

            # Update Windows
            if ann_basis is not None: self.basis_window.append(ann_basis)
            if idx_close > 0: self.vol_window.append(idx_close)

            if len(self.full_klines_data) >= self.cfg.chunk_size:
                self._flush_data_to_disk()

        if not new_bars.empty:
            self.last_bar_dt = self.futures_klines.iloc[-1]["datetime"]

    def _evaluate_and_execute(self, ann_basis, threshold, expire_days, position,
                              test_time, idx_close, fut_close, index_sma, basis_perc):
        # 1. Entry Logic
        if (ann_basis is not None and ann_basis > threshold and
            expire_days > self.cfg.min_days_to_expiry_open and
            position.pos_long == 0 and test_time.date() > self.cfg.start_dt and
            idx_close > index_sma and not self.has_opened_in_current_main):

            vol = self._get_vol_adjusted_volume()
            logger.info(f"🚨【贴水报警】合约: {self.current_underlying} 时间: {test_time} | 年化贴水: {ann_basis:.2f}% | 动态阈值: {threshold:.2f}")
            self.target_pos_task.set_target_volume(vol)
            self.has_opened_in_current_main = True
            self.entry_ann_basis = ann_basis
            logger.info(f"✅ 已下达【买入 {vol} 手】指令")

        # 2. Profit Taking
        elif position.pos_long > 0 and self.entry_ann_basis:
            repair_pct = (self.entry_ann_basis - ann_basis) / self.entry_ann_basis
            if repair_pct >= self.cfg.profit_taking_basis_pct:
                logger.info(f"💰【止盈平仓】合约: {self.current_underlying} 修复率: {repair_pct:.2%}")
                self.target_pos_task.set_target_volume(0)
                self.has_opened_in_current_main = True
                self.entry_ann_basis = None

        # 3. Expiry Close
        elif expire_days <= self.cfg.max_days_to_expiry_close and position.pos_long > 0:
            logger.info(f"⏰【临期平仓】合约: {self.current_underlying} 剩余天数: {expire_days}")
            self.target_pos_task.set_target_volume(0)
            self.has_opened_in_current_main = True

    def run(self):
        """Execute the backtest."""
        self._init_api()
        start_time = time.perf_counter()

        try:
            while True:
                self.api.wait_update()
                self._handle_trades()
                self._handle_main_switch()
                self._process_new_bars()

        except BacktestFinished:
            logger.info("\n回测完成，正在汇总数据...")
            self._flush_data_to_disk(is_final=True)

            if os.path.exists(self.cfg.csv_file):
                final_df = pd.read_csv(self.cfg.csv_file)
                PerformanceAnalyzer.calculate_metrics(final_df, self.cfg, self.api.get_account().balance)

        except ConnectTimeout:
            logger.exception("Network timeout during backtest.")
        finally:
            logger.info(f"运行时长：{(time.perf_counter() - start_time) / 60:.2f} 分")
            if self.api:
                self.api.close()


if __name__ == "__main__":
    config = StrategyConfig()
    strategy = ICBasisRollerStrategy(config)
    strategy.run()
