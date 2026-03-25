import logging

import requests
import json
import pandas as pd
from datetime import datetime, timedelta
import time
import warnings
import calendar
from chinese_calendar import is_workday, is_holiday  # 中国节假日判断库
import akshare as ak
from Ashare import get_price
from utils.backtest_logger import backup_dataframe
from backtest_logger import backup_dataframe

warnings.filterwarnings('ignore')


def get_remaining_days(expiry_str):
    """计算剩余天数"""
    expiry_date = datetime.strptime(expiry_str, "%Y%m%d")
    today = datetime.now()
    return max((expiry_date - today).days, 1)  # 避免除零


def get_main_contract_expiry(symbol, exchange='CFFEX'):
    """
    获取指定期货的最活跃主力合约到期日
    symbol: 'IC', 'IM', 'IF', 'IH'
    """
    # 获取期货基本信息
    futures_info = ak.futures_main_contract_symbol()

    # 获取该品种所有合约信息
    all_contracts = ak.futures_delivery_date(symbol=symbol)

    if all_contracts.empty:
        print(f"未找到 {symbol} 合约信息")
        return None

    # 获取实时主力合约（按成交量排序）
    main_contract = ak.futures_main_sina(symbol=symbol)
    if main_contract.empty:
        print(f"未找到 {symbol} 主力实时数据")
        return None

    main_code = main_contract.iloc[0]['品种代码']  # 最活跃合约代码

    # 在所有合约中匹配主力合约，获取到期日
    contract_row = all_contracts[all_contracts['合约代码'] == main_code]

    if contract_row.empty:
        print(f"主力合约 {main_code} 未找到交割日期")
        return None

    expiry_date = pd.to_datetime(contract_row.iloc[0]['最后交割日'])
    today = datetime.now()
    remaining_days = (expiry_date - today).days

    return {
        '主力合约': main_code,
        '最后交割日': expiry_date.strftime('%Y-%m-%d'),
        '剩余天数': max(remaining_days, 1),
        '成交量': main_contract.iloc[0].get('成交量', 'N/A')
    }


def calc_annualized_basis(fut_price, spot_price, days):
    """计算年化贴水率"""
    # Handle pandas Series or None values
    try:
        if pd.isna(fut_price) or pd.isna(spot_price) or days <= 0:
            return None
    except (TypeError, ValueError):
        return None
    
    if fut_price is None or spot_price is None or days <= 0:
        return None
    basis_ratio = (spot_price - fut_price) / spot_price
    annualized = basis_ratio * 365 / days * 100
    return annualized


def monitor_all_basis(interval=60):
    """监控所有股指年化贴水"""
    print("🚀 股指期货年化贴水实时监控启动 (每{}s刷新)".format(interval))
    print("=" * 80)

    code = "IC0"
    year, month = 2026, 6
    last_trading_day = get_last_trading_day(year, month)

    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{now}] 更新数据...")

        results = {}

        print(f"最后交易日（含顺延）: {last_trading_day}")

        days = get_remaining_days(last_trading_day.strftime("%Y%m%d"))

        fut_price = get_future_price()
        spot_price = get_spot_price()

        ann_basis = calc_annualized_basis(fut_price, spot_price, days)

        status = ""
        if ann_basis is not None:
            if ann_basis > 8:
                status = "🚨 厚贴水-建仓!"
            elif ann_basis > 6:
                status = "📊 中等-观察"
            elif ann_basis > 3:
                status = "✅ 轻微贴水"
            else:
                status = "➡️ 基本平水"

        results[code] = {
            'code': code,
            '期货价': fut_price,
            '现货价': spot_price,
            '贴水点数': (spot_price - fut_price) if (fut_price is not None and spot_price is not None) else None,
            '年化贴水%': ann_basis,
            '剩余天数': days,
            '状态': status,
            'timestamp':datetime.now()
        }

        print(f"{code}: 年化贴水 {ann_basis:.2f}% {status} | 期货:{fut_price:.2f} 现货:{spot_price:.2f}")

        # 保存到CSV（可选）
        df = pd.DataFrame(results).T
        backup_dataframe(df, f"{code}-年化贴水-{datetime.now().strftime('%Y%m%d')}.csv")

        time.sleep(interval)


def get_future_price():
    symbol = "中证500指数期货"
    futures_realtime = ak.futures_zh_realtime(symbol)
    # futures_realtime.rename(columns={'preclose': '前收盘价'}, inplace=True)
    # futures_realtime.rename(columns={'trade': '最新价'}, inplace=True)
    today = datetime.today().strftime("%y%m%d")
    futures_realtime["timestamp"] = pd.Timestamp.now()
    futures_realtime = futures_realtime.sort_values("symbol")
    futures_realtime = futures_realtime[["symbol", "name", "trade", "preclose", "tradedate", "volume", "timestamp"]]
    backup_dataframe(futures_realtime, f"期货品种-{symbol}-交易合约实时数据-futures_zh_realtime-{today}.csv")
    if not futures_realtime.empty:
        return float(futures_realtime.iloc[0]["trade"])
    return None


def get_spot_price():
    symbol = "sh000905"
    df = get_price(symbol, frequency='1m', count=1)
    today = datetime.today().strftime("%y%m%d")
    df["timestamp"] = pd.Timestamp.now()
    backup_dataframe(df, f"中证指数-{symbol}-实时行情-Ashare-{today}.csv")
    if not df.empty:
        return float(df.iloc[0]["close"])
    return None


def get_third_friday(year, month):
    """返回给定年月的第三个星期五日期（datetime.date）。"""
    c = calendar.monthcalendar(year, month)
    # 第三周周五，如果为0就去第四周
    third_friday = c[2][calendar.FRIDAY]
    if third_friday == 0:
        third_friday = c[3][calendar.FRIDAY]
    return datetime(year, month, third_friday).date()


def get_last_trading_day(year, month):
    """计算合约到期月份的最后交易日（第三个周五，遇法定节假日顺延）。"""
    d = get_third_friday(year, month)
    while True:
        # 如果是法定假日或周末（非工作日），就往后推一天
        if is_workday(d):
            return d
        d += timedelta(days=1)


# 运行监控
if __name__ == "__main__":

    print("\n启动实时监控 (Ctrl+C 停止)")
    try:
        monitor_all_basis(interval=60 * 30)  # 每半小时刷新一次
    except KeyboardInterrupt:
        print("\n监控停止")
