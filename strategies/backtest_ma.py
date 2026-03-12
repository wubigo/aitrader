"""
双均线策略回测脚本 - 使用 vn.py CtaBacktester
"""
from vnpy_ctastrategy.backtesting import BacktestingEngine
from vnpy.trader.constant import Interval, Exchange
from datetime import datetime
import akshare as ak
import pandas as pd
from vnpy.trader.database import get_database
from vnpy.trader.object import BarData
import logging

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def download_data_from_akshare(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    从 AKShare 下载股票历史数据
    
    :param symbol: 股票代码，如 "000001"
    :param start_date: 开始日期，如 "20200101"
    :param end_date: 结束日期，如 "20241231"
    :return: DataFrame
    """
    logger.info(f"正在从 AKShare 下载 {symbol} 数据...")
    
    df = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="qfq"  # 前复权
    )
    
    # 数据类型转换
    df["开盘"] = df["开盘"].astype(float)
    df["最高"] = df["最高"].astype(float)
    df["最低"] = df["最低"].astype(float)
    df["收盘"] = df["收盘"].astype(float)
    df["成交量"] = df["成交量"].astype(float)
    
    logger.info(f"下载完成，共 {len(df)} 条数据")
    return df


def import_data_to_vnpy(df: pd.DataFrame, symbol: str, exchange: Exchange):
    """
    将 DataFrame 数据导入 vn.py 数据库
    
    :param df: AKShare 数据
    :param symbol: 股票代码
    :param exchange: 交易所
    """
    from datetime import timezone, timedelta
    
    utc_8 = timezone(timedelta(hours=8))
    database = get_database()
    
    bars = []
    for _, row in df.iterrows():
        dt = pd.to_datetime(row["日期"])
        if getattr(dt, "tz", None) is None:
            dt = dt.tz_localize(utc_8)
        dt = dt.to_pydatetime()
        
        bar = BarData(
            symbol=symbol,
            exchange=exchange,
            datetime=dt,
            interval=Interval.DAILY,
            volume=float(row["成交量"]),
            open_price=float(row["开盘"]),
            high_price=float(row["最高"]),
            low_price=float(row["最低"]),
            close_price=float(row["收盘"]),
            open_interest=0,
            gateway_name="AKSHARE",
        )
        bars.append(bar)
    
    # 入库
    database.save_bar_data(bars)
    logger.info(f"数据入库完成: {symbol}, 共 {len(bars)} 条")


def run_backtest(
    strategy_class,
    symbol: str = "000001",
    exchange: Exchange = Exchange.SZSE,
    start: datetime = None,
    end: datetime = None,
    initial_capital: float = 100000.0,
    fast_window: int = 10,
    slow_window: int = 20,
):
    """
    运行回测
    
    :param strategy_class: 策略类
    :param symbol: 股票代码
    :param exchange: 交易所
    :param start: 回测开始时间
    :param end: 回测结束时间
    :param initial_capital: 初始资金
    :param fast_window: 快线周期
    :param slow_window: 慢线周期
    """
    # 默认时间范围
    if start is None:
        start = datetime(2020, 1, 1)
    if end is None:
        end = datetime(2024, 12, 31)
    
    # 创建回测引擎
    engine = BacktestingEngine()
    
    # 设置回测参数
    engine.set_parameters(
        vt_symbol=f"{symbol}.{exchange.value}",
        interval=Interval.DAILY,
        start=start,
        end=end,
        rate=0.0003,           # 手续费率 万3
        slippage=0.01,         # 滑点
        size=1,                # 合约乘数（股票为1）
        pricetick=0.01,        # 最小价格变动
        capital=initial_capital,
    )
    
    # 添加策略
    setting = {
        "fast_window": fast_window,
        "slow_window": slow_window,
        "fixed_size": 100,    # 每次交易100股
    }
    engine.add_strategy(strategy_class, setting)
    
    # 加载数据
    logger.info("正在加载数据...")
    engine.load_data()
    
    # 运行回测
    logger.info("开始回测...")
    engine.run_backtesting()
    
    # 计算结果
    df = engine.calculate_result()
    
    # 统计指标
    statistics = engine.calculate_statistics()
    
    # 打印统计结果
    logger.info("=" * 50)
    logger.info("回测结果统计")
    logger.info("=" * 50)
    for key, value in statistics.items():
        if value is not None:
            logger.info(f"{key}: {value}")
    
    # 显示图表（如果在 Jupyter 中运行）
    try:
        engine.show_chart()
    except Exception as e:
        logger.warning(f"无法显示图表: {e}")
    
    return engine, df, statistics


if __name__ == "__main__":
    # 导入策略
    from ma_strategy import DoubleMaStrategy
    
    # 参数配置
    SYMBOL = "000001"           # 平安银行
    EXCHANGE = Exchange.SZSE    # 深交所
    START_DATE = "20200101"
    END_DATE = "20241231"
    
    # 步骤1: 下载数据（可选，如果数据库中已有数据可跳过）
    df = download_data_from_akshare(SYMBOL, START_DATE, END_DATE)
    
    # 步骤2: 导入数据到 vn.py
    import_data_to_vnpy(df, SYMBOL, EXCHANGE)
    
    # 步骤3: 运行回测
    engine, result_df, stats = run_backtest(
        strategy_class=DoubleMaStrategy,
        symbol=SYMBOL,
        exchange=EXCHANGE,
        start=datetime(2020, 1, 1),
        end=datetime(2024, 12, 31),
        initial_capital=100000.0,
        fast_window=10,
        slow_window=20,
    )
