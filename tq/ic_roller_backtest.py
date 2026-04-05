import logging
import os
from datetime import date, datetime
import pandas as pd
from tqsdk import TqApi, TqAuth, TqBacktest, BacktestFinished, TargetPosTask, TqSim
from utils.backtest_logger import backup_dataframe

from utils.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def calc_annualized_basis(fut_price, spot_price, days):
    """计算年化贴水率"""
    # 确保价格和天数有效，防止NaN值、None或负天数
    if pd.isna(fut_price) or pd.isna(spot_price) or days <= 0:
        return None
    # 防止除以零
    if spot_price == 0:
        logger.warning("Spot price is zero, cannot calculate annualized basis.")
        return None

    basis_ratio = (spot_price - fut_price) / spot_price
    annualized = basis_ratio * 365 / days * 100
    return round(annualized, 3)



# ================== 配置区域 ==================
futures_symbol = "KQ.m@CFFEX.IC"  # IC 主连合约
index_symbol = "SSE.000905"  # 中证500指数（官方符号）
# --- 常量定义 ---
ONE_DAY_SECONDS = 60 * 60 * 24
KLINE_DATA_LENGTH = 100
INITIAL_ACCOUNT_BALANCE = 1000000
ANNUALIZED_BASIS_THRESHOLD = 8.0  # 年化贴水报警阈值
MIN_DAYS_TO_EXPIRATION_OPEN = 7   # 距离到期天数 > 此值才允许开仓
MAX_DAYS_TO_EXPIRATION_CLOSE = 6  # 距离到期天数 <= 此值触发平仓
PROFIT_TAKING_BASIS_PCT = 0.5   # 止盈比例，例如 0.5 表示当贴水修复了50%时止盈
INDEX_SMA_PERIOD = 20           # 指数SMA周期，用于趋势过滤
DEFAULT_TRADE_VOLUME = 1        # 默认交易手数
ADAPTIVE_THRESHOLD_WINDOW = 60 # 动态阈值窗口（K线数量）
VOLATILITY_WINDOW = 20          # 波动率窗口
TARGET_VOLATILITY = 0.15        # 目标年化波动率，用于调整仓位

duration = ONE_DAY_SECONDS  # K 线周期（秒），60=1分钟线
data_length = KLINE_DATA_LENGTH  # 窗口大小

start_dt = date(2026, 1, 1)
end_dt = date(2026, 3, 31)
# 开始时间转为纳秒时间戳
start_nano = int(pd.Timestamp(start_dt).timestamp() * 1e9)
# ============================================

# 从环境变量获取账号密码
token = os.getenv("TQ_ID")
pa = os.getenv("TQ_PASS")

# 定义模拟账户：初始资金 INITIAL_ACCOUNT_BALANCE
sim_account = TqSim(init_balance=INITIAL_ACCOUNT_BALANCE, account_id='bigo')

# 1. 创建回测 API
api = TqApi(
    backtest=TqBacktest(start_dt=start_dt, end_dt=end_dt),
    account=sim_account,
    auth=TqAuth(token, pa)
)


quote = api.get_quote(futures_symbol)
current_underlying = quote.underlying_symbol
expire = quote.underlying_quote.expire_datetime


# 订阅期货主连 K 线 + 指数 K 线（同周期，确保时间对齐）
# 增加 fill_min_period=0 参数，确保不向前追溯历史数据
futures_klines = api.get_kline_serial(futures_symbol, duration, data_length=data_length, fill_min_period=0)
index_klines = api.get_kline_serial(index_symbol, duration, data_length=data_length, fill_min_period=0)
quote = api.get_quote(futures_symbol)  # 用于监控主力切换

full_klines_data = []  # 用于最终保存所有 K 线的数据字典
last_dt = 0  # 上次已保存的期货 datetime

target_pos_task = TargetPosTask(api, current_underlying)

# 已处理的成交 ID 集合，避免重复打印
processed_trade_ids = set()

# 新增：记录当前主力合约是否已开仓的标记
has_opened_in_current_main = False
entry_ann_basis = None # Track annualized basis at entry for profit-taking

logger.info(f"开始回测：{futures_symbol}（中证500期货主连） vs {index_symbol}（中证500指数）")

