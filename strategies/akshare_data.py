import akshare as ak
import pandas as pd

symbol = "000001"         # 平安银行
market = "sz"             # sz 深市, sh 沪市
start_date = "20200101"
end_date = "20260301"





df = ak.stock_zh_a_hist(
    symbol=f"{symbol}",
    period="daily",
    start_date=start_date,
    end_date=end_date,
    adjust="qfq"          # 前复权
)

df["日期"] = pd.to_datetime(df["日期"])
df["开盘"] = df["开盘"].astype(float)
df["最高"] = df["最高"].astype(float)
df["最低"] = df["最低"].astype(float)
df["收盘"] = df["收盘"].astype(float)
df["成交量"] = df["成交量"].astype(float)

df = df[["日期", "开盘", "最高", "最低", "收盘", "成交量"]]
df.to_csv(f"data/{symbol}.csv", index=False, encoding="utf-8-sig")
print(df.head())
