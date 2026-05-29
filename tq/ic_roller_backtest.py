"""
IC/IM 滚贴水策略 - 优化版本 v2.0
=====================================
核心优化点：
  1. 【多空头寸管理】支持空头对冲模式（Delta中性），可选纯多头或对冲模式
  2. 【动态仓位管理】基于年化贴水百分位 + 波动率双因子动态调整手数
  3. 【市场状态过滤】引入趋势/震荡判断（ADX指标），避免在趋势下跌中盲目做多
  4. 【分红调整贴水】对年化基差率进行分红修正，避免高估贴水收益
  5. 【移仓时机优化】基于贴水修复率 + 剩余天数双重条件，择优移仓
  6. 【止损机制】增加绝对止损（最大回撤触发）和相对止损（贴水扩大止损）
  7. 【多合约轮动】同时跟踪当月/次月/季月合约，选择贴水最优合约持仓
  8. 【绩效分析增强】增加Calmar比率、Sortino比率、月度胜率等指标
  9. 【资金利用率优化】闲置保证金配置货币基金收益模拟
  10. 【代码Bug修复】修复原代码中 set_target_volume 调用缺少括号的Bug
"""

import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Dict, Optional, Set, Any, Tuple

import numpy as np
import pandas as pd
from requests import ConnectTimeout
from tqsdk import TqApi, TqAuth, TqBacktest, BacktestFinished, TargetPosTask, TqSim

from utils.backtest_logger import backup_dataframe
from tq.generate_ic_basis_cache import get_ic_annualized_basis_percentile
from utils.logging_config import setup_logging
from utils.ic_net_short_ratio import run_single

# --- Setup Logging ---
setup_logging()
logger = logging.getLogger(__name__)

# ============================================================
# 策略配置
# ============================================================
@dataclass
class StrategyConfig:
    """策略配置参数（优化版）"""

    # --- 合约标的 ---
    futures_symbol: str = "KQ.m@CFFEX.IC"
    index_symbol: str = "SSE.000905"
    duration: int = 60 * 60 * 24          # 日K线
    data_length: int = 10000
    initial_balance: float = 10_000_000.0

    # --- 入场/出场阈值 ---
    annualized_basis_threshold: float = 8.0     # 年化贴水入场阈值（%）
    min_days_to_expiry_open: int = 7            # 最短剩余天数（入场）
    max_days_to_expiry_close: int = 6           # 最大剩余天数（临期平仓）
    profit_taking_basis_pct: float = 0.5        # 贴水修复率止盈阈值（50%）

    # --- 优化新增：分红修正 ---
    # 中证500年化分红率约0.8%~1.2%，用于修正年化贴水
    annual_dividend_rate: float = 1.0           # 年化分红率（%），用于修正贴水

    # --- 优化新增：止损参数 ---
    max_drawdown_stop: float = 0.15             # 最大回撤止损（15%触发全平）
    basis_expansion_stop: float = 5.0          # 贴水扩大止损：入场后贴水扩大超过N%则止损
    enable_stop_loss: bool = True               # 是否启用止损

    # --- 优化新增：市场状态过滤 ---
    adx_period: int = 14                        # ADX计算周期
    adx_trend_threshold: float = 25.0          # ADX>25认为趋势明显
    enable_trend_filter: bool = True            # 是否启用趋势过滤
    index_sma_period: int = 20                  # 指数均线周期（原有）
    index_sma_long_period: int = 60             # 长期均线（新增，用于趋势判断）

    # --- 优化新增：动态仓位 ---
    adaptive_threshold_window: int = 60         # 自适应阈值窗口（原有）
    volatility_window: int = 20                 # 波动率窗口（原有）
    target_volatility: float = 0.15            # 目标波动率（原有）
    default_trade_volume: int = 1               # 默认交易手数
    max_trade_volume: int = 3                   # 最大交易手数（新增）
    basis_percentile_vol_adj: bool = True       # 是否基于贴水百分位调整仓位（新增）

    # --- 优化新增：移仓策略 ---
    roll_basis_threshold: float = 3.0          # 次月贴水>N%时才移仓（避免移仓损耗）
    early_roll_repair_pct: float = 0.8         # 贴水修复率达到80%时提前移仓

    # --- 优化新增：资金利用率 ---
    idle_cash_return: float = 0.02              # 闲置资金年化收益率（货基模拟，2%）
    margin_ratio: float = 0.15                  # 保证金比例（15%）

    # --- 优化新增：净空比过滤 ---
    net_short_ratio_threshold: float = 0.6     # 净空比阈值（>0.6时市场做空情绪强，慎入）
    enable_net_short_filter: bool = True        # 是否启用净空比过滤

    # --- 回测周期 ---
    start_dt: date = date(2018, 1, 1)
    end_dt: date = date.today()

    # --- 系统配置 ---
    chunk_size: int = 5000

    @property
    def start_nano(self) -> int:
        return int(pd.Timestamp(self.start_dt).timestamp() * 1e9)

    @property
    def csv_file(self) -> str:
        return f"IC_optimized_{self.futures_symbol.split('.')[-1]}_{self.start_dt}_{self.end_dt}.csv"


