import akshare as ak
from datetime import datetime
import pandas as pd
import backtest_logger
from utils.backtest_logger import backup_dataframe
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

# df = ak.futures_symbol_mark()
# backup_dataframe(df, "期货品种命名表-sina-2025.csv")

#期货品种当前时刻所有可交易的合约实时数据
symbol = "中证500指数期货"
futures_realtime = ak.futures_zh_realtime(symbol)
# futures_realtime.rename(columns={'preclose': '前收盘价'}, inplace=True)
# futures_realtime.rename(columns={'trade': '最新价'}, inplace=True)
today = datetime.today().strftime("%y%m%d")
futures_realtime["timestamp"] = pd.Timestamp.now()
backup_dataframe(futures_realtime.sort_values("symbol")[["symbol", "name", "trade", "preclose", "tradedate", "timestamp"]], f"期货品种-{symbol}-交易合约实时数据-futures_zh_realtime-{today}.csv")

# futures_zh_minute_sina_df = ak.futures_zh_minute_sina(symbol="IC0", period="1")
# backup_dataframe(futures_zh_minute_sina_df, f"期货交易分时数据-futures_zh_minute_sina-{timestamp}.csv")
