import logging
import akshare as ak


# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def capital_concentration(symbol="一级行业"):

    try:
        # 获取行业板块的成交量数据
        # df = ak.stock_board_industry_hist_em(symbol="小金属", start_date="20260213", end_date="20260213", period="日k")
        # df[["日期", "成交量", "成交额"]]

        df = ak.index_analysis_daily_sw(symbol="一级行业", start_date="20260225", end_date="20260225")
        print(df[["指数名称", "发布日期", "成交量", "成交额占比"]])

        # ak.index_hist_sw(symbol="000001", period="day")
        # index_hist_sw_df = ak.index_hist_sw(symbol="801030", period="day")
        # print(index_hist_sw_df.tail(30)[["代码", "日期", "成交量", "成交额"]])
        # index_analysis_daily_sw_df = ak.index_analysis_daily_sw(symbol, start_date="20260213",
        #                                                         end_date="20260213")
        # print(index_analysis_daily_sw_df[["成交量", "指数名称"]])
    except Exception:
        logger.exception("获取行业板块的成交量数据")
        raise

    # industry_turnover = industry_df["amount"].tail(5).mean()
    # ratio = industry_turnover / market_turnover
    # return ratio * 100