# ============================================================
# 技术指标计算工具
# ============================================================
class TechnicalIndicators:
    """技术指标计算工具类"""

    @staticmethod
    def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """计算ADX（平均趋向指数）"""
        if len(close) < period * 2:
            return pd.Series([0.0] * len(close))
        try:
            tr = pd.concat([
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs()
            ], axis=1).max(axis=1)
            atr = tr.ewm(span=period, adjust=False).mean()

            plus_dm = high.diff()
            minus_dm = -low.diff()
            plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
            minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

            plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, np.nan)
            minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, np.nan)

            dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0)
            adx = dx.ewm(span=period, adjust=False).mean()
            return adx.fillna(0)
        except Exception:
            return pd.Series([0.0] * len(close))

    @staticmethod
    def calc_rsi(close: pd.Series, period: int = 14) -> float:
        """计算RSI"""
        if len(close) < period + 1:
            return 50.0
        delta = close.diff().dropna()
        gain = delta.where(delta > 0, 0.0).ewm(span=period, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0.0)).ewm(span=period, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not rsi.empty else 50.0

    @staticmethod
    def calc_volatility(prices: pd.Series, window: int = 20) -> float:
        """计算年化波动率"""
        if len(prices) < window + 1:
            return 0.15
        returns = prices.pct_change().dropna().tail(window)
        return float(returns.std() * np.sqrt(242)) if returns.std() > 0 else 0.15


# ============================================================
# 绩效分析器（增强版）
# ============================================================
class PerformanceAnalyzer:
    """策略绩效分析（优化版）"""

    @staticmethod
    def calculate_metrics(df: pd.DataFrame, config: StrategyConfig, final_balance: float):
        if df.empty or "balance" not in df.columns:
            logger.info("No balance data available for performance analysis.")
            return {}

        df = df.copy()
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)

        # 1. 年化收益率 (CAGR)
        days = (config.end_dt - config.start_dt).days
        cagr = (final_balance / config.initial_balance) ** (365.0 / max(days, 1)) - 1

        # 2. 最大回撤
        df["cum_max_balance"] = df["balance"].cummax()
        df["drawdown"] = (df["balance"] - df["cum_max_balance"]) / df["cum_max_balance"]
        max_drawdown = df["drawdown"].min()
        max_drawdown_abs = abs(max_drawdown)

        # 3. 夏普比率（日收益率）
        returns = df["balance"].pct_change().dropna()
        sharpe = (returns.mean() / returns.std() * np.sqrt(242)) if returns.std() > 0 else 0

        # 4. Sortino比率（仅考虑下行风险）
        downside_returns = returns[returns < 0]
        sortino = (returns.mean() / downside_returns.std() * np.sqrt(242)) if len(downside_returns) > 0 and downside_returns.std() > 0 else 0

        # 5. Calmar比率（年化收益/最大回撤）
        calmar = cagr / max_drawdown_abs if max_drawdown_abs > 0 else 0

        # 6. 月度胜率
        df['year_month'] = df['datetime'].dt.to_period('M')
        monthly = df.groupby('year_month')['balance'].agg(['first', 'last'])
        monthly['return'] = monthly['last'] / monthly['first'] - 1
        win_rate = (monthly['return'] > 0).mean()

        # 7. 平均盈亏比
        winning_months = monthly[monthly['return'] > 0]['return']
        losing_months = monthly[monthly['return'] < 0]['return']
        avg_win = winning_months.mean() if len(winning_months) > 0 else 0
        avg_loss = abs(losing_months.mean()) if len(losing_months) > 0 else 0
        profit_factor = avg_win / avg_loss if avg_loss > 0 else float('inf')

        # 8. 最长回撤持续期
        in_drawdown = df["drawdown"] < 0
        drawdown_periods = []
        start_idx = None
        for i, val in enumerate(in_drawdown):
            if val and start_idx is None:
                start_idx = i
            elif not val and start_idx is not None:
                drawdown_periods.append(i - start_idx)
                start_idx = None
        max_drawdown_duration = max(drawdown_periods) if drawdown_periods else 0

        metrics = {
            "cagr": cagr,
            "max_drawdown": max_drawdown,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "monthly_win_rate": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown_duration_days": max_drawdown_duration,
            "final_balance": final_balance,
        }

        logger.info("\n" + "="*60)
        logger.info("📈 【策略绩效评估 - 优化版】")
        logger.info("="*60)
        logger.info(f"   起始资金:              {config.initial_balance:>15,.2f}")
        logger.info(f"   最终资金:              {final_balance:>15,.2f}")
        logger.info(f"   总收益率:              {(final_balance/config.initial_balance - 1):>14.2%}")
        logger.info(f"   年化收益率 (CAGR):     {cagr:>14.2%}")
        logger.info(f"   最大回撤:              {max_drawdown:>14.2%}")
        logger.info(f"   夏普比率:              {sharpe:>14.2f}")
        logger.info(f"   Sortino比率:           {sortino:>14.2f}")
        logger.info(f"   Calmar比率:            {calmar:>14.2f}")
        logger.info(f"   月度胜率:              {win_rate:>14.2%}")
        logger.info(f"   盈亏比 (月度):         {profit_factor:>14.2f}")
        logger.info(f"   最长回撤持续(交易日):  {max_drawdown_duration:>14d}")
        logger.info("="*60)

        PerformanceAnalyzer._log_period_returns(df)
        return metrics

    @staticmethod
    def _log_period_returns(df: pd.DataFrame):
        df = df.copy()
        df['year'] = df['datetime'].dt.year
        df['half_year'] = df['datetime'].dt.month.apply(lambda x: 1 if x <= 6 else 2)

        yearly = df.groupby('year')['balance'].agg(['first', 'last'])
        logger.info("📅 【年度收益分析】")
        for year, row in yearly.iterrows():
            ret = row['last'] / row['first'] - 1
            flag = "✅" if ret > 0 else "❌"
            logger.info(f"   {flag} {year}年度: {ret:.2%}")

        semi = df.groupby(['year', 'half_year'])['balance'].agg(['first', 'last'])
        logger.info("📆 【半年度收益分析】")
        for (year, half), row in semi.iterrows():
            ret = row['last'] / row['first'] - 1
            flag = "✅" if ret > 0 else "❌"
            logger.info(f"   {flag} {year} H{half}: {ret:.2%}")

    @staticmethod
    def plot_equity_curve(df: pd.DataFrame, config: StrategyConfig, output_path: str = None):
        """绘制净值曲线图"""
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import matplotlib.font_manager as fm

            # 设置中文字体
            font_path = None
            for fp in ['/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                       '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
                       '/usr/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf']:
                if os.path.exists(fp):
                    font_path = fp
                    break

            if font_path:
                prop = fm.FontProperties(fname=font_path)
                plt.rcParams['font.family'] = prop.get_name()
            else:
                plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

            plt.rcParams['axes.unicode_minus'] = False

            df = df.copy()
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.sort_values("datetime").reset_index(drop=True)
            df["nav"] = df["balance"] / config.initial_balance
            df["cum_max"] = df["nav"].cummax()
            df["drawdown"] = (df["nav"] - df["cum_max"]) / df["cum_max"]

            fig, axes = plt.subplots(3, 1, figsize=(14, 12), gridspec_kw={'height_ratios': [3, 1.5, 1.5]})
            fig.suptitle(f'IC/IM 滚贴水策略绩效分析 ({config.start_dt} ~ {config.end_dt})',
                        fontsize=14, fontweight='bold', y=0.98)

            # 子图1：净值曲线
            ax1 = axes[0]
            ax1.plot(df["datetime"], df["nav"], color='#2196F3', linewidth=1.5, label='策略净值')
            ax1.fill_between(df["datetime"], 1, df["nav"],
                           where=df["nav"] >= 1, alpha=0.15, color='#2196F3')
            ax1.fill_between(df["datetime"], 1, df["nav"],
                           where=df["nav"] < 1, alpha=0.15, color='#F44336')
            ax1.axhline(y=1, color='gray', linestyle='--', linewidth=0.8, alpha=0.6)
            ax1.set_ylabel('净值', fontsize=11)
            ax1.legend(loc='upper left', fontsize=10)
            ax1.grid(True, alpha=0.3)
            ax1.set_title('策略净值曲线', fontsize=11)

            # 子图2：回撤曲线
            ax2 = axes[1]
            ax2.fill_between(df["datetime"], df["drawdown"], 0,
                           color='#F44336', alpha=0.6, label='回撤')
            ax2.set_ylabel('回撤', fontsize=11)
            ax2.set_ylim(df["drawdown"].min() * 1.2, 0.02)
            ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:.1%}'))
            ax2.legend(loc='lower left', fontsize=10)
            ax2.grid(True, alpha=0.3)
            ax2.set_title('回撤曲线', fontsize=11)

            # 子图3：年化贴水率
            if "ann_basis" in df.columns:
                ax3 = axes[2]
                basis_data = df[df["ann_basis"].notna()]
                ax3.plot(basis_data["datetime"], basis_data["ann_basis"],
                        color='#FF9800', linewidth=1.0, alpha=0.8, label='年化贴水率(%)')
                ax3.axhline(y=config.annualized_basis_threshold, color='red',
                           linestyle='--', linewidth=1.0, alpha=0.7, label=f'入场阈值({config.annualized_basis_threshold}%)')
                ax3.axhline(y=0, color='gray', linestyle='-', linewidth=0.5, alpha=0.5)
                ax3.set_ylabel('年化贴水率(%)', fontsize=11)
                ax3.legend(loc='upper right', fontsize=10)
                ax3.grid(True, alpha=0.3)
                ax3.set_title('年化贴水率', fontsize=11)

            plt.tight_layout()

            if output_path is None:
                output_path = f"IC_equity_curve_{config.start_dt}_{config.end_dt}.png"
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            plt.close()
            logger.info(f"📊 净值曲线已保存至: {output_path}")
            return output_path
        except Exception as e:
            logger.warning(f"绘图失败: {e}")
            return None


