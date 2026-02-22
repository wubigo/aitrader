import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime


# ===============================
# 1️⃣ 获取宏观数据
# ===============================

def get_macro_data():
    # 社融数据
    tsf = ak.macro_china_shrzgm()
    # print(tsf)

    # 筛选最新的 2026年1月 数据
    latest_data = tsf[tsf['月份'].str.startswith('202501')]
    # print(latest_data)
    tsf_latest = latest_data["社会融资规模增量"]
    # print(tsf_latest)

    # M2数据
    # m2 = ak.macro_china_m2()
    # m2 = ak.macro_china_m2_yearly()
    
    # 获取中国宏观月度数据（包含M2）
    # 该接口会返回包括M2余额、同比增长率等在内的数据
    macro_china_money_supply_df = ak.macro_china_money_supply()

    # 由于数据是按月更新的，通常最新的数据会在列表末尾
    # 筛选 M2 相关数据（或者直接查看最后几行）
    # print(macro_china_money_supply_df.tail())
    # print(macro_china_money_supply_df.head())
    # 如果你只想看 M2 供应量（期末值）的最新情况
    m2_data = macro_china_money_supply_df["货币和准货币(M2)-同比增长"]
    # print(m2_data.head(1))
    m2_latest = m2_data.head(1)

    return tsf_latest.item(), m2_latest.item()


# ===============================
# 2️⃣ 国债收益率趋势
# ===============================

def get_bond_trend():
    bond = ak.bond_zh_us_rate()
    bond["日期"] = pd.to_datetime(bond["日期"])
    bond = bond.sort_values("日期")
    recent = bond.tail(30)
    print(recent[['日期', '中国国债收益率10年', '中国国债收益率2年']])

    y1 = recent.iloc[0]["中国国债收益率10年"]
    y2 = recent.iloc[-1]["中国国债收益率10年"]
    print(y1, y2)

    if y2 < y1:
        return -1
    elif y2 > y1:
        return 1
    else:
        return 0


# ===============================
# 3️⃣ 沪深300趋势
# ===============================

def get_market_trend():
    hs300 = ak.stock_zh_index_daily(symbol="sh000300")
    hs300["date"] = pd.to_datetime(hs300["date"])
    hs300 = hs300.sort_values("date")

    hs300["ma120"] = hs300["close"].rolling(120).mean()

    latest = hs300.iloc[-1]

    if latest["close"] > latest["ma120"]:
        return 1
    else:
        return 0


# ===============================
# 4️⃣ 评分逻辑
# ===============================

def calculate_score(tsf, m2, bond_trend, market_trend):
    score = 0

    # 社融评分
    if tsf > 30000:
        score += 10
    elif tsf > 20000:
        score += 6
    else:
        score += 3

    # M2评分
    if m2 > 9:
        score += 10
    elif m2 > 7:
        score += 6
    else:
        score += 3

    # 国债收益率趋势
    if bond_trend == -1:
        score += 10
    else:
        score += 5

    # 沪深300趋势
    if market_trend == 1:
        score += 20
    else:
        score += 5

    return score


def market_state(score):
    if score > 40:
        return "趋势增强（可提高仓位）"
    elif score > 25:
        return "结构行情（精选行业龙头）"
    else:
        return "风险偏高（降低仓位）"


# ===============================
# 5️⃣ 主程序
# ===============================

if __name__ == "__main__":
    print("正在抓取最新数据...")

    tsf, m2 = get_macro_data()
    bond_trend = get_bond_trend()
    market_trend = get_market_trend()

    score = calculate_score(tsf, m2, bond_trend, market_trend)

    print("------ A股环境自动评分 ------")
    print("社融增量:", tsf)
    print("M2同比:", m2)
    print("国债收益率趋势:", bond_trend)
    print("沪深300趋势:", market_trend)
    print("综合评分:", score)
    print("市场状态:", market_state(score))