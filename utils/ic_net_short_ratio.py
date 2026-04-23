"""
IC主力合约净空比计算工具
======================
数据来源：中金所每日持仓龙虎榜（手动导入 或 akshare自动获取）
核心指标：净空比 = (总空头持仓 - 总多头持仓) / 总持仓量

依赖安装：pip install akshare pandas rich
"""
import logging
import sys
from datetime import datetime, timedelta
import pandas as pd
from pathlib import Path

try:
    import akshare as ak
    AKSHARE_OK = True
except ImportError:
    AKSHARE_OK = False

current_dir = Path(__file__).resolve().parent


try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich import box
    RICH_OK = True
    console = Console()
except ImportError:
    RICH_OK = False


from utils.logging_config import setup_logging

# --- Setup Logging ---
setup_logging()
logger = logging.getLogger(__name__)


# ─── 核心计算函数 ──────────────────────────────────────────────

def calc_net_short_ratio(df: pd.DataFrame) -> dict:
    """
    计算净空比及相关指标。

    参数 df 需要包含以下列（中金所龙虎榜标准格式）：
        long_vol  : 多头持仓量
        short_vol : 空头持仓量

    返回 dict：
        total_long       总多头持仓
        total_short      总空头持仓
        net_short        净空头（空-多）
        total_oi         总持仓量（空+多）
        net_short_ratio  净空比（%）
        concentration_top5_short   前5空头占总空头比
        concentration_top5_long    前5多头占总多头比
    """
    if df.empty:
        raise ValueError("数据为空，请检查输入")

    required = {"long_open_interest", "short_open_interest"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"缺少必要列：{missing}，当前列：{list(df.columns)}")

    df = df.copy()
    df["long_vol"] = pd.to_numeric(df["long_open_interest"], errors="coerce").fillna(0)
    df["short_vol"] = pd.to_numeric(df["short_open_interest"], errors="coerce").fillna(0)

    total_long = df["long_vol"][:-1].sum()
    total_short = df["short_vol"][:-1].sum()
    total_oi = total_long + total_short
    net_short = total_short - total_long

    net_short_ratio = (net_short / total_oi * 100) if total_oi > 0 else 0.0

    # 前5席位集中度（按各自方向排序取前5）
    top5_short = df.nlargest(5, "short_vol")["short_vol"].sum()
    top5_long = df.nlargest(5, "long_vol")["long_vol"].sum()
    conc_short = (top5_short / total_short * 100) if total_short > 0 else 0.0
    conc_long = (top5_long / total_long * 100) if total_long > 0 else 0.0

    return {
        "total_long": int(total_long),
        "total_short": int(total_short),
        "net_short": int(net_short),
        "total_oi": int(total_oi),
        "net_short_ratio": round(net_short_ratio, 2),
        "concentration_top5_short": round(conc_short, 2),
        "concentration_top5_long": round(conc_long, 2),
    }


def interpret_signal(net_short_ratio: float) -> tuple:
    """
    根据净空比给出定性判断。

    返回 (等级, 说明)
    经验阈值（可根据历史数据自行校准）：
        < -20%    : 深度空头压力，贴水大概率扩大
        -20%~-10% : 正常对冲需求范围
        -10%~0%   : 空头力量偏弱，贴水可能收敛
        >= 0%     : 多头占优，升水风险
    """
    if net_short_ratio < -20:
        return "深度空头", "贴水大概率持续扩大，谨慎持有纯多头"
    elif net_short_ratio < -10:
        return "正常对冲区间", "贴水处于量化对冲常态范围"
    elif net_short_ratio < 0:
        return "空头力量偏弱", "贴水可能趋于收敛，关注是否持续"
    else:
        return "多头占优", "市场升水风险，空头有平仓回补迹象"


