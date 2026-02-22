import akshare as ak
import pandas as pd
import numpy as np

# =============================
# 1️⃣ 获取行业指数列表
# =============================

def get_industry_list():

    df = ak.sw_index_first_info()
    print(df)
    # return df["行业名称"].tolist()
    return df[["行业代码", "行业名称"]].values.tolist()


# =============================
# 2️⃣ 获取行业历史数据
# =============================

def get_industry_data(industry_name):

    # df = ak.index_stock_info_sw_level1(symbol=industry_name)
    industry_name = industry_name.replace('.SI', '')
    df = ak.index_hist_sw(symbol=industry_name)
    # df["date"] = pd.to_datetime(df["日期"])
    # print(df.tail(1))
    df = df.sort_values("日期")
    return df


# =============================
# 3️⃣ 计算行业强度
# =============================

def calculate_industry_score(df, hs300_df):

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
    score += rs * 100

    # ④ 量能变化
    if "成交量" in df.columns:
        vol_ratio = df["成交量"].iloc[-1] / df["成交量"].rolling(20).mean().iloc[-1]
        if vol_ratio > 1.2:
            score += 10

    return round(score, 2)


# =============================
# 4️⃣ 主程序
# =============================

def run_industry_ranking():

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
        except:
            continue

    ranking = pd.DataFrame(results, columns=["行业", "行业名称", "评分"])
    ranking = ranking.sort_values("评分", ascending=False)

    return ranking


if __name__ == "__main__":
    ranking = run_industry_ranking()

    print("\n===== 行业轮动排名 TOP10   领涨=====")
    print(ranking.head(10))
    print("\n===== 行业轮动排名 TOP10   领跌=====")
    print(ranking.tail(10))

    ranking.to_csv("data/industry_ranking.csv", index=False)