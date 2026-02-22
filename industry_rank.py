
import akshare as ak
import pandas as pd
import numpy as np
import logging

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================
# 1️⃣ 获取行业指数列表
# =============================

def get_industry_list():
    try:
        df = ak.sw_index_first_info()
        return df[["行业代码", "行业名称"]].values.tolist()
    except Exception as e:
        logger.error(f"获取行业列表失败: {e}")
        return []

# =============================
# 2️⃣ 获取行业历史数据
# =============================

def get_industry_data(industry_name):
    try:
        industry_name = industry_name.replace('.SI', '')
        df = ak.index_hist_sw(symbol=industry_name)
        df = df.sort_values("日期")
        return df
    except Exception as e:
        logger.error(f"获取行业数据失败 {industry_name}: {e}")
        return pd.DataFrame()

# =============================
# 3️⃣ 计算行业强度
# 行业总评分 =
# 趋势强度（30%）
# + 动量强度（20%）
# + 相对强弱RS（15%）
# + 资金活跃度（10%）
# + ⭐ 盈利增速（25%）
# =============================

def calculate_industry_score(df, hs300_df):
    try:
        df["ma60"] = df["收盘"].rolling(60).mean()
        df["ma120"] = df["收盘"].rolling(120).mean()

        latest = df.iloc[-1]
        score = 0

        # ① 趋势判断
        if latest["收盘"] > latest["ma120"]:
            score += 30

        # ② 动量（20日涨幅）
        if len(df) > 20:
            ret20 = df["收盘"].pct_change(20).iloc[-1]
            score += ret20 * 100

        # ③ 相对沪深300强度
        industry_ret = df["收盘"].pct_change(20).iloc[-1]
        hs300_ret = hs300_df["close"].pct_change(20).iloc[-1]
        rs = industry_ret - hs300_ret
        print("相对沪深300强度:%f", rs)
        score += rs * 100

        # ④ 量能变化
        if "成交量" in df.columns:
            vol_ratio = df["成交量"].iloc[-1] / df["成交量"].rolling(20).mean().iloc[-1]
            if vol_ratio > 1.2:
                score += 10

        return round(score, 2)
    except Exception as e:
        logger.error(f"计算行业评分失败: {e}")
        return 0

def get_industry_stocks(industry_code):
    try:
        industry_code = industry_code.replace('.SI', '')
        df = ak.index_component_sw(symbol=industry_code)
        return df["证券代码"].tolist()
    except Exception as e:
        logger.error(f"获取行业成分股失败 {industry_code}: {e}")
        return []

def get_stock_profit_growth(symbol):
    try:
        df = ak.stock_financial_analysis_indicator(symbol=symbol)
        df = df.sort_values("报告期")
        # 最新净利润同比
        growth = float(df.iloc[-1]["净利润同比增长率"])
        return growth
    except Exception as e:
        logger.warning(f"获取股票盈利增长失败 {symbol}: {e}")
        return None

def industry_earnings_score(industry_code):
    try:
        stocks = get_industry_stocks(industry_code)
        growth_list = []

        for s in stocks[:30]:   # 取前30避免过慢
            g = get_stock_profit_growth(s)
            if g is not None:
                growth_list.append(g)

        if len(growth_list) == 0:
            return 0

        median_growth = np.median(growth_list)

        # 转换为评分
        if median_growth > 30:
            return 25
        elif median_growth > 15:
            return 18
        elif median_growth > 5:
            return 12
        else:
            return 5
    except Exception as e:
        logger.error(f"计算行业盈利评分失败 {industry_code}: {e}")
        return 0

# =============================
# 4️⃣ 主程序
# =============================

def run_industry_ranking():
    try:
        print("获取沪深300数据...")
        hs300 = ak.stock_zh_index_daily(symbol="sh000300")
        hs300["date"] = pd.to_datetime(hs300["date"])
        hs300 = hs300.sort_values("date")

        industries = get_industry_list()

        results = []

        for name, code in industries:
            try:
                df = get_industry_data(name)
                score = calculate_industry_score(df, hs300)
                results.append((name, code, score))
                print(f"{name} 评分完成")
            except Exception as e:
                logger.error(f"处理行业 {name} 失败: {e}")
                continue

        # for name, code in industries:
        #     try:
        #         score = industry_earnings_score(name)
        #         results.append((name, code, score))
        #         print(f"{name} 评分完成: {score}")
        #     except Exception as e:
        #         logger.error(f"处理行业 {name} 失败: {e}")
        #         continue


        ranking = pd.DataFrame(results, columns=["行业", "行业名称", "评分"])
        ranking = ranking.sort_values("评分", ascending=False)
        return ranking
    except Exception as e:
        logger.error(f"运行行业排名失败: {e}")
        return pd.DataFrame()


if __name__ == "__main__":
    try:
        ranking = run_industry_ranking()

        print("\n===== 行业轮动排名 TOP10   领涨=====")
        print(ranking.head(10))
        print("\n===== 行业轮动排名 TOP10   领跌=====")
        print(ranking.tail(10))

        ranking.to_csv("data/industry_ranking.csv", index=False)
    except Exception as e:
        logger.error(f"主程序执行失败: {e}")