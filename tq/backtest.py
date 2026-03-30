import os
from datetime import date
import pandas as pd
from tqsdk import TqApi, TqAuth, TqBacktest, BacktestFinished
from utils.backtest_logger import backup_dataframe


# ================== 配置区域 ==================
symbol = "KQ.m@CFFEX.IC"  # IC 主连合约（推荐写法）
duration = 24*60*60  # 日K线
data_length = 20  # 窗口大小，建议 1000~5000，根据内存调整

start_dt = date(2023, 1, 1)  # 回测开始日期（可跨多个合约到期）
end_dt = date(2023, 3, 30)  # 回测结束日期
# ============================================


# 从环境变量获取账号密码
token = os.getenv("TQ_ID")
pa = os.getenv("TQ_PASS")

# 1. 创建回测 API
api = TqApi(
    backtest=TqBacktest(start_dt=start_dt,end_dt=end_dt),
    auth=TqAuth(token, pa)
)

# 订阅主连 K 线 和 Quote（用于监控主力切换）
klines = api.get_kline_serial(symbol, duration, data_length=data_length)
quote = api.get_quote(symbol)  # 用于获取 underlying_symbol（当前实际主力合约）

full_klines = []  # 累积所有新增 K 线片段
last_dt = 0  # 上次已保存的 datetime（纳秒时间戳）
current_underlying = ""  # 当前主力合约代码

print(f"开始回测主连合约: {symbol}，周期: {duration}秒")

try:
    while True:
        api.wait_update()

        # ================== 监控主力合约切换 ==================
        if api.is_changing(quote, "underlying_symbol"):
            new_underlying = quote.underlying_symbol
            print(f"【主力切换】{current_underlying or '开始'} → {new_underlying}  | 时间: {quote.datetime}")
            current_underlying = new_underlying

        # ================== 累积 K 线（按时间顺序去重） ==================
        if api.is_changing(klines):
            # 只取比上次更新的 K 线，避免重复
            new_bars = klines[klines["datetime"] > last_dt]

            if not new_bars.empty:
                full_klines.append(new_bars.copy())
                last_dt = klines.iloc[-1]["datetime"]

                # 可选：打印进度
                latest_time = pd.to_datetime(last_dt, unit='ns')
                print(f"新增 {len(new_bars)} 根 K 线，最新时间: {latest_time}")

except BacktestFinished:
    print("\n回测自然结束，开始保存完整 K 线数据...")

    if full_klines:
        # 合并成一个完整的 DataFrame（自动按时间升序）
        full_df = pd.concat(full_klines, ignore_index=True)
        full_df["datetime"] = pd.to_datetime(full_df["datetime"], unit="ns")

        # 保存文件（建议用 parquet 格式，体积更小、读取更快）
        filename = f"IC主连_回测_{duration}s_{start_dt}_{end_dt}.csv"

        backup_dataframe(full_df, filename)

        print(f"✅ 保存完成！共 {len(full_df)} 根 K 线 →文件: {filename}")

        print(f"   时间范围: {full_df['datetime'].iloc[0]} ~ {full_df['datetime'].iloc[-1]}")
    else:
        print("未获取到任何 K 线数据")

finally:
    api.close()