# ─── akshare 数据获取 ──────────────────────────────────────────

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """将 akshare 返回的 DataFrame 标准化为含 member/long_vol/short_vol 的格式"""
    col_map = {}
    for col in df.columns:
        col_lower = col.lower()
        # 优先匹配具体的量（持仓量）
        if ("open_interest" in col_lower and "long" in col_lower) or "多头持仓" in col:
            col_map[col] = "long_vol"
        elif ("open_interest" in col_lower and "short" in col_lower) or "空头持仓" in col:
            col_map[col] = "short_vol"
        # 匹配席位/会员名称
        elif "party_name" in col_lower or "会员" in col or "席位" in col or "member" in col_lower:
            # 如果已经映射了 member 且当前列包含 party_name，优先使用 party_name
            if "member" not in col_map or "party_name" in col_lower:
                col_map[col] = "member"

    df = df.rename(columns=col_map)

    # 移除合计行 (通常 rank 为 999 或为空)
    if "rank" in df.columns:
        df = df[df["rank"].astype(str) != "999"]

    # 若自动识别失败，按列位置映射（中金所格式：会员, 多头持仓, 多头增减, 空头持仓, 空头增减）
    if "long_vol" not in df.columns or "short_vol" not in df.columns:
        cols = list(df.columns)
        if len(cols) >= 4:
            rename_by_pos = {cols[0]: "member", cols[1]: "long_vol", cols[3]: "short_vol"}
            df = df.rename(columns=rename_by_pos)
        else:
            raise ValueError(f"无法识别列结构，原始列：{list(df.columns)}")

    keep = [c for c in ["member", "long_vol", "short_vol"] if c in df.columns]
    return df[keep].copy()


def fetch_cffex_positions(symbol: str = ["IC"], trade_date: str = None) -> pd.DataFrame:
    """
    通过 akshare 获取中金所持仓龙虎榜数据。

    参数：
        symbol     : 合约品种，如 "IC"（中证500）、"IF"（沪深300）、"IM"（中证1000）
        trade_date : 交易日期，格式 "YYYYMMDD"，默认取最近有效交易日

    返回标准化 DataFrame（含 member、long_vol、short_vol 列）
    """
    if trade_date is None:
        trade_date = datetime.today().strftime("%Y%m%d")

    symbol_list = [symbol]

    try:
        raw = ak.get_cffex_rank_table(date=trade_date, vars_list=symbol_list)
        if not raw:
            logger.info(f"{d} no data")
        else:
            # 动态寻找匹配 symbol 的 key (例如 'IC2606' 包含 'IC')
            df_raw = None
            for key in raw.keys():
                if symbol in key:
                    df_raw = raw[key]

            if df_raw is None:
                logger.warning(f"Found keys {list(raw.keys())} but none match {symbol}")
                return pd.DataFrame(columns=["date", "symbol"])

            df = _normalize_columns(df_raw)
            df.attrs["date"] = d
            df.attrs["symbol"] = symbol
            return df
    except Exception:
        logger.exception(f"fetch_cffex_positions error")


# ─── 历史趋势分析 ──────────────────────────────────────────────

def fetch_history(symbol: str = "IC", days: int = 20) -> pd.DataFrame:
    """获取近N个交易日的净空比趋势（需要 akshare）"""
    if not AKSHARE_OK:
        raise ImportError("历史趋势功能需要 akshare：pip install akshare")

    records = []
    delta = 0
    checked = 0
    while len(records) < days and checked < days * 3:
        dt = datetime.today() - timedelta(days=delta)
        delta += 1
        checked += 1
        if dt.weekday() >= 5:  # 跳过周末
            continue
        d = dt.strftime("%Y%m%d")
        try:
            raw = ak.get_cffex_rank_table(date=d, symbol=symbol)
            if raw is None or raw.empty:
                continue
            df = _normalize_columns(raw)
            result = calc_net_short_ratio(df)
            result["date"] = d
            records.append(result)
        except Exception:
            continue

    if not records:
        raise RuntimeError("无法获取历史数据，请检查网络")

    return pd.DataFrame(records).sort_values("date").reset_index(drop=True)


# ─── 输出报告 ──────────────────────────────────────────────────

