import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Dict, Optional, Set, Any
from pathlib import Path
from requests import ConnectTimeout

import pandas as pd
import numpy as np
from pandas import DataFrame
from tqsdk import TqApi, TqSim, TqBacktest, TqAuth, BacktestFinished, TargetPosTask

# --- Setup Logging ---
# Assuming these exist in the environment as per ic_roller_backtest.py
from utils.logging_config import setup_logging
from utils.ic_net_short_ratio import run_single
from tq.generate_ic_basis_cache import get_ic_annualized_basis_percentile

setup_logging()
logger = logging.getLogger(__name__)

@dataclass
class StrategyConfig:
    """Strategy configuration parameters."""
    futures_symbol: str = "KQ.m@CFFEX.IC"
    index_symbol: str = "SSE.000905"
    duration: int = 60 * 60 * 24  # Daily K-line
    duration_minutes: int = 90
    data_length: int = 10
    initial_balance: float = 10_000_000.0

    # Entry/Exit Thresholds
    annualized_basis_threshold: float = 8.0
    min_days_to_expiry_open: int = 7
    max_days_to_expiry_close: int = 6
    profit_taking_basis_pct: float = 0.5

    # Advanced Filters
    index_sma_period: int = 20
    volatility_window: int = 20
    target_volatility: float = 0.15
    default_trade_volume: int = 1

    # Backtest Period (Will be overridden by data range)
    start_dt: date = date(2026, 4, 1)
    end_dt: date = date.today()

    @property
    def csv_file(self) -> str:
        return f"IC_local_results_{self.start_dt}_{self.end_dt}.csv"

class PerformanceAnalyzer:
    """Helper class to calculate and log strategy performance."""

    @staticmethod
    def calculate_metrics(df: pd.DataFrame, initial_balance: float):
        if df.empty or "balance" not in df.columns:
            logger.info("No balance data available for performance analysis.")
            return

        df["datetime"] = pd.to_datetime(df["datetime"])
        final_balance = df["balance"].iloc[-1]

        # 1. CAGR
        start_date = df["datetime"].iloc[0].date()
        end_date = df["datetime"].iloc[-1].date()
        days = (end_date - start_date).days
        cagr = (final_balance / initial_balance) ** (365.0 / max(days, 1)) - 1

        # 2. Max Drawdown
        df["cum_max_balance"] = df["balance"].cummax()
        df["drawdown"] = (df["balance"] - df["cum_max_balance"]) / df["cum_max_balance"]
        max_drawdown = df["drawdown"].min()

        # 3. Sharpe Ratio
        returns = df["balance"].pct_change().dropna()
        sharpe = (returns.mean() / returns.std() * (242 ** 0.5)) if returns.std() > 0 else 0

        logger.info("📈 【本地回测绩效评估】")
        logger.info(f"   起始日期: {start_date} | 结束日期: {end_date}")
        logger.info(f"   起始资金: {initial_balance:,.2f}")
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

