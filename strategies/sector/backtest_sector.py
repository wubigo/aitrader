"""
A股主线识别策略回测脚本
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def download_stock_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """从AKShare下载股票数据"""
    logger.info(f"下载 {symbol} 数据...")
    
    df = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="qfq"
    )
    
    df["开盘"] = df["开盘"].astype(float)
    df["最高"] = df["最高"].astype(float)
    df["最低"] = df["最低"].astype(float)
    df["收盘"] = df["收盘"].astype(float)
    df["成交量"] = df["成交量"].astype(float)
    
    return df


def import_to_vnpy(df: pd.DataFrame, symbol: str, exchange: Exchange):
    """导入数据到vn.py"""
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
    
    database.save_bar_data(bars)
    logger.info(f"入库完成: {symbol}, 共 {len(bars)} 条")


def run_sector_backtest(
    strategy_class,
    symbol: str,
    exchange: Exchange,
    start: datetime,
    end: datetime,
    initial_capital: float = 100000.0,
):
    """运行主线策略回测"""
    
    engine = BacktestingEngine()
    
    engine.set_parameters(
        vt_symbol=f"{symbol}.{exchange.value}",
        interval=Interval.DAILY,
        start=start,
        end=end,
        rate=0.0003,
        slippage=0.01,
        size=1,
        pricetick=0.01,
        capital=initial_capital,
        mode=BacktestingMode.BAR,
    )
    
    # 策略参数
    setting = {
        "sector_count": 3,
        "ranking_period": 20,
        "price_weight": 0.5,
        "volume_weight": 0.3,
        "trend_weight": 0.2,
        "max_holdings": 2,
        "fixed_capital": 30000,
        "stop_loss_pct": 0.08,
        "take_profit_pct": 0.15,
        "rebalance_days": 5,
    }
    
    engine.add_strategy(strategy_class, setting)
    
    logger.info("加载数据...")
    engine.load_data()
    
    logger.info("运行回测...")
    engine.run_backtesting()
    
    df = engine.calculate_result()
    statistics = engine.calculate_statistics()
    
    logger.info("\n" + "=" * 50)
    logger.info("回测结果")
    logger.info("=" * 50)
    for key, value in statistics.items():
        if value is not None:
            logger.info(f"{key}: {value}")
    
    try:
        engine.show_chart()
    except Exception as e:
        logger.warning(f"无法显示图表: {e}")
    
    return engine, df, statistics


def batch_sector_backtest(
    strategy_class,
    symbols: list,
    exchange: Exchange,
    start: datetime,
    end: datetime,
):
    """
    批量回测多个行业代表股
    模拟行业轮动策略
    """
    results = []
    
    for symbol in symbols:
        logger.info(f"\n{'='*50}")
        logger.info(f"回测 {symbol}")
        logger.info(f"{'='*50}")
        
        try:
            engine, df, stats = run_sector_backtest(
                strategy_class,
                symbol,
                exchange,
                start,
                end,
            )
            
            results.append({
                "symbol": symbol,
                "total_return": stats.get("total_return", 0),
                "sharpe_ratio": stats.get("sharpe_ratio", 0),
                "max_drawdown": stats.get("max_drawdown", 0),
                "trade_count": stats.get("total_trade_count", 0),
            })
        except Exception as e:
            logger.error(f"回测 {symbol} 失败: {e}")
            continue
    
    # 汇总结果
    logger.info("\n" + "=" * 60)
    logger.info("批量回测汇总")
    logger.info("=" * 60)
    
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("total_return", ascending=False)
    
    print(results_df.to_string(index=False))
    
    # 保存结果
    results_df.to_csv("../data/sector_backtest_results.csv", index=False, encoding="utf-8-sig")
    logger.info("\n结果已保存到 data/sector_backtest_results.csv")
    
    return results_df


if __name__ == "__main__":
    from sector_rotation_strategy import SectorRotationStrategy
    
    # 配置
    SYMBOL = "000001"  # 平安银行
    EXCHANGE = Exchange.SZSE
    START_DATE = "20230101"
    END_DATE = "20241231"
    
    # 下载数据
    df = download_stock_data(SYMBOL, START_DATE, END_DATE)
    import_to_vnpy(df, SYMBOL, EXCHANGE)
    
    # 运行回测
    engine, result_df, stats = run_sector_backtest(
        strategy_class=SectorRotationStrategy,
        symbol=SYMBOL,
        exchange=EXCHANGE,
        start=datetime(2023, 1, 1),
        end=datetime(2024, 12, 31),
        initial_capital=100000.0,
    )
    
    # 批量回测示例（多个行业代表股）
    # sector_leaders = ["000001", "600519", "300750", "600276", "000938"]
    # batch_sector_backtest(
    #     SectorRotationStrategy,
    #     sector_leaders,
    #     Exchange.SZSE,
    #     datetime(2023, 1, 1),
    #     datetime(2024, 12, 31),
    # )