def print_report(result: dict, df: pd.DataFrame, trade_date: str, symbol: str):
    nsr = result["net_short_ratio"]
    level, desc = interpret_signal(nsr)

    if RICH_OK:
        color = {"深度空头": "red", "正常对冲区间": "yellow",
                 "空头力量偏弱": "green", "多头占优": "bright_green"}.get(level, "white")

        console.print()
        console.print(Panel(
            f"[bold]{symbol} 主力合约净空比报告[/bold]   交易日期：{trade_date}",
            style="bold blue", expand=False
        ))

        # 核心指标表
        t = Table(box=box.SIMPLE, show_header=True, header_style="dim")
        t.add_column("指标", style="dim", width=22)
        t.add_column("数值", justify="right", width=15)
        t.add_column("说明", width=32)
        t.add_row("总多头持仓（手）", f"{result['total_long']:,}", "前20席位多头合计")
        t.add_row("总空头持仓（手）", f"{result['total_short']:,}", "前20席位空头合计")
        t.add_row("净空头（手）", f"{result['net_short']:+,}", "空头 − 多头")
        t.add_row("总持仓量（手）", f"{result['total_oi']:,}", "多头 + 空头")
        t.add_row("─" * 20, "─" * 13, "─" * 30)
        t.add_row("[bold]净空比[/bold]",
                  f"[bold {color}]{nsr:+.2f}%[/bold {color}]",
                  "净空头 / 总持仓量")
        t.add_row("前5空头集中度", f"{result['concentration_top5_short']:.1f}%",
                  "前5席位占总空头比例")
        t.add_row("前5多头集中度", f"{result['concentration_top5_long']:.1f}%",
                  "前5席位占总多头比例")
        console.print(t)

        # 信号判断
        console.print(Panel(
            f"[bold {color}]{level}[/bold {color}]\n[dim]{desc}[/dim]",
            title="信号解读", border_style=color, expand=False
        ))

        # 前10空头席位明细
        if "member" in df.columns:
            top10 = df.nlargest(10, "short_vol").reset_index(drop=True)
            t2 = Table(title="前10空头席位明细", box=box.SIMPLE,
                       show_header=True, header_style="dim")
            t2.add_column("席位", width=14)
            t2.add_column("空头持仓", justify="right", width=10)
            t2.add_column("多头持仓", justify="right", width=10)
            t2.add_column("净空", justify="right", width=12)
            for _, row in top10.iterrows():
                s = int(row.get("short_vol", 0))
                l_v = int(row.get("long_vol", 0))
                net = s - l_v
                net_str = (f"[red]+{net:,}[/red]" if net > 0
                           else f"[green]{net:,}[/green]")
                t2.add_row(str(row.get("member", "—")),
                           f"{s:,}", f"{l_v:,}", net_str)
            console.print(t2)

    else:
        # 纯文本输出（无 rich 时）
        sep = "=" * 55
        print(f"\n{sep}")
        print(f"  {symbol} 主力合约净空比报告  |  {trade_date}")
        print(sep)
        print(f"  总多头持仓  : {result['total_long']:>12,} 手")
        print(f"  总空头持仓  : {result['total_short']:>12,} 手")
        print(f"  净空头      : {result['net_short']:>+12,} 手")
        print(f"  总持仓量    : {result['total_oi']:>12,} 手")
        print(f"  {'─' * 46}")
        print(f"  净空比      : {nsr:>+11.2f} %")
        print(f"  前5空头集中 : {result['concentration_top5_short']:>10.1f} %")
        print(f"  前5多头集中 : {result['concentration_top5_long']:>10.1f} %")
        print(sep)
        print(f"  信号：【{level}】  {desc}")
        print(sep)

        if "member" in df.columns:
            print(f"\n  前10空头席位明细：")
            print(f"  {'席位':<14} {'空头':>8} {'多头':>8} {'净空':>10}")
            print(f"  {'─'*44}")
            top10 = df.nlargest(10, "short_vol")
            for _, row in top10.iterrows():
                s = int(row.get("short_vol", 0))
                l_v = int(row.get("long_vol", 0))
                net = s - l_v
                print(f"  {str(row.get('member','—')):<14} {s:>8,} {l_v:>8,} {net:>+10,}")


