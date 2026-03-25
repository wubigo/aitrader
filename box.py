import pandas as pd

# 示例
data = {'姓名': ['A', 'B', 'C', 'D', 'E', 'F'],
        '分数': [80, 95, 70, 90, 85, 100]}
df = pd.DataFrame(data)

top_5_students = df.nlargest(5, '分数')
print(top_5_students)

print(df['姓名'])

import akshare as ak

# df = ak.stock_board_industry_index_ths(symbol="半导体", start_date="20260101", end_date="20260108")
# print(df.columns.tolist())
# print(df)
#
#
# df = ak.index_analysis_daily_sw(symbol="二级行业")
# print(df.head(100))
# index_zh_a_hist_df = ak.index_zh_a_hist(symbol="000016", period="daily", start_date="19700101", end_date="22220101")
# print(index_zh_a_hist_df)
# STOCK_CODE = "sh000905"
# df = ak.stock_zh_index_daily("sh000905")
# encoding = 'utf-8-sig'
# filename = f"data/index-{STOCK_CODE}.csv"
# df.to_csv(filename, index=False, encoding=encoding)

# 主力连续合约品种一览表
df = ak.futures_display_main_sina()
from utils.backtest_logger import backup_dataframe
backup_dataframe(df, "主力连续合约品种一览表-sina-2026.csv")
