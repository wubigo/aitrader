import datetime
import os
import sys
from datetime import date
import logging
import pandas as pd
from tqsdk import TqApi, TqBacktest, TqAuth, BacktestFinished

# from utils.logging_config import setup_logging
# setup_logging()
logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stdout
    )


# 从环境变量获取账号密码
token = os.getenv("TQ_ID")
pa = os.getenv("TQ_PASS")


KLINE_LEN = 10000
HIS_DAYS = 1000

start_dt = date(2018, 1, 5)
# end_dt = date(2026, 2, 1)
end_dt = date.today()
# 1. 创建回测 API
api = TqApi(
    backtest=TqBacktest(start_dt=start_dt, end_dt=end_dt),
    auth=TqAuth(token, pa)
)


kline_df = api.get_kline_serial(["KQ.m@CFFEX.IC", "SSE.000905"], duration_seconds=1800, data_length=KLINE_LEN)

# print(kline_df.iloc[-1])                         # 2018/01/01 09:00:00.000, O=35000, H=35000, L=35000, C=35000 小时线刚创建

# print(f"模拟订单已提交，订单ID: {order.order_id}")

df = kline_df.copy()

df["datetime"] = pd.to_datetime(df["datetime"], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')

# df["datetime"] = df["datetime"].dt.tz_localize(None)
# df["datetime"] = pd.to_datetime(df["datetime"], unit='ns')
# print(df.iloc[-1]["datetime"])

# 5. 循环检查订单状态
i = 0
n = 0
e = 0


df.to_csv(f"change-tq-{i}.csv")
logging.info(f"change-tq-{i}.csv")
try:
    while True:
        api.wait_update()
        # if order.status == "FINISHED":
        #     print("模拟交易下单测试成功！")

        if api.is_changing(kline_df.iloc[-1], "close"):

            logging.info(f"change-close-{n}.csv")
            df = kline_df.copy()
            df["datetime"] = pd.to_datetime(df["datetime"], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')

            # 5. 循环检查订单状态

            df.to_csv(f"change-close-{i}.csv")

            # print(kline_df.iloc[-2])  # 2018/01/01 09:00:00.000, O=35000, H=35400, L=34700, C=34900 9点这根小时线完成了
            # print(kline_df.iloc[-1])
            n = n + 1
        elif api.is_changing(kline_df.iloc[-1], "datetime"):
            logging.info(f"change-datetime-{i}.csv")
            # df = kline_df.copy()
            # df["datetime"] = pd.to_datetime(df["datetime"], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')
            # # print(f"change-close {n}")
            # df.to_csv(f"change-close-{n}.csv")
            n = i + 1
        else:
            logging.info(f"change-else-{e}.csv")
            # df = kline_df.copy()
            # df["datetime"] = pd.to_datetime(df["datetime"], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')
            # df.to_csv(f"change-else-{e}.csv")
            print(f"else loop {e}")

            e = e + 1
except BacktestFinished:
    logging.info("backtest exit")
except Exception as e:
    print(f"出错: {e}")
finally:
    logging.info(f"i={i}, n={n}, e={e}")

api.close()