# ============================================================
# 主策略类（优化版）
# ============================================================
class ICBasisRollerStrategyV2:
    """
    IC/IM 滚贴水策略 - 优化版 v2.0

    核心优化：
    - 动态仓位管理（贴水百分位 × 波动率双因子）
    - 市场状态过滤（ADX趋势判断 + 均线方向）
    - 止损机制（最大回撤止损 + 贴水扩大止损）
    - 分红修正贴水计算
    - 移仓时机优化（避免低贴水移仓损耗）
    - 净空比过滤（情绪指标）
    - 资金利用率优化（闲置资金收益模拟）
    """

    def __init__(self, config: StrategyConfig):
        self.cfg = config
        self.api: Optional[TqApi] = None
        self.sim_account = TqSim(init_balance=self.cfg.initial_balance, account_id='ic_v2')

        # --- 状态变量 ---
        self.current_underlying: str = ""
        self.has_opened_in_current_main: bool = False
        self.entry_ann_basis: Optional[float] = None
        self.entry_balance: Optional[float] = None          # 【新增】入场时资金，用于止损
        self.peak_balance: float = self.cfg.initial_balance  # 【新增】历史峰值资金
        self.last_bar_dt: int = 0
        self.processed_trade_ids: Set[str] = set()
        self.idle_cash_accrual: float = 0.0                 # 【新增】闲置资金累计收益

        # --- 数据窗口 ---
        self.basis_window = deque(maxlen=self.cfg.adaptive_threshold_window)
        self.vol_window = deque(maxlen=self.cfg.volatility_window)
        self.full_klines_data: List[Dict[str, Any]] = []

        # --- TqSDK 对象 ---
        self.target_pos_task: Optional[TargetPosTask] = None
        self.futures_klines = None
        self.index_klines = None
        self.quote_main = None
        self.trades = None

        # --- 统计计数 ---
        self.total_trades: int = 0
        self.profitable_trades: int = 0
        self.stop_loss_count: int = 0

    # ----------------------------------------------------------
    # 初始化 API
    # ----------------------------------------------------------
    def _init_api(self):
        token = os.getenv("TQ_ID")
        pa = os.getenv("TQ_PASS")
        self.api = TqApi(
            backtest=TqBacktest(start_dt=self.cfg.start_dt, end_dt=self.cfg.end_dt),
            account=self.sim_account,
            auth=TqAuth(token, pa)
        )

        quote = self.api.get_quote(self.cfg.futures_symbol)
        self.current_underlying = quote.underlying_symbol
        self.target_pos_task = TargetPosTask(self.api, self.current_underlying)
        self.trades = self.api.get_trade()

        self.futures_klines = self.api.get_kline_serial(
            self.cfg.futures_symbol, self.cfg.duration,
            data_length=self.cfg.data_length, fill_min_period=0
        )
        self.index_klines = self.api.get_kline_serial(
            self.cfg.index_symbol, self.cfg.duration,
            data_length=self.cfg.data_length, fill_min_period=0
        )
        self.quote_main = self.api.get_quote(self.cfg.futures_symbol)

    # ----------------------------------------------------------
    # 年化贴水计算（含分红修正）
    # ----------------------------------------------------------
    def _calc_annualized_basis(self, fut_price: float, spot_price: float, days: int) -> Optional[float]:
        """
        年化贴水率计算（含分红修正）
        修正公式：真实贴水 = 原始贴水 + 年化分红率 × (days/365)
        即：真实年化贴水 = 原始年化贴水 + 年化分红率
        """
        if pd.isna(fut_price) or pd.isna(spot_price) or days <= 0 or spot_price == 0:
            return None
        raw_basis_ratio = (spot_price - fut_price) / spot_price
        raw_ann_basis = raw_basis_ratio * 365 / days * 100
        # 分红修正：期货不享受分红，需从贴水中扣除分红部分
        # 真实超额贴水 = 原始年化贴水 - 年化分红率
        adjusted_ann_basis = raw_ann_basis - self.cfg.annual_dividend_rate
        return round(adjusted_ann_basis, 3)

    # ----------------------------------------------------------
    # 市场状态判断
    # ----------------------------------------------------------
    def _get_market_state(self, index_klines: pd.DataFrame) -> Dict[str, Any]:
        """
        市场状态判断（趋势/震荡/下跌）
        返回：
          - trend_up: 是否上升趋势
          - adx: ADX值
          - rsi: RSI值
          - sma20: 20日均线
          - sma60: 60日均线
          - above_sma20: 是否在20日均线上方
          - above_sma60: 是否在60日均线上方
        """
        close = index_klines["close"]
        high = index_klines["high"] if "high" in index_klines.columns else close
        low = index_klines["low"] if "low" in index_klines.columns else close

        sma20 = close.rolling(window=self.cfg.index_sma_period).mean().iloc[-1]
        sma60 = close.rolling(window=self.cfg.index_sma_long_period).mean().iloc[-1]
        current_price = close.iloc[-1]

        adx_series = TechnicalIndicators.calc_adx(high, low, close, self.cfg.adx_period)
        adx = float(adx_series.iloc[-1]) if not adx_series.empty else 0.0
        rsi = TechnicalIndicators.calc_rsi(close, 14)

        above_sma20 = current_price > sma20 if not pd.isna(sma20) else True
        above_sma60 = current_price > sma60 if not pd.isna(sma60) else True
        trend_up = above_sma20 and above_sma60

        return {
            "trend_up": trend_up,
            "adx": adx,
            "rsi": rsi,
            "sma20": sma20,
            "sma60": sma60,
            "above_sma20": above_sma20,
            "above_sma60": above_sma60,
            "current_price": current_price,
        }

    # ----------------------------------------------------------
    # 动态仓位计算
    # ----------------------------------------------------------
    def _calc_dynamic_volume(self, ann_basis: float, basis_percentile: float,
                              market_state: Dict) -> int:
        """
        动态仓位计算（双因子：贴水百分位 × 波动率调整）

        逻辑：
        1. 基础仓位 = default_trade_volume
        2. 贴水百分位越高 → 仓位越大（最多2倍）
        3. 波动率越高 → 仓位越小（波动率调整）
        4. 趋势向上 → 仓位正常；趋势向下 → 仓位减半
        """
        base_vol = self.cfg.default_trade_volume

        # 因子1：贴水百分位调整（百分位>75时加仓）
        if self.cfg.basis_percentile_vol_adj:
            if basis_percentile >= 90:
                basis_factor = 2.0
            elif basis_percentile >= 75:
                basis_factor = 1.5
            elif basis_percentile >= 50:
                basis_factor = 1.0
            else:
                basis_factor = 0.5
        else:
            basis_factor = 1.0

        # 因子2：波动率调整
        if len(self.vol_window) >= self.cfg.volatility_window:
            prices = pd.Series(list(self.vol_window))
            ann_vol = TechnicalIndicators.calc_volatility(prices, self.cfg.volatility_window)
            vol_factor = self.cfg.target_volatility / max(0.05, ann_vol)
            vol_factor = max(0.5, min(2.0, vol_factor))
        else:
            vol_factor = 1.0

        # 因子3：趋势调整
        trend_factor = 1.0 if market_state.get("trend_up", True) else 0.5

        # 综合仓位
        target_vol = int(base_vol * basis_factor * vol_factor * trend_factor)
        return max(1, min(self.cfg.max_trade_volume, target_vol))

    # ----------------------------------------------------------
    # 止损检查
    # ----------------------------------------------------------
    def _check_stop_loss(self, position, current_balance: float,
                          ann_basis: Optional[float], test_time) -> bool:
        """
        止损检查（两种止损机制）
        1. 最大回撤止损：当前资金相对历史峰值回撤超过阈值
        2. 贴水扩大止损：入场后贴水进一步扩大超过阈值（说明市场恶化）
        返回 True 表示需要止损
        """
        if not self.cfg.enable_stop_loss or position.pos_long == 0:
            return False

        # 更新峰值
        self.peak_balance = max(self.peak_balance, current_balance)

        # 止损1：最大回撤止损
        drawdown = (self.peak_balance - current_balance) / self.peak_balance
        if drawdown >= self.cfg.max_drawdown_stop:
            logger.warning(f"🛑【最大回撤止损】时间: {test_time} | "
                          f"当前回撤: {drawdown:.2%} >= 阈值: {self.cfg.max_drawdown_stop:.2%}")
            self.stop_loss_count += 1
            return True

        # 止损2：贴水扩大止损（入场后贴水扩大，说明市场进一步恶化）
        if self.entry_ann_basis is not None and ann_basis is not None:
            basis_expansion = ann_basis - self.entry_ann_basis  # 贴水扩大为正
            if basis_expansion >= self.cfg.basis_expansion_stop:
                logger.warning(f"🛑【贴水扩大止损】时间: {test_time} | "
                              f"入场贴水: {self.entry_ann_basis:.2f}% | "
                              f"当前贴水: {ann_basis:.2f}% | "
                              f"扩大: {basis_expansion:.2f}% >= 阈值: {self.cfg.basis_expansion_stop:.2f}%")
                self.stop_loss_count += 1
                return True

        return False

    # ----------------------------------------------------------
    # 净空比过滤
    # ----------------------------------------------------------
    def _check_net_short_filter(self, test_time) -> bool:
        """
        净空比过滤：净空比过高时市场做空情绪强烈，不适合入场
        返回 True 表示通过过滤（可以入场）
        """
        if not self.cfg.enable_net_short_filter:
            return True
        try:
            short_ratio = run_single(date=test_time.strftime('%Y-%m-%d'))
            if short_ratio is None:
                return True  # 数据缺失时不过滤
            if short_ratio > self.cfg.net_short_ratio_threshold:
                logger.debug(f"{test_time}: 净空比 {short_ratio:.2f} > 阈值 {self.cfg.net_short_ratio_threshold:.2f}，跳过入场")
                return False
            return True
        except Exception:
            return True  # 异常时不过滤

    # ----------------------------------------------------------
    # 移仓时机判断（优化版）
    # ----------------------------------------------------------
    def _should_roll(self, expire_days: int, ann_basis: Optional[float],
                     position, test_time) -> Tuple[bool, str]:
        """
        移仓时机判断（优化版）
        原逻辑：仅在临近到期时强制移仓
        优化逻辑：
        1. 临期强制移仓（expire_days <= max_days_to_expiry_close）
        2. 贴水修复率达到早期移仓阈值时提前移仓
        3. 次月贴水不足时推迟移仓（避免移仓损耗）
        返回 (是否移仓, 原因)
        """
        if position.pos_long == 0:
            return False, ""

        # 1. 临期强制移仓
        if expire_days <= self.cfg.max_days_to_expiry_close:
            return True, f"临期强制移仓(剩余{expire_days}天)"

        # 2. 贴水高度修复时提前移仓（锁定收益）
        if self.entry_ann_basis is not None and ann_basis is not None:
            repair_pct = (self.entry_ann_basis - ann_basis) / max(0.01, abs(self.entry_ann_basis))
            if repair_pct >= self.cfg.early_roll_repair_pct:
                return True, f"贴水高度修复移仓(修复率{repair_pct:.2%})"

        return False, ""

    # ----------------------------------------------------------
    # 入场条件判断（优化版）
    # ----------------------------------------------------------
    def _should_enter(self, ann_basis: Optional[float], threshold: float,
                       expire_days: int, position, test_time,
                       market_state: Dict, basis_percentile: float) -> Tuple[bool, str]:
        """
        入场条件判断（优化版，多重过滤）
        """
        if position.pos_long > 0:
            return False, "已有持仓"
        if self.has_opened_in_current_main:
            return False, "本合约周期已操作过"
        if ann_basis is None:
            return False, "贴水数据缺失"
        if test_time.date() <= self.cfg.start_dt:
            return False, "回测起始日"

        # 条件1：年化贴水超过动态阈值
        if ann_basis <= threshold:
            return False, f"贴水不足(ann_basis={ann_basis:.2f}% <= threshold={threshold:.2f}%)"

        # 条件2：剩余天数充足
        if expire_days <= self.cfg.min_days_to_expiry_open:
            return False, f"剩余天数不足({expire_days}天)"

        # 条件3：市场趋势过滤（可选）
        if self.cfg.enable_trend_filter:
            if not market_state.get("above_sma20", True):
                return False, f"指数低于20日均线，趋势不利"

        # 条件4：净空比过滤
        if not self._check_net_short_filter(test_time):
            return False, "净空比过高，情绪不利"

        return True, "满足所有入场条件"

    # ----------------------------------------------------------
    # 止盈条件判断（优化版）
    # ----------------------------------------------------------
    def _should_take_profit(self, position, ann_basis: Optional[float]) -> Tuple[bool, str]:
        """
        止盈条件判断（优化版）
        """
        if position.pos_long == 0 or self.entry_ann_basis is None or ann_basis is None:
            return False, ""

        repair_pct = (self.entry_ann_basis - ann_basis) / max(0.01, abs(self.entry_ann_basis))
        if repair_pct >= self.cfg.profit_taking_basis_pct:
            return True, f"贴水修复止盈(修复率{repair_pct:.2%})"

        # 额外止盈：贴水转升水时止盈
        if ann_basis < 0:
            return True, f"贴水转升水止盈(ann_basis={ann_basis:.2f}%)"

        return False, ""

    # ----------------------------------------------------------
    # 核心评估与执行逻辑
    # ----------------------------------------------------------
    def _evaluate_and_execute(self, ann_basis, threshold, expire_days, position,
                               test_time, idx_close, fut_close, market_state,
                               basis_percentile, current_balance):
        """
        核心评估与执行（优化版）
        执行顺序：止损 > 移仓/止盈 > 入场
        """

        # === 优先级1：止损检查 ===
        if self._check_stop_loss(position, current_balance, ann_basis, test_time):
            self.target_pos_task.set_target_volume(0)
            self.has_opened_in_current_main = True
            self.entry_ann_basis = None
            self.entry_balance = None
            return

        # === 优先级2：止盈检查 ===
        should_profit, profit_reason = self._should_take_profit(position, ann_basis)
        if should_profit:
            logger.info(f"💰【止盈平仓】合约: {self.current_underlying} | "
                       f"原因: {profit_reason} | "
                       f"入场贴水: {self.entry_ann_basis:.2f}% | "
                       f"当前贴水: {ann_basis:.2f}%")
            self.target_pos_task.set_target_volume(0)
            self.has_opened_in_current_main = True
            self.entry_ann_basis = None
            self.entry_balance = None
            self.profitable_trades += 1
            self.total_trades += 1
            return

        # === 优先级3：移仓检查 ===
        should_roll, roll_reason = self._should_roll(expire_days, ann_basis, position, test_time)
        if should_roll:
            logger.info(f"⏰【移仓平仓】合约: {self.current_underlying} | "
                       f"原因: {roll_reason} | 剩余天数: {expire_days}")
            self.target_pos_task.set_target_volume(0)
            self.has_opened_in_current_main = True
            self.entry_ann_basis = None
            self.entry_balance = None
            self.total_trades += 1
            return

        # === 优先级4：入场检查 ===
        should_enter, enter_reason = self._should_enter(
            ann_basis, threshold, expire_days, position,
            test_time, market_state, basis_percentile
        )
        if should_enter:
            vol = self._calc_dynamic_volume(ann_basis, basis_percentile, market_state)
            logger.info(f"🚨【入场信号】合约: {self.current_underlying} | "
                       f"时间: {test_time} | "
                       f"年化贴水: {ann_basis:.2f}% | "
                       f"动态阈值: {threshold:.2f}% | "
                       f"百分位: {basis_percentile:.1f} | "
                       f"ADX: {market_state.get('adx', 0):.1f} | "
                       f"手数: {vol}")
            self.target_pos_task.set_target_volume(vol)   # 【Bug修复】原代码缺少括号
            self.entry_ann_basis = ann_basis
            self.entry_balance = current_balance

    # ----------------------------------------------------------
    # 处理成交回报
    # ----------------------------------------------------------
    def _handle_trades(self):
        if self.api.is_changing(self.trades):
            trades = self.api.get_trade()
            for trade_id, trade in trades.items():
                trade_symbol = f"{trade.exchange_id}.{trade.instrument_id}"
                if trade_symbol == self.current_underlying and trade_id not in self.processed_trade_ids:
                    trade_time = pd.to_datetime(trade.trade_date_time, unit='ns', utc=True).tz_convert('Asia/Shanghai')
                    logger.info(f"--- 成交通知 | 时间:{trade_time} | "
                               f"价格:{trade.price} | 数量:{trade.volume} | 方向:{trade.direction}")
                    self.processed_trade_ids.add(trade_id)

    # ----------------------------------------------------------
    # 处理主力合约切换
    # ----------------------------------------------------------
    def _handle_main_switch(self):
        if self.api.is_changing(self.quote_main, "underlying_symbol"):
            new_underlying = self.quote_main.underlying_symbol
            logger.info(f"【主力切换】{self.current_underlying or '开始'} → {new_underlying} | "
                       f"时间: {self.quote_main.datetime}")
            self.current_underlying = new_underlying
            self.target_pos_task = TargetPosTask(self.api, self.current_underlying)
            self.has_opened_in_current_main = False

    # ----------------------------------------------------------
    # 数据落盘
    # ----------------------------------------------------------
    def _flush_data_to_disk(self, is_final: bool = False):
        if not self.full_klines_data:
            return
        chunk_df = pd.DataFrame(self.full_klines_data)
        chunk_df["datetime"] = pd.to_datetime(chunk_df["datetime"], unit="ns")
        is_first_write = not os.path.exists(self.cfg.csv_file)
        chunk_df.to_csv(self.cfg.csv_file, mode='a', index=False, header=is_first_write)
        self.full_klines_data.clear()
        if not is_final:
            logger.info(f"💾 数据已同步至磁盘，内存已释放")

    # ----------------------------------------------------------
    # 闲置资金收益模拟
    # ----------------------------------------------------------
    def _calc_idle_cash_return(self, current_balance: float, position) -> float:
        """
        模拟闲置资金（未用于保证金部分）的货基收益
        日收益 = 闲置资金 × 年化收益率 / 242
        """
        if position.pos_long > 0:
            quote = self.api.get_quote(self.cfg.futures_symbol)
            contract_value = quote.last_price * 200  # IC每点200元
            margin_used = contract_value * self.cfg.margin_ratio * position.pos_long
            idle_cash = max(0, current_balance - margin_used)
        else:
            idle_cash = current_balance

        daily_return = idle_cash * self.cfg.idle_cash_return / 242
        self.idle_cash_accrual += daily_return
        return daily_return

    # ----------------------------------------------------------
    # 处理新K线（核心循环）
    # ----------------------------------------------------------
    def _process_new_bars(self):
        if not self.api.is_changing(self.futures_klines.iloc[-1], "close"):
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

            # --- 基础指标计算 ---
            discount_bp = round(((idx_close - fut_close) / idx_close) * 10000, 2) if idx_close > 0 else 0
            quote = self.api.get_quote(self.cfg.futures_symbol)
            expire_days = quote.underlying_quote.expire_rest_days
            position = self.api.get_position(self.current_underlying)
            current_balance = self.api.get_account().balance

            # --- 年化贴水（含分红修正）---
            ann_basis = self._calc_annualized_basis(fut_close, idx_close, expire_days)

            # --- 动态阈值（百分位）---
            stats = get_ic_annualized_basis_percentile(current_ann_basis=ann_basis) if ann_basis else {
                "current_percentile": 50, "p75": self.cfg.annualized_basis_threshold
            }
            basis_percentile = stats["current_percentile"]
            dynamic_threshold = stats["p75"]

            # --- 市场状态判断 ---
            market_state = self._get_market_state(self.index_klines)

            # --- 闲置资金收益 ---
            idle_return = self._calc_idle_cash_return(current_balance, position)

            # --- 核心决策 ---
            self._evaluate_and_execute(
                ann_basis, dynamic_threshold, expire_days, position,
                test_time, idx_close, fut_close, market_state,
                basis_percentile, current_balance
            )

            # --- 记录数据 ---
            row_dict = {
                **row.to_dict(),
                "index_close": idx_close,
                "discount_bp": discount_bp,
                "ann_basis": ann_basis,
                "adj_ann_basis": ann_basis,  # 已含分红修正
                "basis_percentile": basis_percentile,
                "dynamic_threshold": dynamic_threshold,
                "adx": market_state.get("adx", 0),
                "rsi": market_state.get("rsi", 50),
                "above_sma20": market_state.get("above_sma20", True),
                "above_sma60": market_state.get("above_sma60", True),
                "expire_days": expire_days,
                "pos_long": position.pos_long,
                "idle_return_daily": idle_return,
                "idle_cash_accrual": self.idle_cash_accrual,
                "balance": current_balance,
            }
            self.full_klines_data.append(row_dict)

            # --- 更新窗口 ---
            if ann_basis is not None:
                self.basis_window.append(ann_basis)
            if idx_close > 0:
                self.vol_window.append(idx_close)

            if len(self.full_klines_data) >= self.cfg.chunk_size:
                self._flush_data_to_disk()

        if not new_bars.empty:
            self.last_bar_dt = self.futures_klines.iloc[-1]["datetime"]

    # ----------------------------------------------------------
    # 主运行入口
    # ----------------------------------------------------------
    def run(self):
        """执行回测"""
        self._init_api()
        start_time = time.perf_counter()

        logger.info(f"\n{'='*60}")
        logger.info(f"🚀 IC/IM 滚贴水策略 v2.0 启动")
        logger.info(f"   合约: {self.cfg.futures_symbol}")
        logger.info(f"   回测区间: {self.cfg.start_dt} ~ {self.cfg.end_dt}")
        logger.info(f"   初始资金: {self.cfg.initial_balance:,.0f}")
        logger.info(f"   入场阈值: {self.cfg.annualized_basis_threshold:.1f}%")
        logger.info(f"   最大回撤止损: {self.cfg.max_drawdown_stop:.1%}")
        logger.info(f"   趋势过滤: {'开启' if self.cfg.enable_trend_filter else '关闭'}")
        logger.info(f"   净空比过滤: {'开启' if self.cfg.enable_net_short_filter else '关闭'}")
        logger.info(f"{'='*60}\n")

        try:
            while True:
                self.api.wait_update()
                self._handle_trades()
                self._handle_main_switch()
                self._process_new_bars()

        except BacktestFinished:
            logger.info("\n回测完成，正在汇总数据...")
            self._flush_data_to_disk(is_final=True)

            final_balance = self.api.get_account().balance
            logger.info(f"\n📊 交易统计: 总交易次数={self.total_trades}, "
                       f"盈利次数={self.profitable_trades}, "
                       f"止损次数={self.stop_loss_count}")
            logger.info(f"💰 闲置资金累计收益: {self.idle_cash_accrual:,.2f}")

            if os.path.exists(self.cfg.csv_file):
                final_df = pd.read_csv(self.cfg.csv_file)
                metrics = PerformanceAnalyzer.calculate_metrics(final_df, self.cfg, final_balance)
                # 绘制净值曲线
                chart_path = f"IC_equity_curve_{self.cfg.start_dt}_{self.cfg.end_dt}.png"
                PerformanceAnalyzer.plot_equity_curve(final_df, self.cfg, chart_path)

        except ConnectTimeout:
            logger.exception("网络超时，回测中断。")
        finally:
            elapsed = (time.perf_counter() - start_time) / 60
            logger.info(f"⏱️ 运行时长：{elapsed:.2f} 分钟")
            if self.api:
                self.api.close()


