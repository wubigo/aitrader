"""
主线识别策略回测 - 完整流程

回测流程：
1. 使用AKShare获取行业指数和个股数据
2. 导入到vn.py数据库
3. 运行主线策略回测
4. 输出回测结果和图表
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

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mainline_data_feed import MainlineDataFeed
from mainline_strategy import MainlineStrategy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def download_and_import_data(
    symbol: str,
    exchange: Exchange,
    start_date: str,
    end_date: str,
    is_index: bool = False,
) -> bool:
    """
    下载数据并导入vn.py
    
    :param symbol: 代码（股票或指数）
    :param exchange: 交易所
    :param start_date: 开始日期 "20230101"
    :param end_date: 结束日期 "20241231"
    :param is_index: 是否为指数
    :return: 是否成功
    """
    from datetime import timezone, timedelta
    
    logger.info(f"下载 {'指数' if is_index else '股票'} {symbol} 数据...")
    
    try:
        if is_index:
            # 下载指数数据
            df = ak.index_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
            )
        else:
            # 下载股票数据
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"
            )
        
        if df.empty:
            logger.warning(f"{symbol} 数据为空")
            return False
        
        # 标准化列名
        df.columns = [c.lower() for c in df.columns]
        
        # 转换为vn.py BarData
        utc_8 = timezone(timedelta(hours=8))
        database = get_database()
        
        bars = []
        for _, row in df.iterrows():
            dt = pd.to_datetime(row["date"])
            if getattr(dt, "tz", None) is None:
                dt = dt.tz_localize(utc_8)
            dt = dt.to_pydatetime()
            
            bar = BarData(
                symbol=symbol,
                exchange=exchange,
                datetime=dt,
                interval=Interval.DAILY,
                volume=float(row.get("volume", 0)),
                open_price=float(row["open"]),
                high_price=float(row["high"]),
                low_price=float(row["low"]),
                close_price=float(row["close"]),
                open_interest=0,
                gateway_name="AKSHARE",
            )
            bars.append(bar)
        
        database.save_bar_data(bars)
        logger.info(f"导入完成: {symbol}, 共 {len(bars)} 条")
        return True
        
    except Exception as e:
        logger.error(f"下载/导入 {symbol} 失败: {e}")
        return False


def prepare_backtest_data(
    sectors_config: dict,
    start_date: str,
    end_date: str,
):
    """
    准备回测数据
    
    下载所有行业指数和成分股数据
    """
    logger.info("=" * 60)
    logger.info("准备回测数据")
    logger.info("=" * 60)
    
    # 下载行业指数数据
    for sector_name, config in sectors_config.items():
        index_code = config.get("index_code")
        if index_code:
            download_and_import_data(
                symbol=index_code,
                exchange=Exchange.SSE,  # 指数用SSE
                start_date=start_date,
                end_date=end_date,
                is_index=True,
            )
    
    # 下载个股数据
    for sector_name, config in sectors_config.items():
        for symbol in config.get("stocks", []):
            # 判断交易所
            exchange = Exchange.SZSE if symbol.startswith(("0", "3")) else Exchange.SSE
            
            download_and_import_data(
                symbol=symbol,
                exchange=exchange,
                start_date=start_date,
                end_date=end_date,
                is_index=False,
            )


def run_mainline_backtest(
    symbol: str,
    exchange: Exchange,
    start: datetime,
    end: datetime,
    initial_capital: float = 100000.0,
):
    """
    运行主线策略回测
    
    :param symbol: 回测标的（个股代码）
    :param exchange: 交易所
    :param start: 开始时间
    :param end: 结束时间
    :param initial_capital: 初始资金
    """
    engine = BacktestingEngine()
    
    engine.set_parameters(
        vt_symbol=f"{symbol}.{exchange.value}",
        interval=Interval.DAILY,
        start=start,
        end=end,
        rate=0.0003,           # 手续费万3
        slippage=0.01,         # 滑点
        size=1,
        pricetick=0.01,
        capital=initial_capital,
        mode=BacktestingMode.BAR,
    )
    
    # 策略参数
    setting = {
        # 行业筛选
        "sector_scan_interval": 5,
        "top_n_sectors": 3,
        "sector_momentum_weight": 0.4,
        "sector_volume_weight": 0.3,
        "sector_fund_flow_weight": 0.3,
        # 个股筛选
        "stocks_per_sector": 2,
        "stock_momentum_weight": 0.4,
        "stock_volume_weight": 0.2,
        "stock_consistency_weight": 0.2,
        "stock_market_cap_weight": 0.2,
        # 交易参数
        "rebalance_days": 5,
        "max_holdings": 6,
        "position_pct_per_stock": 0.15,
        "stop_loss_pct": 0.07,
        "take_profit_pct": 0.20,
        "trailing_stop_pct": 0.10,
    }
    
    engine.add_strategy(MainlineStrategy, setting)
    
    
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
    
    # 保存回测日志到文件
    log_filename = f"../../data/backtest_log_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(log_filename, "w", encoding="utf-8") as f:
        f.write(f"Backtest Log for {symbol}\n")
        f.write(f"Start: {start}\n")
        f.write(f"End: {end}\n")
        f.write("=" * 60 + "\n\n")
        for log in engine.logs:
            f.write(log + "\n")
        f.write("\n" + "=" * 60 + "\n")
        f.write("Statistics:\n")
        for key, value in statistics.items():
            if value is not None:
                f.write(f"{key}: {value}\n")
    
    logger.info(f"回测日志已保存到: {log_filename}")
    
    # 显示图表
    try:
        engine.show_chart()
    except Exception as e:
        logger.warning(f"无法显示图表: {e}")
    
    return engine, df, statistics


def batch_backtest_stocks(
    stocks: list[tuple[str, Exchange]],
    start: datetime,
    end: datetime,
    initial_capital: float = 100000.0,
) -> pd.DataFrame:
    """
    批量回测多只股票
    
    模拟主线策略在多个候选股票上的表现
    """
    results = []
    
    for symbol, exchange in stocks:
        logger.info(f"\n{'='*60}")
        logger.info(f"回测 {symbol}")
        logger.info(f"{'='*60}")
        
        try:
            engine, df, stats = run_mainline_backtest(
                symbol=symbol,
                exchange=exchange,
                start=start,
                end=end,
                initial_capital=initial_capital,
            )
            
            results.append({
                "symbol": symbol,
                "total_return": stats.get("total_return", 0),
                "sharpe_ratio": stats.get("sharpe_ratio", 0),
                "max_drawdown": stats.get("max_drawdown", 0),
                "win_rate": stats.get("win_rate", 0),
                "trade_count": stats.get("total_trade_count", 0),
            })
        except Exception as e:
            logger.error(f"回测 {symbol} 失败: {e}")
            continue
    
    # 汇总
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("total_return", ascending=False)
    
    logger.info("\n" + "=" * 60)
    logger.info("批量回测汇总")
    logger.info("=" * 60)
    print(results_df.to_string(index=False))
    
    # 保存
    output_file = "../../data/mainline_backtest_results.csv"
    results_df.to_csv(output_file, index=False, encoding="utf-8-sig")
    logger.info(f"\n结果已保存到: {output_file}")
    
    return results_df


if __name__ == "__main__":
    # 行业配置
    SECTORS_CONFIG = {
        "半导体": {
            "index_code": "H30184",
            "stocks": ["688981", "603501", "002371"],
        },
        "新能源": {
            "index_code": "399808",
            "stocks": ["300750", "002594", "601012"],
        },
        "白酒": {
            "index_code": "399997",
            "stocks": ["600519", "000858", "000568"],
        },
        "医药": {
            "index_code": "399933",
            "stocks": ["600276", "000661", "300760"],
        },
    }
    
    START_DATE = "20230101"
    END_DATE = "20241231"
    
    # 步骤1: 准备数据（可选，如果已有数据可跳过）
    # prepare_backtest_data(SECTORS_CONFIG, START_DATE, END_DATE)
    
    # 步骤2: 单股票回测
    SYMBOL = "000001"  # 平安银行
    EXCHANGE = Exchange.SZSE
    
    engine, result_df, stats = run_mainline_backtest(
        symbol=SYMBOL,
        exchange=EXCHANGE,
        start=datetime(2023, 1, 1),
        end=datetime(2024, 12, 31),
        initial_capital=100000.0,
    )
    
    # 步骤3: 批量回测（可选）
    # test_stocks = [
    #     ("000001", Exchange.SZSE),
    #     ("600519", Exchange.SSE),
    #     ("300750", Exchange.SZSE),
    # ]
    # batch_backtest_stocks(test_stocks, datetime(2023, 1, 1), datetime(2024, 12, 31))
