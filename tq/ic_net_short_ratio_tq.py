import os
import logging
import pandas as pd
from tqsdk import TqApi, TqAuth
from datetime import datetime, date
import sys

from utils.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# 尝试导入 rich 用于美化输出
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich import box
    RICH_OK = True
    console = Console()
except ImportError:
    RICH_OK = False

def calculate_net_short_ratio(long_df, short_df):
    """
    计算净空比
    净空比 = (总空头持仓 - 总多头持仓) / (总空头持仓 + 总多头持仓) * 100
    """
    # 按日期分组求和
    long_sum = long_df.groupby("datetime")["long_oi"].sum()
    short_sum = short_df.groupby("datetime")["short_oi"].sum()

    # 合并数据
    df = pd.DataFrame({"long": long_sum, "short": short_sum}).fillna(0)
    df["net_short"] = df["short"] - df["long"]
    df["total_oi"] = df["short"] + df["long"]
    df["ratio"] = (df["net_short"] / df["total_oi"] * 100).round(2)

    return df.sort_index(ascending=True)

def interpret_signal(ratio):
    if ratio < -20:
        return "深度空头", "贴水大概率扩大"
    elif ratio < -10:
        return "正常对冲", "量化对冲常态"
    elif ratio < 0:
        return "空头偏弱", "贴水可能收敛"
    else:
        return "多头占优", "升水风险"

def print_report(df, symbol):
    if RICH_OK:
        console.print(Panel(f"[bold blue]{symbol} 历史净空比趋势分析 (TqSDK)[/bold blue]", expand=False))
        table = Table(box=box.SIMPLE, show_header=True, header_style="dim")
        table.add_column("日期", width=12)
        table.add_column("总多头", justify="right")
        table.add_column("总空头", justify="right")
        table.add_column("净空头", justify="right")
        table.add_column("净空比", justify="right")
        table.add_column("趋势", justify="center")
        table.add_column("信号", width=10)

        prev_ratio = None
        for date, row in df.iterrows():
            ratio = row["ratio"]
            level, _ = interpret_signal(ratio)

            # 颜色逻辑
            color = "red" if ratio < -20 else ("yellow" if ratio < -10 else "green")

            # 趋势箭头
            trend = "—"
            if prev_ratio is not None:
                if ratio > prev_ratio: trend = "[green]↑[/green]"
                elif ratio < prev_ratio: trend = "[red]↓[/red]"

            table.add_row(
                str(date),
                f"{int(row['long']):,}",
                f"{int(row['short']):,}",
                f"{int(row['net_short']):+,}",
                f"[{color}]{ratio:+.2f}%[/{color}]",
                trend,
                f"[{color}]{level}[/{color}]"
            )
            prev_ratio = ratio

        console.print(table)
    else:
        print(f"\n{symbol} 历史净空比趋势分析 (TqSDK)")
        print("-" * 70)
        print(f"{'日期':<12} {'总多头':>10} {'总空头':>10} {'净空头':>10} {'净空比':>10} {'信号'}")
        print("-" * 70)
        for date, row in df.iterrows():
            level, _ = interpret_signal(row["ratio"])
            print(f"{date:<12} {int(row['long']):>10,} {int(row['short']):>10,} {int(row['net_short']):>+10,} {row['ratio']:>+9.2f}% {level}")

def save_report_to_csv(result_dict, file_path="ic_report_history.csv"):
    """
    保存结果到CSV：若日期存在则更新，不存在则追加。
    """
    new_df = pd.DataFrame([result_dict])

    if Path(file_path).exists():
        old_df = pd.read_csv(file_path)
        # 确保 date 是字符串格式以便比较
        old_df['date'] = old_df['date'].astype(str)
        new_df['date'] = new_df['date'].astype(str)

        # 检查日期是否已存在
        if result_dict['date'] in old_df['date'].values:
            # 删除旧记录并合并新记录
            old_df = old_df[old_df['date'] != result_dict['date']]
            combined_df = pd.concat([old_df, new_df], ignore_index=True)
        else:
            # 直接追加
            combined_df = pd.concat([old_df, new_df], ignore_index=True)
    else:
        combined_df = new_df

    # 按日期排序后保存
    combined_df.sort_values("date", inplace=True)
    combined_df.to_csv(file_path, index=False, encoding='utf-8-sig')
    print(f"已更新数据至: {file_path}")

def main():
    # 环境配置
    token = os.getenv("TQ_ID")
    pa = os.getenv("TQ_PASS")
    if not token or not pa:
        print("错误: 请设置环境变量 TQ_ID 和 TQ_PASS")
        return

    symbol = "KQ.m@CFFEX.IC"
    days = 2000  # 默认查询天数

    api = TqApi(auth=TqAuth(token, pa))

    try:
        # long_ranking_df = api.query_symbol_ranking('CFFEX.IC2101', ranking_type="LONG", start_dt=date(2021, 1, 4))
        # print(long_ranking_df)
        quote = api.get_quote(symbol)
        symbol_list = [symbol]
        conts = api.query_his_cont_quotes(symbol=symbol_list, n=days)
        # conts.to_csv("date-ic-all.csv")
        df_tq = conts[conts['date'] > '2020-12-31']


        for start, underlying_symbol in zip(df_tq['date'], df_tq[symbol]):

            print(f"正在查询 {underlying_symbol} 在 {start} 排名数据...")
            dt = pd.to_datetime(start, unit='ns').date()

            # 查询多头排名
            long_ranking_df = api.query_symbol_ranking(underlying_symbol, ranking_type="LONG", start_dt=dt)

            # long_ranking_df.to_csv("tq-api-持仓排名-多头持仓量排序.csv")
            # # 查询空头排名
            short_ranking_df = api.query_symbol_ranking(underlying_symbol, ranking_type="SHORT", start_dt=dt)
            # short_ranking_df.to_csv("tq-api-持仓排名-空头持仓量排序.csv")
            if long_ranking_df.empty or short_ranking_df.empty:
                print("未获取到足够的数据，请确认合约代码或日期范围。")
                return

            # 计算
            result_df = calculate_net_short_ratio(long_ranking_df, short_ranking_df)
            # 补充结果维度
            result_df['date'] = dt
            result_df['symbol'] = underlying_symbol
            level, desc = interpret_signal(result_df["net_short_ratio"])
            result_df['signal_level'] = level

            # 3. 打印并保存
            print_report(result_df, trade_info, dt, underlying_symbol)
            save_report_to_csv(result, file_path=report_file)

            # 输出
            print_report(result_df, symbol)


        api.close()



    except Exception as e:
        logger.exception(f"运行出错: {e}")
        if 'api' in locals(): api.close()

if __name__ == "__main__":
    main()
