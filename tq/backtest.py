import os
from datetime import date
from datetime import datetime
import pandas as pd
from tqsdk import TqApi, TqAuth, TqBacktest, TargetPosTask
from utils.backtest_logger import backup_dataframe

# 从环境变量获取账号密码
token = os.getenv("TQ_ID")
pa = os.getenv("TQ_PASS")

'''
如果当前价格大于5分钟K线的MA15则开多仓
如果小于则平仓
回测从 2018-05-01 到 2018-10-01
'''
# 在创建 api 实例时传入 TqBacktest 就会进入回测模式
api = TqApi(debug="tq-debug.json", backtest=TqBacktest(start_dt=date(2023, 1, 4), end_dt=date(2024, 12, 31)), auth=TqAuth(token, pa))
symbol = api.query_cont_quotes(product_id="IC").pop()
quote = api.get_quote(symbol)

# 获得 IC主连 日K线的引用
klines = api.get_kline_serial(symbol, 24*60 * 60, data_length=100)


first = datetime.fromtimestamp(klines["datetime"].iloc[0] / 1e9)
last = datetime.fromtimestamp(klines["datetime"].iloc[-1] / 1e9)

print(f"{first}   -- {last}")

# tick = api.get_tick_serial(symbol, data_length= 200)

# 创建 m1901 的目标持仓 task，该 task 负责调整 m1901 的仓位到指定的目标仓位
# target_pos = TargetPosTask(api, symbol)

while True:
    api.wait_update()
    if api.is_changing(klines.iloc[-1], "datetime"):
        # print(klines.close.iloc[-5:])
        # 将 datetime 列从 float (纳秒时间戳) 转换为 pandas Timestamp
        if pd.api.types.is_numeric_dtype(klines['datetime']):
            klines['datetime'] = pd.to_datetime(klines['datetime'] / 1e9)
        else:
            klines['datetime'] = pd.to_datetime(klines['datetime'])
        backup_dataframe(klines, "tq-backtest-log.csv", mode='w')
        # print(klines.iloc[-1])
        d = klines["datetime"].iloc[-1]
        print("新K线", d)
        # print("新K线", datetime.fromtimestamp(klines.tail(1)["datetime"]))


api.close()


