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

KLINE_LEN = 5000
HIS_DAYS = 1000

start_dt = date(2015, 1, 1)
# end_dt = date(2026, 4, 21)
end_dt = date.today()

api = TqApi(
    backtest=TqBacktest(start_dt=start_dt, end_dt=end_dt),
    auth=TqAuth(token, pa)
)

fut_symbol = "KQ.m@CFFEX.IC"
# kline_df = api.get_kline_serial(["KQ.m@CFFEX.IC", "SSE.000905"], duration_seconds=1800, data_length=KLINE_LEN)
kline_df = api.get_kline_serial([fut_symbol], duration_seconds=86400, data_length=KLINE_LEN)
quote = api.get_quote(fut_symbol)
current_underlying = quote.underlying_symbol

record_list = []

data_file = f"{current_dir}/future_expires.csv"

if os.path.exists(data_file):
    os.rename(data_file, f"{data_file}-{date.today()}")


try:
    while True:
        api.wait_update()
        # if order.status == "FINISHED":
        #     print("模拟交易下单测试成功！")

        if api.is_changing(quote, "underlying_symbol"):
            new_underlying = quote.underlying_symbol
            logger.info(f"时间: {quote.datetime} 【主力切换】{current_underlying or '开始'} → {new_underlying} ")
            current_underlying = new_underlying

        if api.is_changing(kline_df.iloc[-1], "datetime"):
            latest = pd.to_datetime(kline_df.iloc[-1]["datetime"], unit='ns', utc=True).tz_convert('Asia/Shanghai')
            expire_rest_days = quote.underlying_quote.expire_rest_days

            logger.info(f"backtest date:{latest} expire_rest_days:{expire_rest_days} IC0:{current_underlying}")

            # 使用 list.append 收集数据
            record_list.append({
                "datetime": latest,
                "KQ.m@CFFEX.IC": current_underlying,
                "expire_rest_days": expire_rest_days
            })

except BacktestFinished:
    # 回测结束后一次性转 DataFrame 并保存
    if record_list:
        record_df = pd.DataFrame(record_list)
        record_df.to_csv(data_file, index=False, encoding="utf-8-sig")
        logger.info(f"回测结束，成功保存 {len(record_df)} 条记录")
    else:
        logger.warning("未收集到任何数据，请检查 K 线或 Quote 推送")
    logger.info("backtest exit")

except Exception as e:
    logging.exception(f"出错: {e}")
finally:
    api.close()




