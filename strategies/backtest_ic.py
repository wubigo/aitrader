"""
IC 股指期货滚贴水套利策略回测脚本

回测流程：
1. 从 AKShare 获取 IC 期货历史数据
2. 获取对应的现货数据（500ETF）
3. 导入到 vn.py 数据库
4. 运行回测并输出结果
"""
from vnpy_ctastrategy.backtesting import BacktestingEngine
from vnpy_ctastrategy.base import BacktestingMode
from vnpy.trader.constant import Interval, Exchange
from datetime import datetime
import akshare as ak
import pandas as pd
from vnpy.trader.database import get_database
from vnpy.trader.object import BarData
import logging
import sys
import os

# 添加路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ic_backwater_strategy import ICBackwaterArbitrageStrategy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def download_ic_data(symbol: str = "IC0", start_date: str = "20230101", end_date: str = "20241231") -> pd.DataFrame:
    """
    下载 IC 期货主力合约连续数据
    
    :param symbol: "IC0" - 主力合约连续，"IC1" - 次主力合约连续
    :param start_date: 开始日期
    :param end_date: 结束日期
    """
    logger.info(f"下载 IC 期货数据 {symbol}...")
    
    try:
        df = ak.futures_main_sina(
            symbol=symbol,
            trade_date=start_date,
        )
        
        # 如果是获取历史连续数据，使用不同的接口
        # 这里简化处理，实际需要调用正确的接口
        
        if df.empty:
            logger.warning("获取数据为空")
            return pd.DataFrame()
        
        return df
        
    except Exception as e:
        logger.exception(f"下载失败：{e}")
        return pd.DataFrame()


def download_500etf_data(start_date: str, end_date: str) -> pd.DataFrame:
    """
    下载 500ETF 数据作为现货代理
    
    :param start_date: 开始日期
    :param end_date: 结束日期
    """
    logger.info("下载 500ETF 数据...")
    
    try:
        df = ak.etf_hist_em(
            symbol="sh510500",
            period="daily",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust="qfq"
        )
        
        if df.empty:
            return pd.DataFrame()
        
        return df
        
    except Exception as e:
        logger.exception(f"下载 ETF 数据失败：{e}")
        return pd.DataFrame()


def import_to_vnpy(df: pd.DataFrame, symbol: str, exchange: Exchange):
    """导入数据到 vn.py"""
    from datetime import timezone, timedelta
    
    utc_8 = timezone(timedelta(hours=8))
    database = get_database()
    
    bars = []
    for _, row in df.iterrows():
        dt = pd.to_datetime(row.get('date', row.get('交易日', row.index[0])))
        if getattr(dt, "tz", None) is None:
            dt = dt.tz_localize(utc_8)
        dt = dt.to_pydatetime()
        
        # 根据实际列名调整
        bar = BarData(
            symbol=symbol,
            exchange=exchange,
            datetime=dt,
            interval=Interval.DAILY,
            volume=float(row.get('volume', row.get('成交量', 0))),
            open_price=float(row.get('open', row.get('开盘', 0))),
            high_price=float(row.get('high', row.get('最高', 0))),
            low_price=float(row.get('low', row.get('最低', 0))),
            close_price=float(row.get('close', row.get('收盘', 0))),
            open_interest=0,
            gateway_name="AKSHARE",
        )
        bars.append(bar)
    
    database.save_bar_data(bars)
    logger.info(f"入库完成：{symbol}, 共 {len(bars)} 条")


def run_backtest(
    symbol: str = "IC2406.SFF",
    start: datetime = None,
    end: datetime = None,
    initial_capital: float = 1000000.0,
):
    """
    运行回测
    
    :param symbol: 合约代码，如 "IC2406.SFF"
    :param start: 开始时间
    :param end: 结束时间
    :param initial_capital: 初始资金
    """
    if start is None:
        start = datetime(2023, 1, 1)
    if end is None:
        end = datetime(2024, 12, 31)
    
    engine = BacktestingEngine()
    
    engine.set_parameters(
        vt_symbol=symbol,
        interval=Interval.DAILY,
        start=start,
        end=end,
        rate=0.000023,       # 期货手续费万分之 0.23
        slippage=0.2,        # 滑点 0.2 点
        size=200,            # IC 合约乘数 200 元/点
        pricetick=0.2,       # 最小变动价位 0.2 点
        capital=initial_capital,
        mode=BacktestingMode.BAR,
    )
    
    # 策略参数
    setting = {
        "spot_symbol": "510500.SSE",
        "futures_symbol": "IC.SFF",
        "open_basis_threshold": -0.02,      # -2% 贴水开仓
        "min_open_volume": 1,
        "close_basis_threshold": -0.005,    # -0.5% 平仓
        "max_holding_days": 20,
        "stop_loss_pct": 0.03,              # 3% 止损
        "roll_days_before_expiry": 5,
        "roll_spread_threshold": 0.005,     # 0.5% 滚动阈值
        "position_ratio": 0.8,
        "cash_reserve": 0.2,
    }
    
    engine.add_strategy(ICBackwaterArbitrageStrategy, setting)
    
    logger.info("加载数据...")
    engine.load_data()
    
    logger.info("运行回测...")
    engine.run_backtesting()
    
    # 计算结果
    df = engine.calculate_result()
    statistics = engine.calculate_statistics()
    
    # 输出结果
    logger.info("\n" + "=" * 60)
    logger.info("回测结果")
    logger.info("=" * 60)
    for key, value in statistics.items():
        if value is not None:
            logger.info(f"{key}: {value}")
    
    # 保存日志
    log_filename = f"../../data/ic_backtest_log_{symbol.replace('.', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(log_filename, "w", encoding="utf-8") as f:
        f.write(f"IC 滚贴水套利回测报告\n")
        f.write(f"标的：{symbol}\n")
        f.write(f"期间：{start.date()} ~ {end.date()}\n")
        f.write("=" * 60 + "\n\n")
        for log in engine.logs:
            f.write(log + "\n")
        f.write("\n" + "=" * 60 + "\n")
        f.write("统计指标:\n")
        for key, value in statistics.items():
            if value is not None:
                f.write(f"{key}: {value}\n")
    
    logger.info(f"回测日志已保存到：{log_filename}")
    
    # 显示图表
    try:
        engine.show_chart()
    except Exception as e:
        logger.warning(f"无法显示图表：{e}")
    
    return engine, df, statistics


if __name__ == "__main__":
    # 配置
    SYMBOL = "IC2406.SFF"
    START_DATE = "20230101"
    END_DATE = "20241231"
    
    # 方式 1: 直接回测（如果数据已在数据库中）
    engine, result_df, stats = run_backtest(
        symbol=SYMBOL,
        start=datetime(2023, 1, 1),
        end=datetime(2024, 12, 31),
        initial_capital=1000000.0,
    )
    
    # 方式 2: 先下载数据再回测
    # df_futures = download_ic_data("IC0", START_DATE, END_DATE)
    # if not df_futures.empty:
    #     import_to_vnpy(df_futures, "IC2406", Exchange.CFFEX)
    #     
    #     df_etf = download_500etf_data(START_DATE, END_DATE)
    #     if not df_etf.empty:
    #         import_to_vnpy(df_etf, "510500", Exchange.SSE)
