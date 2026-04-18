import logging
import os
from typing import Optional
from pathlib import Path
import pandas as pd


from tqsdk import TqApi, TqAuth, TqAccount, TqBacktest, BacktestFinished

from utils.logging_config import setup_logging


setup_logging()
logger = logging.getLogger(__name__)

current_dir = Path(__file__).resolve().parent


# # 1. 注册天勤账号并认证


DURATION_DAY = 86400


def calc_annualized_basis(fut_price: float, spot_price: float, days: int) -> Optional[float]:
    """计算年化贴水率"""
    if pd.isna(fut_price) or pd.isna(spot_price) or days <= 0 or spot_price <= 0:
        return None
    basis_ratio = (spot_price - fut_price) / spot_price
    annualized = basis_ratio * 365 / days * 100
    return round(annualized, 3)


def update_ann_basis(csv_path: str):
    # 1. 读取数据
    df = pd.read_csv(csv_path)

    # 2. 计算 ann_basis
    df["ann_basis"] = df.apply(
        lambda row: calc_annualized_basis(
            row.get("fut_close"),
            row.get("idx_close"),
            row.get("days_left", 0)
        ),
        axis=1
    )

    df.to_csv(csv_path, index=False)

    print("✅ ann_basis 已全部更新")


def sync_ic_discount(csv_path: str, kline_df: pd.DataFrame, output_path=None):
    """
    同步 ic_discount_his.csv：
    - 已存在 → 更新
    - 不存在 → 追加
    """

    # 1. 读取CSV
    df = pd.read_csv(csv_path)
    df["datetime"] = pd.to_datetime(df["datetime"])

    # 2. 处理kline数据
    kline_df = kline_df.copy()
    kline_df["datetime"] = pd.to_datetime(kline_df["datetime"], unit="ns")

    # 只保留有效数据
    kline_valid = kline_df.dropna(subset=["close", "close1"]).copy()

    # 标准字段
    kline_valid = kline_valid.rename(columns={
        "close": "fut_close",
        "close1": "idx_close"
    })

    kline_valid = kline_valid[["datetime", "fut_close", "idx_close"]]

    # =========================
    # 3. 拆分：已有 & 新数据
    # =========================
    existing_mask = kline_valid["datetime"].isin(df["datetime"])

    update_df = kline_valid[existing_mask]      # 用来更新
    append_df = kline_valid[~existing_mask]     # 用来追加

    # =========================
    # 4. 更新已有数据
    # =========================
    if not update_df.empty:
        df = df.merge(
            update_df,
            on="datetime",
            how="left",
            suffixes=("", "_new")
        )

        df["fut_close"] = df["fut_close_new"].combine_first(df["fut_close"])
        df["idx_close"] = df["idx_close_new"].combine_first(df["idx_close"])

        df.drop(columns=["fut_close_new", "idx_close_new"], inplace=True)

    # =========================
    # 5. 追加新数据
    # =========================
    if not append_df.empty:
        # ⚠️ 如果你CSV还有其他字段，这里会自动补NaN
        df = pd.concat([df, append_df], ignore_index=True)

    # =========================
    # 6. 排序 + 去重（保险）
    # =========================
    df = df.sort_values("datetime")
    df = df.drop_duplicates(subset=["datetime"], keep="last")

    # =========================
    # 7. 保存
    # =========================
    if output_path:
        df.to_csv(output_path, index=False)
    else:
        df.to_csv(csv_path, index=False)

    print(f"✅ 更新 {len(update_df)} 条 | 追加 {len(append_df)} 条")


def update_ic_discount(csv_path: str, kline_df: pd.DataFrame, output_path=None):
    """
    用最新k线数据更新 ic_discount_his.csv

    :param csv_path: 原始csv路径
    :param kline_df: 从tqsdk获取的kline数据 (需包含 datetime, close, close1)
    :param output_path: 输出路径（默认覆盖原文件）
    """

    # 1. 读取原始数据
    df = pd.read_csv(csv_path)

    # 统一时间格式（关键！）
    df["datetime"] = pd.to_datetime(df["datetime"])
    kline_df["datetime"] = pd.to_datetime(kline_df["datetime"], unit="ns")

    # 2. 只保留有效数据（close 和 close1 不为空）
    kline_valid = kline_df.dropna(subset=["close", "close1"]).copy()

    # 3. 重命名字段以便 merge
    kline_valid = kline_valid.rename(columns={
        "close": "fut_close_new",
        "close1": "idx_close_new"
    })

    # 4. merge 对齐 datetime
    merged = df.merge(
        kline_valid[["datetime", "fut_close_new", "idx_close_new"]],
        on="datetime",
        how="left"
    )

    # 5. 覆盖逻辑（仅当新值存在时替换）
    merged["fut_close"] = merged["fut_close_new"].combine_first(merged["fut_close"])
    merged["idx_close"] = merged["idx_close_new"].combine_first(merged["idx_close"])

    # 6. 删除临时列
    merged.drop(columns=["fut_close_new", "idx_close_new"], inplace=True)

    # 7. 保存
    if output_path:
        merged.to_csv(output_path, index=False)
    else:
        merged.to_csv(csv_path, index=False)

    print("✅ ic_discount_his.csv 更新完成")


if __name__ == "__main__":
    # 从环境变量读取天勤账号（若无则需手动替换）
    token = os.getenv("TQ_ID", "YOUR_TQ_TOKEN")
    pa = os.getenv("TQ_PASS", "YOUR_TQ_PASSWORD")

    # 2015年4月16日至2018年1月，A股共有约665个交易日
    # 2018年1月1日到2026年4月11日，中国A股交易日数量约为1972天
    TRADE_DAYS_HIS = 4020
    # 初始化天勤API
    api = TqApi(auth=TqAuth(token, pa))
    try:
        # 执行更新（默认拉取最近60天数据做比对更新）
        # 获取现货(SSE.000905) 和 期货主力(KQ.m@CFFEX.IC) 的日K线
        kline_df = api.get_kline_serial(
            ["KQ.m@CFFEX.IC", "SSE.000905"],
            duration_seconds=DURATION_DAY,
            data_length=TRADE_DAYS_HIS
        )

        sync_ic_discount(f'{current_dir}/ic_discount_his.csv', kline_df)
        # 重新计算年化收益率
        update_ann_basis(f'{current_dir}/ic_discount_his.csv')
    except Exception as e:
        logging.exception(f"❌ 更新过程中发生错误: {e}")
    finally:
        api.close()
        logging.info("🔌 天勤连接已关闭。")

