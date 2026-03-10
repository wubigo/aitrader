import pandas as pd
from datetime import timedelta, timezone
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.database import get_database
from vnpy.trader.object import BarData
import logging

utc_8 = timezone(timedelta(hours=8))
database = get_database()

symbol = "000001"
exchange = Exchange.SZSE      # 深交所
csv_file = f"data/{symbol}.csv"

df = pd.read_csv(csv_file)

# 适配 AkShare 列名
df["datetime"] = pd.to_datetime(df["日期"])
df["open"] = df["开盘"]
df["high"] = df["最高"]
df["low"] = df["最低"]
df["close"] = df["收盘"]
df["volume"] = df["成交量"]

bars = []
for row in df.itertuples():
    dt = row.datetime.replace(tzinfo=utc_8)
    print(dt)
    bar = BarData(
        symbol=symbol,
        exchange=exchange,
        datetime=dt,
        interval=Interval.DAILY,
        volume=float(row.volume),
        open_price=float(row.open),
        high_price=float(row.high),
        low_price=float(row.low),
        close_price=float(row.close),
        open_interest=0,
        gateway_name="DB",
    )
    bars.append(bar)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 尝试批量入库，若失败则逐条入库并记录失败条数
try:
    database.save_bar_data(bars)
    logger.info(f"入库完成: {symbol}, 共 {len(bars)} 条")
except Exception:
    logger.exception("批量入库失败，尝试逐条入库")
    success = 0
    failed = 0
    for i, bar in enumerate(bars, 1):
        try:
            # 使用单条列表形式调用以兼容不同实现
            database.save_bar_data([bar])
            success += 1
        except Exception:
            failed += 1
            dt = getattr(bar, "datetime", None)
            logger.exception(f"单条入库失败 index={i}, symbol={symbol}, datetime={dt}")
    logger.info(f"逐条入库完成: 成功 {success} 条, 失败 {failed} 条")

print(f"入库完成: {symbol}, 共 {len(bars)} 条")
