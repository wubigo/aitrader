import datetime
import os
import sys
from datetime import date
import logging
from pathlib import Path

import pandas as pd
from tqsdk import TqApi, TqBacktest, TqAuth, BacktestFinished

from utils.logging_config import setup_logging

setup_logging()

logger = logging.getLogger(__name__)
current_dir = Path(__file__).resolve().parent

# 从环境变量获取账号密码
token = os.getenv("TQ_ID")
pa = os.getenv("TQ_PASS")

# 默认全局 KLINE_LEN（如果 CSV 不存在时的保底值）
KLINE_LEN = 5000
csv_file_path = current_dir / "future_expires.csv"

# ==================== 1. 动态读取 CSV 并重置 start_dt, end_dt 和 KLINE_LEN ====================
# 默认初始回测起点（如果 CSV 不存在）
start_dt = date(2015, 1, 1)
end_dt = date.today()

if csv_file_path.exists():
    try:
        # 读取已有的 CSV 数据
        existing_df = pd.read_csv(csv_file_path)
        if not existing_df.empty and "datetime" in existing_df.columns:
            # 获取最后一行的时间
            last_datetime_str = existing_df["datetime"].iloc[-1]
            # 提取日期部分 (例如 "2026-03-16 00:00:00+08:00" -> "2026-03-16")
            last_date_str = last_datetime_str.split(" ")[0]
            last_date = datetime.datetime.strptime(last_date_str, "%Y-%m-%d").date()

            # 增量更新的起点：从已有数据的最后一天开始
            start_dt = last_date
            logger.info(f"检测到历史数据，重置回测起点 start_dt 为: {start_dt}")

            # 【新增条件】计算 start_dt 和 end_dt 之间间隔的天数并重置 KLINE_LEN
            delta_days = (end_dt - start_dt).days
            # 避免天数为 0 或负数导致 TqSdk 报错，至少保持 10 条（或根据策略需要给个安全垫 +5 天）
            KLINE_LEN = max(delta_days + 5, 10)
            logger.info(f"检测到历史 CSV，重置 KLINE_LEN 为时间间隔天数: {KLINE_LEN} (实际间隔 {delta_days} 天)")
    except Exception as e:
        logger.error(f"读取历史 CSV 文件失败，将使用默认参数。错误: {e}")

if start_dt >= end_dt:
    logger.info("数据已经是最新，无需更新。")
    sys.exit(0)

# ==================== 2. 用 TqSdk 增量回测这段时间的数据 ====================
# 注意：TqApi 的初始化移到了计算好 KLINE_LEN 之后
api = TqApi(
    backtest=TqBacktest(start_dt=start_dt, end_dt=end_dt),
    auth=TqAuth(token, pa)
)

fut_symbol = "KQ.m@CFFEX.IC"
# 使用动态调整后的 KLINE_LEN
kline_df = api.get_kline_serial([fut_symbol], duration_seconds=86400, data_length=KLINE_LEN)
quote = api.get_quote(fut_symbol)

current_underlying = None
record_list = []

try:
    while True:
        api.wait_update()

        if api.is_changing(quote, "underlying_symbol"):
            new_underlying = quote.underlying_symbol
            logger.info(f"时间: {quote.datetime} 【主力切换】{current_underlying or '开始'} → {new_underlying} ")
            current_underlying = new_underlying

        if api.is_changing(kline_df.iloc[-1], "datetime"):
            latest = pd.to_datetime(kline_df.iloc[-1]["datetime"], unit='ns', utc=True).tz_convert('Asia/Shanghai')
            expire_rest_days = quote.underlying_quote.expire_rest_days

            logger.info(f"回测进行中 date:{latest} expire_rest_days:{expire_rest_days} IC0:{current_underlying}")

            record_list.append({
                "datetime": str(latest),  # 统一转为字符串，方便后续与 CSV 比对和保存
                "KQ.m@CFFEX.IC": current_underlying,
                "expire_rest_days": expire_rest_days
            })

except BacktestFinished:
    # ==================== 3. 将新数据追加到旧 CSV 文件中 ====================
    if record_list:
        new_df = pd.DataFrame(record_list)

        if csv_file_path.exists():
            # 读取历史数据，并合并新数据
            old_df = pd.read_csv(csv_file_path)
            # 合并
            combined_df = pd.concat([old_df, new_df], ignore_index=True)
            # 根据时间戳去重，保留最新更新（例如重叠的最后一天）
            combined_df.drop_duplicates(subset=["datetime"], keep="last", inplace=True)
            # 重新写回 CSV
            combined_df.to_csv(csv_file_path, index=False)
            logger.info(f"增量数据已成功追加并去重，保存至: {csv_file_path}")
        else:
            # 如果文件不存在直接保存
            new_df.to_csv(csv_file_path, index=False)
            logger.info(f"全新生成 CSV 文件并保存至: {csv_file_path}")
    else:
        logger.info("未回测到新的有效记录。")

    # 关闭 API 释放资源
    api.close()