try:
    while True:
        api.wait_update()

        # 2. 获取账户所有成交记录
        trades = api.get_trade()
        for trade_id, trade in trades.items():
            # 过滤条件：该合约的成交 且 是新发现的成交记录
            # TqSdk 的 Trade 对象使用 instrument_id (合约代码) 和 exchange_id (交易所代码)
            # 拼接方式通常为 "EXCHANGE.INSTRUMENT"
            trade_symbol = f"{trade.exchange_id}.{trade.instrument_id}"
            if trade_symbol == current_underlying and trade_id not in processed_trade_ids:
                # trade_date_time 是纳秒时间戳
                trade_time = datetime.fromtimestamp(trade.trade_date_time / 1e9)

                logger.info(f"--- 交易成功通知 ---")
                logger.info(f"Trade时间:{trade_time.strftime('%Y-%m-%d %H:%M:%S.%f')}, 价格:{trade.price}, 数量:{trade.volume}, 买卖方向:{trade.direction}")
                processed_trade_ids.add(trade_id)
                # 3. 检查是否已经达到目标持仓（可选）
                pos = api.get_position(current_underlying)
                if pos.pos_long == 1: # Assuming target is 1 long position
                    logger.info("目标持仓已达成，查询结束。")
                    break




        # ================== 监控主力合约切换 ==================
        if api.is_changing(quote, "underlying_symbol"):
            new_underlying = quote.underlying_symbol
            logger.info(f"【主力切换】{current_underlying or '开始'} → {new_underlying}  | 时间: {quote.datetime}")
            current_underlying = new_underlying
            target_pos_task = TargetPosTask(api, current_underlying)
            # 关键：主力切换后，重置开仓标记，允许新合约贴水开仓
            has_opened_in_current_main = False

        # ================== 累积 K 线 + 贴水判断 ==================
        if api.is_changing(futures_klines):

            new_bars = futures_klines[(futures_klines["datetime"] > last_dt) & (futures_klines["datetime"] >= start_nano)]

            if not new_bars.empty:
                for idx, row in new_bars.iterrows():
                    fut_dt = row["datetime"]
                    fut_close = row["close"]

                    # 在指数 K 线中查找完全相同时间的 bar（同周期下时间精确对齐）
                    idx_match = index_klines[index_klines["datetime"] == fut_dt]

                    if not idx_match.empty:
                        idx_close = idx_match.iloc[0]["close"]

                        if idx_close > 0:  # 防止除零
                            discount = (idx_close - fut_close) / idx_close
                            discount_bp = round(discount * 10000, 2)   # 关键：保留2位小数
                            test_time = pd.to_datetime(fut_dt, unit='ns')

                            quote = api.get_quote(futures_symbol)
                            expire_rest_days = quote.underlying_quote.expire_rest_days
                            position = api.get_position(current_underlying)
                            ann_basis = calc_annualized_basis(fut_close, idx_close, expire_rest_days)

                            # --- 趋势过滤 ---
                            index_sma = index_klines["close"].rolling(window=INDEX_SMA_PERIOD).mean().iloc[-1]
                            is_uptrend = idx_close > index_sma

                            # --- 动态阈值计算 ---
                            # 维护最近的年化贴水历史
                            basis_history = [row["ann_basis"] for row in full_klines_data[-ADAPTIVE_THRESHOLD_WINDOW:] if "ann_basis" in row and row["ann_basis"] is not None]
                            if len(basis_history) >= ADAPTIVE_THRESHOLD_WINDOW:
                                dynamic_threshold = pd.Series(basis_history).quantile(0.75) # 使用75%分位数作为动态门槛
                            else:
                                dynamic_threshold = ANNUALIZED_BASIS_THRESHOLD

                            # --- 波动率调整仓位 (简单的风险平价思路) ---
                            # 计算指数最近的年化波动率
                            if len(full_klines_data) >= VOLATILITY_WINDOW:
                                idx_closes = [row["index_close"] for row in full_klines_data[-VOLATILITY_WINDOW:] if row["index_close"] is not None]
                                if len(idx_closes) >= VOLATILITY_WINDOW:
                                    returns = pd.Series(idx_closes).pct_change().dropna()
                                    ann_vol = returns.std() * (242 ** 0.5) # 简单年化，假设242个交易日
                                    # 根据波动率调整仓位：目标波动率 / 当前波动率
                                    vol_adj_volume = max(1, int(DEFAULT_TRADE_VOLUME * (TARGET_VOLATILITY / max(0.01, ann_vol))))
                                else:
                                    vol_adj_volume = DEFAULT_TRADE_VOLUME
                            else:
                                vol_adj_volume = DEFAULT_TRADE_VOLUME

                            # === 核心判断：期货贴水报警 ===
                            if (ann_basis is not None and
                                    ann_basis > dynamic_threshold and # 使用动态阈值
                                    expire_rest_days > MIN_DAYS_TO_EXPIRATION_OPEN and
                                    position.pos_long == 0 and
                                    test_time.date() > start_dt and
                                    is_uptrend and # 仅在上涨趋势或非强下跌趋势中开仓
                                    not has_opened_in_current_main):
                                alert_time = test_time
                                logger.info(f"🚨【贴水报警】合约: {current_underlying} 时间: {alert_time} | "
                                      f"期货收盘: {fut_close:.2f} | "
                                      f"指数收盘: {idx_close:.2f} | "
                                      f"年化贴水: {ann_basis:.2f} (动态阈值: {dynamic_threshold:.2f}) | "
                                      f"指数SMA({INDEX_SMA_PERIOD}): {index_sma:.2f}")

                                target_pos_task.set_target_volume(vol_adj_volume)
                                has_opened_in_current_main = True  # 标记已执行，本合约周期不再触发
                                entry_ann_basis = ann_basis        # 记录开仓时的年化贴水
                                logger.info(f"✅ 已下达【买入 {vol_adj_volume} 手】指令，等待成交...")

                            elif position.pos_long > 0 and entry_ann_basis is not None:
                                # 计算贴水修复比例
                                basis_repair_pct = (entry_ann_basis - ann_basis) / entry_ann_basis
                                if basis_repair_pct >= PROFIT_TAKING_BASIS_PCT:
                                    logger.info(f"💰【止盈平仓】合约: {current_underlying} 达到止盈条件 (修复率: {basis_repair_pct:.2%})，触发平仓。")
                                    target_pos_task.set_target_volume(0)
                                    has_opened_in_current_main = True # 平仓后本合约不再操作
                                    entry_ann_basis = None
                                    continue

                            elif expire_rest_days <= MAX_DAYS_TO_EXPIRATION_CLOSE and position.pos_long > 0:
                                logger.info(
                                    f"⏰【临期平仓】合约: {current_underlying} 距离到期仅剩 {expire_rest_days} 天，触发强制平仓。多头浮动盈亏: {position.float_profit_long}")
                                target_pos_task.set_target_volume(0)
                                # 注意：平仓后可以设置标记，防止同一合约在最后几天又因为贴水被买回来
                                has_opened_in_current_main = True
                                continue  # 跳过本次循环，不再进入下方的买入判断

                            else:
                                logger.info(f"{test_time }-持仓: {position.pos_long}，浮动盈亏: {position.float_profit_long}, 合约：{current_underlying}， 剩余天数: {expire_rest_days}")


                        # 可选：把指数价和贴水也存进 full_klines（方便后续分析）
                        # 收集数据作为字典
                        row_data = row.to_dict()
                        row_data["index_close"] = idx_close
                        row_data["discount_bp"] = discount_bp
                        row_data["ann_basis"] = ann_basis
                        # 获取账户资金情况，TqSdk 中通过 api.get_account() 获取
                        account_info = api.get_account()
                        row_data["balance"] = account_info.balance
                        full_klines_data.append(row_data)
                    else:
                        # 极少数情况下时间未对齐，直接用期货 bar
                        full_klines_data.append(row.to_dict())

                last_dt = futures_klines.iloc[-1]["datetime"]