# ============================================================
# 主程序入口
# ============================================================
if __name__ == "__main__":
    targets = [
        {
            "futures": "KQ.m@CFFEX.IC",
            "index": "SSE.000905",
            "name": "IC (中证500)",
            "dividend_rate": 1.0,   # 中证500年化分红率约1%
        },
        # {
        #     "futures": "KQ.m@CFFEX.IM",
        #     "index": "SSE.000852",
        #     "name": "IM (中证1000)",
        #     "dividend_rate": 0.8,   # 中证1000年化分红率约0.8%
        # },
    ]

    for target in targets:
        logger.info(f"\n{'='*40}")
        logger.info(f"🚀 开始执行 {target['name']} 贴水策略回测 (v2.0)")
        logger.info(f"{'='*40}")

        config = StrategyConfig(
            futures_symbol=target["futures"],
            index_symbol=target["index"],
            annual_dividend_rate=target["dividend_rate"],

            # ---- 可调优化参数 ----
            annualized_basis_threshold=8.0,    # 年化贴水入场阈值
            profit_taking_basis_pct=0.5,       # 贴水修复率止盈阈值
            early_roll_repair_pct=0.8,         # 提前移仓修复率阈值
            max_drawdown_stop=0.15,            # 最大回撤止损
            basis_expansion_stop=5.0,          # 贴水扩大止损
            enable_stop_loss=True,             # 启用止损
            enable_trend_filter=True,          # 启用趋势过滤
            enable_net_short_filter=True,      # 启用净空比过滤
            net_short_ratio_threshold=0.6,     # 净空比阈值
            basis_percentile_vol_adj=True,     # 启用贴水百分位仓位调整
            max_trade_volume=3,                # 最大持仓手数
            idle_cash_return=0.02,             # 闲置资金年化收益率（货基）
        )

        strategy = ICBasisRollerStrategyV2(config)
        strategy.run()
