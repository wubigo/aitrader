import os
from datetime import date
from pathlib import Path

from tqsdk import TqApi, TqAuth
from utils.backtest_logger import backup_dataframe


current_dir = Path(__file__).resolve().parent

# 从环境变量获取账号密码
token = os.getenv("TQ_ID")
pa = os.getenv("TQ_PASS")

# 创建 API
api = TqApi(auth=TqAuth(token, pa))

# 获取行情
#quote = api.get_quote("SHFE.ni2206")
# quote = api.get_quote("CFFEX.IC0")
# print(quote.last_price, quote.volume)
#
# # ✅ 关键：必须关闭 API，否则一定会出你那个报错
# api.close()

symbol = "CFFEX.IC2606"
# 推荐用 with 自动关闭，
# with TqApi(auth=TqAuth(token, pa)) as api:
    # 正确：中金所 中证500股指期货 主力连续
quote = api.get_quote(symbol)
# quote = api.get_quote("CFFEX.IC主连")
print("最新价：", quote.last_price)
print("成交量：", quote.volume)

csv_file_path = current_dir / "future_expires.csv"

d = api.query_his_cont_quotes(['KQ.m@CFFEX.IC'], n=2705)

d.to_csv(csv_file_path, index=False)




api.close()