except BacktestFinished:
    logger.info("\n回测结束，开始保存完整数据...")

    if full_klines_data:
        full_df = pd.DataFrame(full_klines_data)
        full_df["datetime"] = pd.to_datetime(full_df["datetime"], unit="ns")

        # 保存（推荐 parquet）
        csv_file = f"IC_main_vs_CSI500_{duration}s_{start_dt}_{end_dt}.csv"

        backup_dataframe(full_df, csv_file)

        logger.info(f"✅ 保存完成！共 {len(full_df)} 根 K 线")
        logger.info(f"   CSV: {csv_file}")

        # 额外统计贴水报警次数（方便查看）
        if "discount_bp" in full_df.columns:
            alert_count = (full_df["discount_bp"] >= 50).sum()
            logger.info(f"📊 本次回测共触发贴水≥50bp 报警 {alert_count} 次")

        # --- 策略绩效分析 ---
        if "balance" in full_df.columns:
            # 1. 年化收益率 (CAGR)
            start_balance = INITIAL_ACCOUNT_BALANCE
            account_info = api.get_account()
            end_balance = account_info.balance
            days = (end_dt - start_dt).days
            if days > 0:
                cagr = (end_balance / start_balance) ** (365.0 / days) - 1
            else:
                cagr = 0

            # 2. 最大回撤 (MDD)
            full_df["cum_max_balance"] = full_df["balance"].cummax()
            full_df["drawdown"] = (full_df["balance"] - full_df["cum_max_balance"]) / full_df["cum_max_balance"]
            max_drawdown = full_df["drawdown"].min()

            # 3. 夏普比率 (Sharpe Ratio)
            returns = full_df["balance"].pct_change().dropna()
            if returns.std() > 0:
                sharpe = (returns.mean() / returns.std()) * (242 ** 0.5) # 假设242个交易日
            else:
                sharpe = 0

            logger.info(f"📈 【策略绩效评估】")
            logger.info(f"   起始资金: {start_balance:,.2f}")
            logger.info(f"   最终资金: {end_balance:,.2f}")
            logger.info(f"   年化收益率 (CAGR): {cagr:.2%}")
            logger.info(f"   最大回撤 (Max Drawdown): {max_drawdown:.2%}")
            logger.info(f"   夏普比率 (Sharpe Ratio): {sharpe:.2f}")

    else:
        logger.info("未获取到 K 线数据")

finally:
    api.close()



