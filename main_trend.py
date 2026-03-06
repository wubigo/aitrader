import logging
import akshare as ak
import pandas as pd
from datetime import datetime


# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def capital_concentration(symbol="一级行业", date_str: str = None):
    """计算行业成交量占比（成交量占比 = 行业成交量 / 当日所有行业成交量）

    参数:
        symbol: akshare 接口使用的板块层级，默认 `一级行业`。
        date_str: 日期，格式 YYYYMMDD。默认为当天。

    返回:
        包含原字段并新增 `成交量占比`（百分比）的 DataFrame；失败时返回 None。
    """

    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    try:
        df = ak.index_analysis_daily_sw(symbol="一级行业", start_date="20260225", end_date="20260225")
        print(df[["指数名称", "发布日期", "成交量", "成交额占比"]])

        df = ak.index_analysis_daily_sw(symbol=symbol, start_date=date_str, end_date=date_str)

        if df is None or df.empty:
            logger.info(f"没有获取到 {date_str} 的数据: symbol={symbol}")
            return None

        # 确保成交量为数值（部分接口可能返回字符串带千分位）
        if "成交量" in df.columns:
            df["成交量"] = (
                df["成交量"].astype(str).str.replace(",", "", regex=False).replace("--", "0")
            )
            df["成交量"] = pd.to_numeric(df["成交量"], errors="coerce").fillna(0)
        else:
            logger.warning("返回数据中不包含 '成交量' 列")
            df["成交量"] = 0

        total_vol = df["成交量"].sum()
        if total_vol == 0:
            logger.warning(f"{date_str} 总成交量为 0，无法计算占比")
            df["成交量占比"] = 0.0
        else:
            df["成交量占比"] = df["成交量"] / total_vol * 100

        # 格式化并显示常用列
        display_cols = [c for c in ["指数名称", "发布日期", "成交量", "成交额占比", "成交量占比"] if c in df.columns]
        print(df[display_cols].sort_values("成交量占比", ascending=False).reset_index(drop=True))

        return df

    except Exception:
        logger.exception("获取行业板块的成交量数据失败")
        raise

    # 未来可扩展：与全市场成交量比较、滑动窗口占比、北向资金占比等分析
