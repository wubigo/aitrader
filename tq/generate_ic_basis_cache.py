from pathlib import Path
import os
import time
import pandas as pd
from datetime import date, timedelta
from typing import Optional, List, Dict

from tqsdk import TqApi, TqAuth, TqBacktest, BacktestFinished
import logging

from utils.logging_config import setup_logging
from utils.github_tools import backup_file

setup_logging()
logger = logging.getLogger(__name__)

current_dir = Path(__file__).resolve().parent
CHUNK_SIZE = 5000


def calc_annualized_basis(fut_price: float, spot_price: float, days: int) -> Optional[float]:
    """计算年化贴水率"""
    if pd.isna(fut_price) or pd.isna(spot_price) or days <= 0 or spot_price <= 0:
        return None
    basis_ratio = (spot_price - fut_price) / spot_price
    annualized = basis_ratio * 365 / days * 100
    return round(annualized, 3)

def _flush_records(records: List[Dict], cache_file: Path):
    if not records:
        return
    chunk_df = pd.DataFrame(records)
    # 第一次写入需带 header，后续追加不带 header
    is_first_write = not cache_file.exists()
    chunk_df.to_csv(cache_file, mode='a', index=False, header=is_first_write)
    logger.info(f"💾 已同步 {len(records)} 行数据至磁盘: {cache_file.name}")

def generate_basis_cache(fut_symbol: str, idx_symbol: str, cache_file_name: str, start: Optional[str] = None, end: Optional[str] = None, years: int = 5):
    """通用回测统计缓存生成函数"""
    cache_file = current_dir / cache_file_name
    logger.info(f"开始生成 {fut_symbol} (vs {idx_symbol}) 的年化贴水缓存...")

    if start is None and end is None:
        end_dt = date.today()
        start_dt = end_dt - timedelta(days=years * 365+100)
    else:
        start_dt = date.fromisoformat(start)
        end_dt = date.fromisoformat(end)

    logger.info(f"回测区间: {start_dt} ~ {end_dt}")

    token = os.getenv("TQ_ID")
    pa = os.getenv("TQ_PASS")

    api = TqApi(
        backtest=TqBacktest(start_dt=start_dt, end_dt=end_dt),
        auth=TqAuth(token, pa)
    )

    fut_klines = api.get_kline_serial(fut_symbol, 86400, data_length=1)
    idx_klines = api.get_kline_serial(idx_symbol, 86400, data_length=1)
    quote = api.get_quote(fut_symbol)
    current_underlying = quote.underlying_symbol

    records = []
    last_dt = 0

    try:
        while True:
            api.wait_update()

            if api.is_changing(quote, "underlying_symbol"):
                new_underlying = quote.underlying_symbol
                logger.info(f"时间: {quote.datetime} 【主力切换】{current_underlying or '开始'} → {new_underlying} ")
                current_underlying = new_underlying

            if api.is_changing(fut_klines):
                new_bars = fut_klines[fut_klines["datetime"] > last_dt]

                for _, row in new_bars.iterrows():
                    dt_nano = row["datetime"]
                    dt = pd.to_datetime(dt_nano, unit='ns')
                    fut_close = row["close"]

                    idx_match = idx_klines[idx_klines["datetime"] == dt_nano]
                    if idx_match.empty:
                        continue

                    idx_close = idx_match.iloc[0]["close"]
                    if idx_close <= 0 or fut_close <= 0:
                        continue

                    # 实时获取当时对应的 quote 剩余天数
                    expire_rest_days = quote.underlying_quote.expire_rest_days

                    if pd.isna(expire_rest_days) or expire_rest_days <= 0:
                        expire_rest_days = 30  # 兜底

                    ann_basis = calc_annualized_basis(fut_close, idx_close, expire_rest_days)
                    if ann_basis is not None:
                        records.append({
                            "datetime": dt,
                            "fut_close": round(fut_close, 2),
                            "idx_close": round(idx_close, 2),
                            "days_left": int(expire_rest_days),
                            "ann_basis": ann_basis
                        })

                    if len(records) >= CHUNK_SIZE:
                        _flush_records(records, cache_file)
                        records.clear()

                last_dt = fut_klines.iloc[-1]["datetime"]

    except BacktestFinished:
        logger.info(f"{fut_symbol} 回测结束")
    except Exception as e:
        logger.error(f"生成缓存过程中出错: {e}")
    finally:
        if records:
            _flush_records(records, cache_file)
            records.clear()

        if is_colab() and cache_file.exists():
            backup_file(cache_file)

        api.close()

def is_colab():
    try:
        import google.colab
        return True
    except ImportError:
        return False

def get_basis_percentile(cache_file_name: str, years: int = 5, current_ann_basis: Optional[float] = None):
    """通用百分位计算函数"""
    cache_file = current_dir / cache_file_name
    if not cache_file.exists():
        logger.error(f"缓存文件不存在: {cache_file}")
        return {}

    df = pd.read_csv(cache_file)
    df["datetime"] = pd.to_datetime(df["datetime"])

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

def get_ic_annualized_basis_percentile(years=5, current_ann_basis=None):
    return get_basis_percentile("ic_discount_his.csv", years, current_ann_basis)

def get_im_annualized_basis_percentile(years=5, current_ann_basis=None):
    return get_basis_percentile("im_discount_his.csv", years, current_ann_basis)

if __name__ == "__main__":
    # 需要生成的列表
    tasks = [
        {"fut": "KQ.m@CFFEX.IM", "idx": "SSE.000852", "file": "im_discount_his.csv"},
        {"fut": "KQ.m@CFFEX.IC", "idx": "SSE.000905", "file": "ic_discount_his.csv"},

    ]

    # 获取环境变量控制的参数
    years_env = os.getenv("IC_YEARS")
    years = int(years_env) if years_env else 8

    for task in tasks:
        # 如果文件已存在，可以选择跳过或重新生成（此处演示为重新生成/追加，根据逻辑逻辑建议先手动删除旧文件若需全新生成）
        # 为了安全，这里不自动删除，但在生产中通常先判断
        generate_basis_cache(
            fut_symbol=task["fut"],
            idx_symbol=task["idx"],
            cache_file_name=task["file"],
            years=years
        )

        # 打印简单统计
        stats = get_basis_percentile(task["file"], years=years)
        logger.info(f"{task['fut']} 统计结果: {stats}")
