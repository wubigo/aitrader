import akshare as ak
from datetime import datetime
import pandas as pd
import backtest_logger
from utils.backtest_logger import backup_dataframe
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

# df = ak.futures_symbol_mark()
# backup_dataframe(df, "期货品种命名表-sina-2025.csv")

#期货品种当前时刻所有可交易的合约实时数据
# symbol = "中证500指数期货"
# futures_realtime = ak.futures_zh_realtime(symbol)
# # futures_realtime.rename(columns={'preclose': '前收盘价'}, inplace=True)
# # futures_realtime.rename(columns={'trade': '最新价'}, inplace=True)
# today = datetime.today().strftime("%y%m%d")
# futures_realtime["timestamp"] = pd.Timestamp.now()
# backup_dataframe(futures_realtime.sort_values("symbol")[["symbol", "name", "trade", "preclose", "tradedate", "timestamp"]], f"期货品种-{symbol}-交易合约实时数据-futures_zh_realtime-{today}.csv")

# futures_zh_minute_sina_df = ak.futures_zh_minute_sina(symbol="IC0", period="1")
# backup_dataframe(futures_zh_minute_sina_df, f"期货交易分时数据-futures_zh_minute_sina-{timestamp}.csv")


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


df = ak.futures_contract_detail("IC2606")
print(df)
df = ak.futures_contract_detail_em("IC2606")
print(df)
# get_main_contract_expiry("IC")