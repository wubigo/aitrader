import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tqsdk import TqApi, TqAuth
from utils.backtest_logger import backup_dataframe

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
symbol = api.query_cont_quotes(product_id="IC").pop()

# 推荐用 with 自动关闭，
# with TqApi(auth=TqAuth(token, pa)) as api:
    # 正确：中金所 中证500股指期货 主力连续
quote = api.get_quote(symbol)
# quote = api.get_quote("CFFEX.IC主连")
print("最新价：", quote.last_price)
print("成交量：", quote.volume)

# 最近3天结算价信息
df = api.query_symbol_settlement(symbol, days=3)
print(df)

# 最近 1 天持仓排名信息，以成交量排序
df = api.query_symbol_ranking(symbol, ranking_type="VOLUME")
backup_dataframe(df, "tq-api-持仓排名-成交量排序.csv")

# 最近 3 天持仓排名信息，以多头持仓量排序
df = api.query_symbol_ranking(symbol, ranking_type="LONG", days=1)
backup_dataframe(df, "tq-api-持仓排名-多头持仓量排序.csv")

df = api.query_symbol_ranking(symbol, ranking_type="SHORT", days=1)
backup_dataframe(df, "tq-api-持仓排名-空头持仓量排序.csv")

ls = api.query_quotes(exchange_id="CFFEX", product_id="IC")
ls = api.query_cont_quotes(exchange_id="CFFEX")
print(ls)
# IC 品种主连合约对应的标的合约
ls = api.query_cont_quotes(product_id="IC")
df_symbol_info = api.query_symbol_info(ls.pop())
backup_dataframe(df_symbol_info, "IC-主连合约信息-query_symbol_info.csv")
ts = df_symbol_info["expire_datetime"]
print(f"expire_datetime:{datetime.fromtimestamp(ts.iloc[0])}")


api.close()

