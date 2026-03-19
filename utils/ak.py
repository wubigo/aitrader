import pandas as pd
import requests
import math
from akshare.utils.tqdm import get_tqdm


def index_analysis_daily_sw(
        index_code: str = "801081",
        start_date: str = "20260318",
        end_date: str = "20260318",
) -> pd.DataFrame:
    """
    申万宏源研究-指数分析
    https://www.swsresearch.com/institute_sw/allIndex/analysisIndex
    :param index_code: 指数代码
    :type index_code: str
    :param symbol: choice of {"市场表征", "一级行业", "二级行业", "风格指数"}
    :type symbol: str
    :param start_date: 开始日期
    :type start_date: str
    :param end_date: 结束日期
    :type end_date: str
    :return: 指数分析
    :rtype: pandas.DataFrame
    """
    symbol = "一级行业",
    url = "https://www.swsresearch.com/institute-sw/api/index_analysis/index_analysis_report/"
    params = {
        "page": "1",
        "page_size": "50",
        "index_type": symbol,
        "start_date": "-".join([start_date[:4], start_date[4:6], start_date[6:]]),
        "end_date": "-".join([end_date[:4], end_date[4:6], end_date[6:]]),
        "type": "DAY",
        "swindexcode": index_code,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/114.0.0.0 Safari/537.36"
    }
    r = requests.get(url, params=params, headers=headers, verify=False)
    data_json = r.json()
    total_num = data_json["data"]["count"]
    total_page = math.ceil(total_num / 50)
    big_df = pd.DataFrame()
    tqdm = get_tqdm()
    for page in tqdm(range(1, total_page + 1), leave=False):
        params.update({"page": page})
        r = requests.get(url, params=params, headers=headers, verify=False)
        data_json = r.json()
        temp_df = pd.DataFrame(data_json["data"]["results"])
        big_df = pd.concat(objs=[big_df, temp_df], ignore_index=True)
    big_df.rename(
        columns={
            "swindexcode": "指数代码",
            "swindexname": "指数名称",
            "bargaindate": "发布日期",
            "closeindex": "收盘指数",
            "bargainamount": "成交量",
            "markup": "涨跌幅",
            "turnoverrate": "换手率",
            "pe": "市盈率",
            "pb": "市净率",
            "meanprice": "均价",
            "bargainsumrate": "成交额占比",
            "negotiablessharesum1": "流通市值",
            "negotiablessharesum2": "平均流通市值",
            "dp": "股息率",
        },
        inplace=True,
    )
    big_df["发布日期"] = pd.to_datetime(big_df["发布日期"], errors="coerce").dt.date
    big_df["收盘指数"] = pd.to_numeric(big_df["收盘指数"], errors="coerce")
    big_df["成交量"] = pd.to_numeric(big_df["成交量"], errors="coerce")
    big_df["涨跌幅"] = pd.to_numeric(big_df["涨跌幅"], errors="coerce")
    big_df["换手率"] = pd.to_numeric(big_df["换手率"], errors="coerce")
    big_df["市盈率"] = pd.to_numeric(big_df["市盈率"], errors="coerce")
    big_df["市净率"] = pd.to_numeric(big_df["市净率"], errors="coerce")
    big_df["均价"] = pd.to_numeric(big_df["均价"], errors="coerce")
    big_df["成交额占比"] = pd.to_numeric(big_df["成交额占比"], errors="coerce")
    big_df["流通市值"] = pd.to_numeric(big_df["流通市值"], errors="coerce")
    big_df["平均流通市值"] = pd.to_numeric(big_df["平均流通市值"], errors="coerce")
    big_df["股息率"] = pd.to_numeric(big_df["股息率"], errors="coerce")
    big_df.sort_values(by=["发布日期"], inplace=True, ignore_index=True)
    return big_df


def index_publish_daily_sw(symbol: str = "801081", start_date: str = "20260318",
                  end_date: str = "20260318") -> pd.DataFrame:
    """
    申万宏源研究-指数发布-指数详情-指数历史数据
    https://www.swsresearch.com/institute_sw/allIndex/releasedIndex/releasedetail?code=801001&name=%E7%94%B3%E4%B8%8750
    :param end_date:
    :param start_date:
    :param symbol: 指数代码
    :type symbol: str
    :param period: choice of {"day", "week", "month"}
    :type period: str
    :return: 指数历史数据
    :rtype: pandas.DataFrame
    """
    period_map = {
        "day": "DAY",
        "week": "WEEK",
        "month": "MONTH",
    }
    url = "https://www.swsresearch.com/institute-sw/api/index_publish/history/"
    params = {
        "page": "1",
        "page_size": "50",
        "index_type": "二级行业",
        "index_code": symbol,
        "start_date": "-".join([start_date[:4], start_date[4:6], start_date[6:]]),
        "end_date": "-".join([end_date[:4], end_date[4:6], end_date[6:]]),

    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/114.0.0.0 Safari/537.36",
    }
    r = requests.get(url, params=params, headers=headers, verify=False)
    data_json = r.json()
    total_num = data_json.get("data", {}).get("count", 0)
    
    # 如果没有数据，直接返回空 DataFrame
    if total_num == 0:
        print(f"申万指数 {symbol} 无数据")
        return pd.DataFrame(columns=["代码", "日期", "收盘", "开盘", "最高", "最低", "成交量", "成交额"])
    
    total_page = math.ceil(total_num / 50)
    big_df = pd.DataFrame()
    tqdm = get_tqdm()
    for page in tqdm(range(1, total_page + 1), leave=False):
        params.update({"page": page})
        r = requests.get(url, params=params, headers=headers, verify=False)
        data_json = r.json()
        temp_df = pd.DataFrame(data_json["data"]["results"])
        big_df = pd.concat(objs=[big_df, temp_df], ignore_index=True)

    # 如果合并后仍为空，返回标准结构的空 DataFrame
    if big_df.empty:
        print(f"申万指数 {symbol} 数据获取失败，返回空 DataFrame")
        return pd.DataFrame(columns=["代码", "日期", "收盘", "开盘", "最高", "最低", "成交量", "成交额"])
    
    big_df.rename(
        columns={
            "swindexcode": "代码",
            "bargaindate": "日期",
            "openindex": "开盘",
            "maxindex": "最高",
            "minindex": "最低",
            "closeindex": "收盘",
            "hike": "",
            "markup": "",
            "bargainamount": "成交量",
            "bargainsum": "成交额",
        },
        inplace=True,
    )
    big_df = big_df[
        [
            "代码",
            "日期",
            "收盘",
            "开盘",
            "最高",
            "最低",
            "成交量",
            "成交额",
        ]
    ]
    big_df["日期"] = pd.to_datetime(big_df["日期"], errors="coerce").dt.date
    big_df["收盘"] = pd.to_numeric(big_df["收盘"], errors="coerce")
    big_df["最高"] = pd.to_numeric(big_df["最高"], errors="coerce")
    big_df["最低"] = pd.to_numeric(big_df["最低"], errors="coerce")
    big_df["成交量"] = pd.to_numeric(big_df["成交量"], errors="coerce")
    big_df["成交额"] = pd.to_numeric(big_df["成交额"], errors="coerce")
    return big_df