def print_history_trend(hist: pd.DataFrame, symbol: str):
    """打印历史净空比趋势"""
    if RICH_OK:
        console.print()
        t = Table(title=f"{symbol} 近期净空比趋势（日频）",
                  box=box.SIMPLE, show_header=True, header_style="dim")
        t.add_column("日期", width=12)
        t.add_column("净空比", justify="right", width=10)
        t.add_column("净空头（手）", justify="right", width=14)
        t.add_column("信号", width=12)
        t.add_column("日变化", width=6)
        prev = None
        for _, row in hist.iterrows():
            nsr = row["net_short_ratio"]
            color = "red" if nsr < -20 else ("yellow" if nsr < -10 else "green")
            level, _ = interpret_signal(nsr)
            trend = ("—" if prev is None
                     else ("[red]↓[/red]" if nsr < prev
                           else ("[green]↑[/green]" if nsr > prev else "→")))
            t.add_row(str(row["date"]),
                      f"[{color}]{nsr:+.2f}%[/{color}]",
                      f"{row['net_short']:,}",
                      f"[{color}]{level}[/{color}]",
                      trend)
            prev = nsr
        console.print(t)
    else:
        print(f"\n{symbol} 近期净空比趋势")
        print(f"{'日期':<12} {'净空比':>10} {'净空头(手)':>14} {'信号':<14}")
        print("-" * 52)
        for _, row in hist.iterrows():
            level, _ = interpret_signal(row["net_short_ratio"])
            print(f"{row['date']:<12} {row['net_short_ratio']:>+9.2f}%  "
                  f"{row['net_short']:>12,}  {level}")


# ─── 对外接口（供其他脚本 import 调用）─────────────────────────

def run_single_from_cache(symbol: str = "IC", trade_date: str = None) -> dict:
    """
    对外提供和 run_single 一样的接口，但从本地 CSV 缓存中读取数据。

    参数：
    symbol     : 合约品种，如 "IC"
    trade_date : 交易日期，格式 "YYYYMMDD" 或 "YYYY-12-31" (需与CSV中格式一致)
    """
    report_file = Path(f"{current_dir}/ic_net_short_records.csv")

    if not report_file.exists():
        raise FileNotFoundError(f"本地缓存文件 {report_file} 不存在")

    # 读取缓存
    cache_df = pd.read_csv(report_file)

    # 统一日期格式为字符串进行匹配
    # 如果 CSV 里的日期是 2018-01-11 这种格式，而输入是 20180111，需要做一层转换
    search_date = str(trade_date)
    if "-" not in search_date and len(search_date) == 8:
        search_date = f"{search_date[:4]}-{search_date[4:6]}-{search_date[6:]}"

    # 过滤数据
    match = cache_df[(cache_df['date'].astype(str) == search_date) &
                     (cache_df['symbol'].str.contains(symbol))]

    if match.empty:
        # raise ValueError(f"在缓存中未找到 {search_date} 对应的 {symbol} 数据")
        return {}

    # 取最近的一条记录并转为字典
    result = match.iloc[-1].to_dict()

    # 确保数值类型正确（从CSV读取后可能是numpy类型，转回原生Python类型以保持兼容性）
    return {
        "total_long": int(result["total_long"]),
        "total_short": int(result["total_short"]),
        "net_short": int(result["net_short"]),
        "total_oi": int(result["total_oi"]),
        "net_short_ratio": float(result["net_short_ratio"]),
        "concentration_top5_short": float(result["concentration_top5_short"]),
        "concentration_top5_long": float(result["concentration_top5_long"]),
        "trade_date": result["trade_date"],
        "symbol": result["symbol"],
        "signal_level": result["signal_level"],
        "signal_desc": interpret_signal(result["net_short_ratio"])[1]  # 重新获取描述
    }


