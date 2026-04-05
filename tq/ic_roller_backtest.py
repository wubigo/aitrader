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
sim_account = TqSim(init_balance=INITIAL_ACCOUNT_BALANCE)

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

                            # === 核心判断：期货贴水报警 ===
                            if (ann_basis is not None and
                                    ann_basis > ANNUALIZED_BASIS_THRESHOLD and
                                    expire_rest_days > MIN_DAYS_TO_EXPIRATION_OPEN and
                                    position.pos_long == 0 and
                                    test_time.date() > start_dt and
                                    not has_opened_in_current_main):
                                alert_time = test_time
                                logger.info(f"🚨【贴水报警】合约: {current_underlying} 时间: {alert_time} | "
                                      f"期货收盘: {fut_close:.2f} | "
                                      f"指数收盘: {idx_close:.2f} | "
                                      f"年化贴水: {ann_basis:.2f} ")

                                target_pos_task.set_target_volume(1)
                                has_opened_in_current_main = True  # 标记已执行，本合约周期不再触发
                                logger.info("✅ 已下达【买入 1 手】指令，等待成交...")

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

    else:
        logger.info("未获取到 K 线数据")

finally:
    api.close()



