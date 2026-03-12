import tushare as ts
import pandas as pd


# df = pro.daily(ts_code='000001.SZ', start_date='20180701', end_date='20180718')

# 1. 设置你的 Tushare Token
# 将 'your_token_here' 替换为你在 Tushare 官网获取的真实 Token
token = '1f832aa50ab6eda9166cf7ead1191121540c1eba28c7fb978'
TUSHARE_TOKEN = token
STOCK_CODE = '600519.SH'  # 股票代码
START_DATE = '20200101'  # 回测开始日期
END_DATE = '20200201'  # 回测结束日期
# ts.set_token(token)
#
# # 2. 初始化 Pro API
# pro = ts.pro_api()

# 3. 调用日线数据接口 (以贵州茅台为例)
# ts_code: 股票代码, start_date: 开始日期, end_date: 结束日期
# fields 参数可选，用于指定只获取需要的字段，节省流量
# df = pro.daily(
#     ts_code='600519.SH',
#     start_date='20240101',
#     end_date='20240201',
#     fields='trade_date,open,high,low,close,vol,amount'
# )
#
#
#
# # 4. 将数据保存为 CSV 文件
# # index=False 表示不保存行索引 (0, 1, 2...)
# # 能更好地支持中文且在 Windows Excel 中打开不乱码
# encoding='utf-8-sig'
# filename = '600519_SH_2024.csv'
# df.to_csv(filename, index=False, encoding='utf-8-sig')
#
# print(f"数据已成功保存为 {filename}")


def get_data_from_tushare():
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()

    # 获取复权数据 (前复权)
    df = pro.daily(ts_code=STOCK_CODE, start_date=START_DATE, end_date=END_DATE, adj='qfq')

    # 数据清洗与格式转换 (关键步骤)
    df = df.sort_values('trade_date')  # 按时间升序排列
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df.set_index('trade_date', inplace=True)

    # 重命名列名以匹配 backtrader 要求
    df.rename(columns={'vol': 'volume'}, inplace=True)

    # 选择核心列
    df = df[['open', 'high', 'low', 'close', 'volume']]

    # 处理缺失值
    df.dropna(inplace=True)

    return df


df = get_data_from_tushare()

encoding = 'utf-8-sig'
filename = '600519_SH_2024.csv'
df.to_csv(filename, index=False, encoding='utf-8-sig')