def run_single(symbol: str = "IC", trade_date: str = None) -> dict:
    """
    一行调用接口，返回完整结果字典。

    示例：
        from ic_net_short_ratio import run_single
        r = run_single("IC", "20250415")
        print(r["net_short_ratio"], r["signal_level"])
    """
    result = run_single_from_cache(trade_date=trade_date)
    if result:
        return result
    df = fetch_cffex_positions(symbol=symbol, trade_date=trade_date)
    if df is None or df.empty:
        return None

    result = calc_net_short_ratio(df)
    result["date"] = df.attrs.get("date")
    result["symbol"] = symbol
    level, desc = interpret_signal(result["net_short_ratio"])
    result["signal_level"] = level
    result["signal_desc"] = desc
    return result


def save_report_to_csv(result_dict, file_path="ic_report_history.csv"):
    """
    保存结果到CSV：若日期存在则更新，不存在则追加。
    """
    new_df = pd.DataFrame([result_dict])

    if Path(file_path).exists():
        old_df = pd.read_csv(file_path)
        # 确保 trade_date 是字符串格式以便比较
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


# ─── 主程序入口 ──────────────────────────────────────────────

def main():
    print("\nIC主力合约净空比计算工具")
    print("─" * 40)
    symbol = "IC"
    symbol_list = [symbol]
    report_file = f"{current_dir}ic_net_short_records.csv"

    try:
        # 1. 加载任务清单
        dict_df = pd.read_csv(f'{current_dir}/../tq/date-ic-all.csv')
        dict_df['KQ.m@CFFEX.IC'] = dict_df['KQ.m@CFFEX.IC'].str.replace('CFFEX.', '', regex=False)
        records = dict_df[['date', 'KQ.m@CFFEX.IC']].to_dict('records')

        # 2. 预先加载已有的记录日期，避免重复调用 API
        existing_dates = set()
        if Path(report_file).exists():
            try:
                temp_df = pd.read_csv(report_file)
                if 'trade_date' in temp_df.columns:
                    existing_dates = set(temp_df['trade_date'].astype(str).tolist())
                print(f"检测到本地记录，已跳过 {len(existing_dates)} 条历史数据。")
            except Exception as e:
                print(f"读取历史记录文件失败，将重新爬取: {e}")

        results_data = []
        for row in records:
            trade_date = str(row['date'])
            main_symbol = row['KQ.m@CFFEX.IC']
            if pd.isna(main_symbol):
                logging.debug(f"{trade_date}对应的主力合约在AK没有记录(query_his_cont_quotes接口支持的最早时间2015-04-16")
                continue

            # --- 新增逻辑：检查是否已存在记录 ---
            if trade_date in existing_dates:
                # print(f"日期 {trade_date} 已有记录，跳过 API 调用。") # 可选日志
                continue

            # --- 原始抓取逻辑 ---
            print(f"正在获取 {trade_date} ({main_symbol}) 的数据...")
            try:
                # 调用可能失败的接口
                df = ak.get_cffex_rank_table(date=trade_date, vars_list=symbol_list)

                if main_symbol not in df:
                    print(f"警告：日期 {trade_date} 的返回结果中未找到合约 {main_symbol}")
                    continue

                trade_info = df[main_symbol]
                result = calc_net_short_ratio(trade_info)

                # 补充结果维度
                result['date'] = trade_date
                result['symbol'] = main_symbol
                level, desc = interpret_signal(result["net_short_ratio"])
                result['signal_level'] = level
                results_data.append(result)
                # 3. 打印并保存
                print_report(result, trade_info, trade_date, main_symbol)
                # save_report_to_csv(result, file_path=report_file)
                # 更新内存中的已存在日期集合，防止 records 中有重复日期
                existing_dates.add(trade_date)

            except Exception as e:
                logger.exception(f"获取 {trade_date} 数据失败: {e}")
                continue  # 单次失败不影响整个循环

        if len(results_data) > 0:
            results_df = pd.DataFrame(results_data)
            print_history_trend(results_df, main_symbol)
            results_df.to_csv(report_file)
        else:
            logger.info("no data")

    except Exception as e:
        logging.exception(f"\n运行过程中出现严重错误：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    t = run_single()
    main()
