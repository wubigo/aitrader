import logging

import requests
import json
import pandas as pd
from datetime import datetime, timedelta
import time
import warnings
warnings.filterwarnings('ignore')

# 合约配置：secid 格式 (期货用 0.代码, 指数用 1.代码)
CONTRACTS = {
    'IC': {'fut_secid': '0.159919', 'spot_code': '000905', 'name': '中证500', 'expiry': '20260620'},  # 改成实际交割日
    'IM': {'fut_secid': '0.150130', 'spot_code': '000852', 'name': '中证1000', 'expiry': '20260620'},
    'IF': {'fut_secid': '0.159915', 'spot_code': '000300', 'name': '沪深300', 'expiry': '20260620'},
    'IH': {'fut_secid': '0.159916', 'spot_code': '000016', 'name': '上证50', 'expiry': '20260620'}
}

def get_price(secid):
    """获取东方财富实时价格"""
    url = f"https://push2.eastmoney.com/api/qt/stock/trends2/get?secid={secid}&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13,f14,f15&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&ndays=1"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get('data') and data['data'].get('trends'):
            latest = data['data']['trends'][0].split(',')
            return float(latest[1])  # 最新成交价
    except:
        logging.exception(f"get_price")
    return None

def get_remaining_days(expiry_str):
    """计算剩余天数"""
    expiry_date = datetime.strptime(expiry_str, "%Y%m%d")
    today = datetime.now()
    return max((expiry_date - today).days, 1)  # 避免除零

def calc_annualized_basis(fut_price, spot_price, days):
    """计算年化贴水率"""
    if fut_price is None or spot_price is None or days <= 0:
        return None
    basis_ratio = (spot_price - fut_price) / spot_price
    annualized = basis_ratio * 365 / days * 100
    return annualized

def monitor_all_basis(interval=60):
    """监控所有股指年化贴水"""
    print("🚀 股指期货年化贴水实时监控启动 (每{}s刷新)".format(interval))
    print("=" * 80)
    
    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{now}] 更新数据...")
        
        results = {}
        for code, info in CONTRACTS.items():
            fut_price = get_price(info['fut_secid'])
            spot_price = get_price(f"1.{info['spot_code']}")
            days = get_remaining_days(info['expiry'])
            
            ann_basis = calc_annualized_basis(fut_price, spot_price, days)
            
            status = ""
            if ann_basis:
                if ann_basis > 8:
                    status = "🚨 厚贴水-建仓!"
                elif ann_basis > 6:
                    status = "📊 中等-观察"
                elif ann_basis > 3:
                    status = "✅ 轻微贴水"
                else:
                    status = "➡️ 基本平水"
            
            results[code] = {
                '期货价': fut_price,
                '现货价': spot_price,
                '贴水点数': spot_price - fut_price if spot_price and fut_price else None,
                '年化贴水%': ann_basis,
                '剩余天数': days,
                '状态': status
            }
            
            print(f"{code}: 年化贴水 {ann_basis:.2f}% {status} | 期货:{fut_price:.2f} 现货:{spot_price:.2f}")
        
        # 保存到CSV（可选）
        df = pd.DataFrame(results).T
        df.to_csv(f"basis_monitor_{datetime.now().strftime('%Y%m%d')}.csv")
        
        time.sleep(interval)

def get_future_price():
    symbol = "中证500指数期货"
    futures_realtime = ak.futures_zh_realtime(symbol)
    # futures_realtime.rename(columns={'preclose': '前收盘价'}, inplace=True)
    # futures_realtime.rename(columns={'trade': '最新价'}, inplace=True)
    today = datetime.today().strftime("%y%m%d")
    futures_realtime["timestamp"] = pd.Timestamp.now()
    futures_realtime = futures_realtime.sort_values("symbol")
    backup_dataframe(futures_realtime, f"期货品种-{symbol}-交易合约实时数据-futures_zh_realtime-{today}.csv")
    if not futures_realtime.empty:
        return futures_realtime.head["trade"]
    return ""

def get_spot_price():



# 运行监控
if __name__ == "__main__":
    # 先测试单次运行
    print("测试单次抓取...")
    for code in ['IC', 'IM']:
        info = CONTRACTS[code]
        fut = get_price(info['fut_secid'])
        spot = get_price(f"1.{info['spot_code']}")
        print(f"{code}: 期货 {fut}, 现货 {spot}")
    
    print("\n启动实时监控 (Ctrl+C 停止)")
    try:
        monitor_all_basis(interval=60*30)  # 每60秒刷新一次
    except KeyboardInterrupt:
        print("\n监控停止")