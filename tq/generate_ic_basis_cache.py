import os
import time
import pandas as pd
from datetime import date, timedelta
from tqsdk import TqApi, TqAuth, TqBacktest, BacktestFinished
import logging

from utils.logging_config import setup_logging
from utils.github_tools import backup_file
setup_logging()
logger = logging.getLogger(__name__)

CACHE_FILE = "ic_2021.csv"
CHUNK_SIZE = 5000


def calc_annualized_basis(fut_price, spot_price, days):
    """计算年化贴水率"""
    if pd.isna(fut_price) or pd.isna(spot_price) or days <= 0 or spot_price <= 0:
        return None
    basis_ratio = (spot_price - fut_price) / spot_price
    annualized = basis_ratio * 365 / days * 100
    return round(annualized, 3)


def generate_ic_basis_cache(start: str, end: str, years=5):
    """使用 wait_update 循环方式生成最近5年正确的IC年化贴水缓存（推荐）"""
    logger.info(f"开始生成最近 {years} 年 IC 年化贴水缓存（wait_update 模式）...")
    if start is None and end is None:
        end_dt = date.today()
        start_dt = end_dt - timedelta(days=years * 365)
    else:
        start_dt = date.fromisoformat(start)
        end_dt = date.fromisoformat(end)
    logger.info(f"start_dt:{start_dt}")

    token = os.getenv("TQ_ID")
    pa = os.getenv("TQ_PASS")

    api = TqApi(
        backtest=TqBacktest(start_dt=start_dt, end_dt=end_dt),
        auth=TqAuth(token, pa)
    )

    fut_symbol = "KQ.m@CFFEX.IC"
    idx_symbol = "SSE.000905"

    # 订阅日K线和Quote
    fut_klines = api.get_kline_serial(fut_symbol, 86400, data_length=1)
    idx_klines = api.get_kline_serial(idx_symbol, 86400, data_length=1)
    quote = api.get_quote(fut_symbol)
    current_underlying = quote.underlying_symbol

    records = []
    last_dt = 0

    logger.info("开始按时间顺序推进回测并计算年化贴水...")

    try:
        while True:
            api.wait_update()

            if api.is_changing(quote, "underlying_symbol"):
                new_underlying = quote.underlying_symbol
                logger.info(f"时间: {quote.datetime} 【主力切换】{current_underlying or '开始'} → {new_underlying} ")
                quote = api.get_quote(fut_symbol)
                current_underlying = quote.underlying_symbol

            # 只在期货K线有更新时处理
            if api.is_changing(fut_klines):
                new_bars = fut_klines[fut_klines["datetime"] > last_dt]

                for _, row in new_bars.iterrows():
                    dt_nano = row["datetime"]
                    dt = pd.to_datetime(dt_nano, unit='ns')

                    fut_close = row["close"]

                    # 匹配同一天指数K线
                    idx_match = idx_klines[idx_klines["datetime"] == dt_nano]
                    if idx_match.empty:
                        continue

                    idx_close = idx_match.iloc[0]["close"]
                    if idx_close <= 0 or fut_close <= 0:
                        continue

                    # 获取当前剩余天数（关键：每次从 quote 取最新值）
                    quote = api.get_quote(fut_symbol)
                    expire_rest_days = quote.underlying_quote.expire_rest_days

                    if pd.isna(expire_rest_days) or expire_rest_days <= 0:
                        expire_rest_days = 30  # 兜底
                    else:
                        logger.info(f"{dt} {quote.underlying_symbol} expires {expire_rest_days}")

                    ann_basis = calc_annualized_basis(fut_close, idx_close, expire_rest_days)
                    if ann_basis is not None:
                        records.append({
                            "datetime": dt,
                            "fut_close": round(fut_close, 2),
                            "idx_close": round(idx_close, 2),
                            "days_left": int(expire_rest_days),
                            "ann_basis": ann_basis
                        })

                    if len(records) % 200 == 0:
                        logger.info(f"已计算 {len(records)} 条记录，当前日期: {dt.date()}")

                    if len(records) >= CHUNK_SIZE:
                        chunk_df = pd.DataFrame(records)
                        chunk_df["datetime"] = pd.to_datetime(chunk_df["datetime"], unit="ns")
                        # 第一次写入需带 header，后续追加不带 header
                        is_first_write = not os.path.exists(CACHE_FILE)
                        chunk_df.to_csv(CACHE_FILE, mode='a', index=False, header=is_first_write)
                        records.clear()  # 关键：释放内存
                        logger.info(f"💾 已自动同步 {CHUNK_SIZE} 行数据至磁盘，当前内存占用已释放")

                last_dt = fut_klines.iloc[-1]["datetime"]

    except BacktestFinished:
        logger.info("回测自然结束，开始保存缓存...")
    except Exception as e:
        logger.error(f"生成缓存过程中出错: {e}")
    finally:
        # 保存缓存
        if records:

            chunk_df = pd.DataFrame(records)
            chunk_df["datetime"] = pd.to_datetime(chunk_df["datetime"], unit="ns")
            # 如果文件不存在说明是第一次写（之前从未达到过 CHUNK_SIZE）
            is_first_write = not os.path.exists(CACHE_FILE)
            chunk_df.to_csv(CACHE_FILE, mode='a', index=False, header=is_first_write)
            records.clear()
            if IN_COLAB:
                backup_file(CACHE_FILE)
            logger.info(f"✅ 缓存生成成功！共 {len(chunk_df)} 条记录")
            logger.info(f"时间范围: {chunk_df['datetime'].min().date()} ~ {chunk_df['datetime'].max().date()}")
            logger.info(f"年化贴水平均值: {chunk_df['ann_basis'].mean():.2f}% | "
                        f"最大: {chunk_df['ann_basis'].max():.2f}% | 最小: {chunk_df['ann_basis'].min():.2f}%")
        else:
            logger.error("未能生成任何有效记录")


        api.close()


def is_colab():
    try:
        import google.colab
        return True
    except ImportError:
        return False


def get_ic_annualized_basis_percentile(years=5, current_ann_basis=None):

    df = pd.read_csv(CACHE_FILE)
    df["datetime"] = pd.to_datetime(df["datetime"])

    # 过滤最近 years 年数据
    cutoff = pd.Timestamp.today() - pd.Timedelta(days=years * 365 + 100)
    df = df[df["datetime"] >= cutoff]

    historical = df["ann_basis"].dropna()

    stats = {
        "total_days": len(historical),
        "mean": round(historical.mean(), 3),
        "p75": round(historical.quantile(0.75), 3),
        "p90": round(historical.quantile(0.90), 3),
        "p95": round(historical.quantile(0.95), 3),
        "current_percentile": None
    }

    if current_ann_basis is not None:
        stats["current_percentile"] = round((historical < current_ann_basis).mean() * 100, 2)

    return stats


IN_COLAB = is_colab()


def reset_cache():
    stime = time.perf_counter()
    # 代码
    years = os.getenv("IC_YEARS")
    if years is not None:
        years = int(years)
    else:
        years = 1  # 默认值
    start = '2017-10-01'
    end = '2018-03-31'
    generate_ic_basis_cache(years=years, start=start, end=end)
    etime = time.perf_counter()
    logger.info(f"运行时长：{(etime - stime) / 60:.2f} 分")


if __name__ == "__main__":
    stats = get_ic_annualized_basis_percentile(5, current_ann_basis=7)
    print(stats)
    print(stats["current_percentile"])