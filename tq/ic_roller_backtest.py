import os
from datetime import date
import pandas as pd
from tqsdk import TqApi, TqAuth, TqBacktest, BacktestFinished, TargetPosTask
from utils.backtest_logger import backup_dataframe

# ================== 配置区域 ==================
futures_symbol = "KQ.m@CFFEX.IC"  # IC 主连合约
index_symbol = "SSE.000905"  # 中证500指数（官方符号）
duration = 60*60*24  # K 线周期（秒），60=1分钟线
data_length = 20  # 窗口大小

start_dt = date(2026, 1, 1)
end_dt = date(2026, 3, 31)
# ============================================

# 从环境变量获取账号密码
token = os.getenv("TQ_ID")
pa = os.getenv("TQ_PASS")

# 1. 创建回测 API
api = TqApi(
    backtest=TqBacktest(start_dt=start_dt, end_dt=end_dt),
    auth=TqAuth(token, pa)
)


quote = api.get_quote(futures_symbol)
current_underlying = quote.underlying_symbol
expire = quote.underlying_quote.expire_datetime

# 订阅期货主连 K 线 + 指数 K 线（同周期，确保时间对齐）
futures_klines = api.get_kline_serial(futures_symbol, duration, data_length=data_length)
index_klines = api.get_kline_serial(index_symbol, duration, data_length=data_length)
quote = api.get_quote(futures_symbol)  # 用于监控主力切换

full_klines = []  # 用于最终保存所有 K 线
last_dt = 0  # 上次已保存的期货 datetime

target_pos_task = TargetPosTask(api, current_underlying)

print(f"开始回测：{futures_symbol}（中证500期货主连） vs {index_symbol}（中证500指数）")

try:
    while True:
        api.wait_update()

        # ================== 监控主力合约切换 ==================
        if api.is_changing(quote, "underlying_symbol"):
            new_underlying = quote.underlying_symbol
            print(f"【主力切换】{current_underlying or '开始'} → {new_underlying}  | 时间: {quote.datetime}")
            current_underlying = new_underlying
            target_pos_task = TargetPosTask(api, current_underlying)

        # ================== 累积 K 线 + 贴水判断 ==================
        if api.is_changing(futures_klines):
            new_bars = futures_klines[futures_klines["datetime"] > last_dt]

            if not new_bars.empty:
                for idx, row in new_bars.iterrows():
                    fut_dt = row["datetime"]
                    fut_close = row["close"]

                    # 在指数 K 线中查找完全相同时间的 bar（同周期下时间精确对齐）
                    idx_match = index_klines[index_klines["datetime"] == fut_dt]

                    if not idx_match.empty:
                        idx_close = idx_match.iloc[0]["close"]

                        if idx_close > 0:  # 防止除零
                            discount = (idx_close - fut_close) / idx_close
                            discount_bp = round(discount * 10000, 2)   # 关键：保留2位小数

                            # === 核心判断：期货贴水 ≥ 50bp 就报警 ===
                            if discount_bp >= 50:
                                alert_time = pd.to_datetime(fut_dt, unit='ns')
                                print(f"🚨【贴水报警】时间: {alert_time} | "
                                      f"期货收盘: {fut_close:.2f} | "
                                      f"指数收盘: {idx_close:.2f} | "
                                      f"贴水: {discount_bp:.2f} bp（≥50bp）")
                                position = api.get_position(current_underlying)
                                print(f"合约: {current_underlying}")
                                pos_long = position.pos_long
                                if pos_long > 0:
                                    print(f"多头持仓一手数量: {position.pos_long}")
                                    print(f"空头持仓一手数量: {position.pos_short}")
                                    print(f"多头浮动盈亏: {position.float_profit_long}")
                                    print(f"空头浮动盈亏: {position.float_profit_short}")
                                else:
                                    target_pos_task.set_target_volume(1)
                                    print("✅ 已下达【买入 1 手】指令，等待成交...")

                        # 可选：把指数价和贴水也存进 full_klines（方便后续分析）
                        row = row.copy()
                        row["index_close"] = idx_close if not idx_match.empty else None
                        row["discount_bp"] = discount_bp if not idx_match.empty else None
                        full_klines.append(row.to_frame().T)  # 每条独立 append
                    else:
                        # 极少数情况下时间未对齐，直接用期货 bar
                        full_klines.append(row.to_frame().T)

                last_dt = futures_klines.iloc[-1]["datetime"]

except BacktestFinished:
    print("\n回测结束，开始保存完整数据...")

    if full_klines:
        full_df = pd.concat(full_klines, ignore_index=True)
        full_df["datetime"] = pd.to_datetime(full_df["datetime"], unit="ns")

        # 保存（推荐 parquet）
        csv_file = f"IC_main_vs_CSI500_{duration}s_{start_dt}_{end_dt}.csv"

        backup_dataframe(full_df, csv_file)

        print(f"✅ 保存完成！共 {len(full_df)} 根 K 线")
        print(f"   CSV: {csv_file}")

        # 额外统计贴水报警次数（方便查看）
        if "discount_bp" in full_df.columns:
            alert_count = (full_df["discount_bp"] >= 50).sum()
            print(f"📊 本次回测共触发贴水≥50bp 报警 {alert_count} 次")

    else:
        print("未获取到 K 线数据")

finally:
    api.close()