class LocalICBasisRollerStrategy:
    """Strategy implementation using local K-line data."""

    def __init__(self, config: StrategyConfig):

        self.cfg = config
        self.api: Optional[TqApi] = None
        self.sim_account = TqSim(init_balance=self.cfg.initial_balance, account_id='bigo')
        self.target_pos_task: Optional[TargetPosTask] = None

        self.current_dir = Path(__file__).resolve().parent

        # State Variables
        self.balance = self.cfg.initial_balance
        self.current_underlying: str = ""
        self.pos_long = 0
        self.entry_price = 0.0
        self.entry_ann_basis = None
        self.has_opened_in_current_main = False
        self.last_symbol = None
        self.trades = None
        self.processed_trade_ids: Set[str] = set()

        # Windows
        self.vol_window = deque(maxlen=self.cfg.volatility_window)
        self.results_data = []

    def _init_api(self):
        token = os.getenv("TQ_ID")
        pa = os.getenv("TQ_PASS")
        self.api = TqApi(
            backtest=TqBacktest(start_dt=self.cfg.start_dt, end_dt=self.cfg.end_dt),
            account=self.sim_account,
            auth=TqAuth(token, pa)
        )

        self.trades = self.api.get_trade()

        self.futures_klines = self.api.get_kline_serial(
            self.cfg.futures_symbol, self.cfg.duration,
            data_length=self.cfg.data_length, fill_min_period=0
        )


    def _handle_trades(self):
        if self.api.is_changing(self.trades):
            trades = self.api.get_trade()
            for trade_id, trade in trades.items():
                trade_symbol = f"{trade.exchange_id}.{trade.instrument_id}"
                if trade_symbol == self.current_underlying and trade_id not in self.processed_trade_ids:
                    trade_time = pd.to_datetime(trade.trade_date_time, unit='ns', utc=True).tz_convert('Asia/Shanghai')
                    logger.info(f"--- 交易成功通知 ---")
                    logger.info(f"Trade时间:{trade_time}, 价格:{trade.price}, 数量:{trade.volume}, 方向:{trade.direction}")
                    self.processed_trade_ids.add(trade_id)

    def _calc_annualized_basis(self, fut_price: float, spot_price: float, days: int) -> Optional[float]:
        if pd.isna(fut_price) or pd.isna(spot_price) or days <= 0 or spot_price <= 0:
            return None
        basis_ratio = (spot_price - fut_price) / spot_price
        return round(basis_ratio * 365 / days * 100, 3)

    def _get_vol_adjusted_volume(self) -> int:
        if len(self.vol_window) >= self.cfg.volatility_window:
            returns = pd.Series(list(self.vol_window)).pct_change().dropna()
            ann_vol = returns.std() * (242 ** 0.5)
            if ann_vol > 0:
                return max(1, int(self.cfg.default_trade_volume * (self.cfg.target_volatility / max(0.01, ann_vol))))
        return self.cfg.default_trade_volume

    def load_data(self):
        data_file = self.current_dir / f"IC0-日-K线.csv"
        expire_file = self.current_dir / "future_expires.csv"

        if not data_file.exists():
            raise FileNotFoundError(f"Data file not found: {data_file}")
        if not expire_file.exists():
            raise FileNotFoundError(f"Expire file not found: {expire_file}")

        # Load K-lines
        df = pd.read_csv(data_file)
        df['datetime'] = pd.to_datetime(df['datetime'])
        # Drop rows where main info is missing
        df = df.dropna(subset=['close', 'close1'])

        # Load Expire info
        expire_df = pd.read_csv(expire_file)
        expire_df['datetime'] = pd.to_datetime(expire_df['datetime'])

        # Extract date for merge
        df['date_str'] = df['datetime'].dt.strftime('%Y-%m-%d')
        expire_df['date_str'] = expire_df['datetime'].dt.strftime('%Y-%m-%d')

        # Merge
        expire_df = expire_df[['date_str', 'expire_rest_days', 'KQ.m@CFFEX.IC']]
        merged = pd.merge(df, expire_df, on='date_str', how='left')

        return merged.sort_values('datetime')

    def _process_new_bars(self, df: DataFrame):
        if self.api.is_changing(self.futures_klines.iloc[-1], "datetime"):
            latest = pd.to_datetime(self.futures_klines.iloc[-1]["datetime"], unit='ns', utc=True).tz_convert('Asia/Shanghai')
            kline = df[df['datetime'] == latest].iloc[0]
            test_time = kline['datetime']
            fut_close = kline['close']
            idx_close = kline['close1']
            expire_days = kline['expire_rest_days']

            symbol = kline['KQ.m@CFFEX.IC'].removeprefix('CFFEX.')

            if symbol != self.current_underlying:
                self.current_underlying = symbol
                logger.info(f"current_underlying={self.current_underlying}  symbol={symbol}")
                self.target_pos_task = TargetPosTask(self.api, self.current_underlying)
                self.has_opened_in_current_main = False
                logger.info(
                    f"【主力切换】{self.current_underlying or '开始'} → {symbol} | 时间: {test_time}")

            logger.info(f"{latest} ICO({symbol}):close={fut_close} CS500:close={idx_close}")

            # Pre-calculate SMA for efficiency
            # 选取历史k线做均线
            klines_his = df[df['datetime'] < latest]
            sma_df = klines_his['close1'].rolling(window=self.cfg.index_sma_period).mean()
            if not sma_df.empty:
                index_sma = sma_df.iloc[-1]
            else:
                index_sma = 0

            # 1. Handle Main Switch
            if symbol != self.last_symbol:
                if self.last_symbol is not None:
                    logger.info(f"【主力切换】{self.last_symbol} → {symbol} | 时间: {test_time}")
                    # If we have a position, we should roll it or close it?
                    # The Tq strategy closes and sets has_opened_in_current_main = False
                    if self.pos_long > 0:
                        logger.info(f"⏰【换月平仓】合约: {self.last_symbol}")
                        self._close_position(fut_close, test_time)

                self.last_symbol = symbol
                self.has_opened_in_current_main = False

            # 2. Calculate Features
            ann_basis = self._calc_annualized_basis(fut_close, idx_close, expire_days)
            # Dynamic Threshold (Percentile)
            stats = get_ic_annualized_basis_percentile(current_ann_basis=ann_basis) if ann_basis is not None else {
                "current_percentile": 50, "p75": self.cfg.annualized_basis_threshold}
            basis_perc = stats.get("current_percentile", 50)
            dynamic_threshold = stats.get("p75", self.cfg.annualized_basis_threshold)
            position = self.api.get_position(symbol)

            # 3. Strategy Logic
            self._evaluate_and_execute(
                ann_basis, dynamic_threshold, expire_days, position,
                test_time, idx_close, fut_close, index_sma, basis_perc
            )

            # 4. Record Data
            self.results_data.append({
                "datetime": test_time,
                "close": fut_close,
                "index_close": idx_close,
                "ann_basis": ann_basis,
                "basis_percentile": basis_perc,
                "balance": self.api.get_account().balance,
                "pos_long": self.api.get_position(symbol).pos_long,
                "symbol": symbol
            })

            # Update volatility window
            if idx_close > 0:
                self.vol_window.append(idx_close)

    def run(self):
        df = self.load_data().sort_values(by='datetime')
        end = df["datetime"].iloc[-1].date()
        logger.info(f"Loaded {len(df)} records for backtest.")
        self.cfg.end_dt = end
        self._init_api()
        start_time = time.perf_counter()


        try:
            while True:
                self.api.wait_update()
                self._handle_trades()
                self._process_new_bars(df)

        except BacktestFinished:
            logger.info("\n回测完成，正在汇总数据...")

            # Summary
            results_df = pd.DataFrame(self.results_data)
            PerformanceAnalyzer.calculate_metrics(df=results_df, initial_balance=self.cfg.initial_balance)
            output_file = self.current_dir / self.cfg.csv_file
            results_df.to_csv(output_file, index=False)
            logger.info(f"Results saved to {output_file}")

        except ConnectTimeout:
            logger.exception("Network timeout during backtest.")
        finally:
            logger.info(f"运行时长：{(time.perf_counter() - start_time) / 60:.2f} 分")
            if self.api:
                self.api.close()


    def _evaluate_and_execute(self, ann_basis, threshold, expire_days, position,
                              test_time, idx_close, fut_close, index_sma, basis_perc):

        short_ratio = run_single(date=test_time.strftime('%Y-%m-%d'))
        if short_ratio is None or not short_ratio:
            logger.info(f"{test_time}:当天净空比不存在")
        # 1. Entry Logic
        if (ann_basis is not None and ann_basis > threshold and
                expire_days > self.cfg.min_days_to_expiry_open and
                position.pos_long == 0 and test_time.date() > self.cfg.start_dt and
                idx_close > index_sma and not self.has_opened_in_current_main):

            vol = self._get_vol_adjusted_volume()
            logger.info(
                f"🚨【贴水报警】合约: {self.current_underlying} 时间: {test_time} | 年化贴水: {ann_basis:.2f}% | 动态阈值: {threshold:.2f}")
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

    def _open_position(self, price, volume, ann_basis, dt):
        self.pos_long = volume
        self.entry_price = price
        self.entry_ann_basis = ann_basis
        logger.info(f"✅ 【买入开仓】价格: {price}, 数量: {volume}, 时间: {dt}")

    def _close_position(self, price, dt):
        # Calculate PnL (multiplier for IC is 200)
        pnl = (price - self.entry_price) * self.pos_long * 200
        self.balance += pnl
        logger.info(f"❌ 【卖出平仓】价格: {price}, 数量: {self.pos_long}, PnL: {pnl:.2f}, 时间: {dt}")
        self.pos_long = 0
        self.entry_price = 0.0
        self.entry_ann_basis = None

if __name__ == "__main__":
    config = StrategyConfig()
    strategy = LocalICBasisRollerStrategy(config)
    strategy.run()
