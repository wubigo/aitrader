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



# 从环境变量获取账号密码
token = os.getenv("TQ_ID")
pa = os.getenv("TQ_PASS")

KLINE_LEN = 10000
# 90分钟-K线
DURATION_MINUTES = (60+30+30) * 60
DURATION_MINUTES = 60*60*24
HIS_DAYS = 1000

current_dir = Path(__file__).resolve().parent

data_file = f"{current_dir}/IC0-日-K线.csv"

if os.path.exists(data_file):
    os.rename(data_file, f"{data_file}-{date.today()}")


start_dt = date(2015, 4, 16)
# end_dt = date(2026, 4, 21)
end_dt = date.today()
# 1. 创建回测 API
api = TqApi(
    auth=TqAuth(token, pa)
)



try:
    # kline_df = api.get_kline_serial(["KQ.m@CFFEX.IC", "SSE.000905"], duration_seconds=1800, data_length=KLINE_LEN)
    kline_df = api.get_kline_serial(["KQ.m@CFFEX.IC", "SSE.000905"], duration_seconds=DURATION_MINUTES, data_length=KLINE_LEN)
    df = kline_df
    df["datetime"] = pd.to_datetime(df["datetime"], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')
    df.to_csv(data_file, index=False)

except Exception as e:
    logger.info(f"出错: {e}")
finally:
    logger.info(f"end")
    api.close()




