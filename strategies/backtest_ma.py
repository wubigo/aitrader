"""
双均线策略回测脚本 - 使用 vn.py CtaBacktester
支持参数优化功能
"""
from vnpy_ctastrategy.backtesting import BacktestingEngine
from vnpy_ctastrategy.base import BacktestingMode
from vnpy.trader.constant import Interval, Exchange
from datetime import datetime
from itertools import product
import akshare as ak
import pandas as pd
from vnpy.trader.database import get_database
from vnpy.trader.object import BarData
import logging

# 引入通用回测日志工具
from utils.backtest_logger import save_backtest_log, save_optimization_log

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


def run_single_backtest(
    strategy_class,
    symbol: str = "000001",
    exchange: Exchange = Exchange.SZSE,
    start: datetime = None,
    end: datetime = None,
    initial_capital: float = 100000.0,
    fast_window: int = 10,
    slow_window: int = 20,
    fixed_size: int = 100,
    # 过滤参数
    use_volume_filter: bool = True,
    volume_ratio: float = 1.2,
    use_volatility_filter: bool = True,
    atr_threshold: float = 0.5,
    use_trend_filter: bool = False,
    adx_threshold: float = 25,
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
        "fixed_size": fixed_size,
        "use_volume_filter": use_volume_filter,
        "volume_ratio": volume_ratio,
        "use_volatility_filter": use_volatility_filter,
        "atr_threshold": atr_threshold,
        "use_trend_filter": use_trend_filter,
        "adx_threshold": adx_threshold,
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
        logger.warning(f"无法显示图表：{e}")
        
    # 保存回测日志（使用通用工具）
    log_file = save_backtest_log(
        logs=engine.logs,
        statistics=statistics,
        symbol=symbol,
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        strategy_name="双均线策略",
    )
    logger.info(f"回测日志已保存到：{log_file}")
        
    return engine, df, statistics


def run_parameter_optimization(
    strategy_class,
    symbol: str = "000001",
    exchange: Exchange = Exchange.SZSE,
    start: datetime = None,
    end: datetime = None,
    initial_capital: float = 100000.0,
    fast_window_range: range = range(5, 31, 5),
    slow_window_range: range = range(10, 61, 10),
    fixed_size: int = 100,
    target_metric: str = "sharpe_ratio",
    # 过滤参数优化范围
    optimize_volume_filter: bool = False,
    volume_ratio_range: list = [1.0, 1.2, 1.5],
    optimize_volatility_filter: bool = False,
    atr_threshold_range: list = [0.3, 0.5, 0.8],
):
    """
    参数优化 - 网格搜索最佳参数组合
    
    :param strategy_class: 策略类
    :param symbol: 股票代码
    :param exchange: 交易所
    :param start: 回测开始时间
    :param end: 回测结束时间
    :param initial_capital: 初始资金
    :param fast_window_range: 快线周期范围
    :param slow_window_range: 慢线周期范围
    :param fixed_size: 每次交易股数
    :param target_metric: 优化目标指标 (sharpe_ratio, total_return, max_drawdown, win_rate)
    :return: 最佳参数组合和结果列表
    """
    # 默认时间范围
    if start is None:
        start = datetime(2020, 1, 1)
    if end is None:
        end = datetime(2024, 12, 31)
    
    logger.info("=" * 60)
    logger.info("开始参数优化")
    logger.info(f"快线范围: {list(fast_window_range)}")
    logger.info(f"慢线范围: {list(slow_window_range)}")
    if optimize_volume_filter:
        logger.info(f"成交量倍数范围: {volume_ratio_range}")
    if optimize_volatility_filter:
        logger.info(f"ATR阈值范围: {atr_threshold_range}")
    logger.info(f"优化目标: {target_metric}")
    logger.info("=" * 60)
    
    results = []
    
    # 构建参数组合
    param_combinations = []
    for fast, slow in product(fast_window_range, slow_window_range):
        if fast >= slow:
            continue
        
        # 基础参数组合
        base_params = {"fast_window": fast, "slow_window": slow}
        
        # 如果不优化过滤参数，直接添加
        if not optimize_volume_filter and not optimize_volatility_filter:
            param_combinations.append(base_params)
        else:
            # 添加过滤参数组合
            vol_ratios = volume_ratio_range if optimize_volume_filter else [1.2]
            atr_thresholds = atr_threshold_range if optimize_volatility_filter else [0.5]
            
            for vol_ratio in vol_ratios:
                for atr_thresh in atr_thresholds:
                    params = base_params.copy()
                    params["volume_ratio"] = vol_ratio
                    params["atr_threshold"] = atr_thresh
                    param_combinations.append(params)
    
    total_combinations = len(param_combinations)
    logger.info(f"总共 {total_combinations} 组参数需要测试\n")
    
    # 遍历所有参数组合
    for idx, params in enumerate(param_combinations, 1):
        fast = params["fast_window"]
        slow = params["slow_window"]
        vol_ratio = params.get("volume_ratio", 1.2)
        atr_thresh = params.get("atr_threshold", 0.5)
        
        param_str = f"快线={fast}, 慢线={slow}"
        if optimize_volume_filter:
            param_str += f", 量倍={vol_ratio}"
        if optimize_volatility_filter:
            param_str += f", ATR={atr_thresh}"
        
        logger.info(f"[{idx}/{total_combinations}] 测试参数: {param_str}")
        
        try:
            # 创建回测引擎
            engine = BacktestingEngine()
            
            # 设置回测参数
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
            
            # 添加策略
            setting = {
                "fast_window": fast,
                "slow_window": slow,
                "fixed_size": fixed_size,
                "use_volume_filter": optimize_volume_filter or True,
                "volume_ratio": vol_ratio,
                "use_volatility_filter": optimize_volatility_filter or True,
                "atr_threshold": atr_thresh,
            }
            engine.add_strategy(strategy_class, setting)
            
            # 加载数据并运行
            engine.load_data()
            engine.run_backtesting()
            
            # 计算结果
            df = engine.calculate_result()
            stats = engine.calculate_statistics()
            
            # 记录结果
            result = {
                "fast_window": fast,
                "slow_window": slow,
                "volume_ratio": vol_ratio,
                "atr_threshold": atr_thresh,
                "total_return": stats.get("total_return", 0),
                "sharpe_ratio": stats.get("sharpe_ratio", 0),
                "max_drawdown": stats.get("max_drawdown", 0),
                "win_rate": stats.get("win_rate", 0),
                "trade_count": stats.get("total_trade_count", 0),
                "daily_return": stats.get("daily_return", 0),
                "return_drawdown_ratio": stats.get("return_drawdown_ratio", 0),
            }
            results.append(result)
            
            logger.info(f"  总收益率: {result['total_return']:.2f}%")
            logger.info(f"  夏普比率: {result['sharpe_ratio']:.2f}")
            logger.info(f"  最大回撤: {result['max_drawdown']:.2f}%")
            logger.info(f"  胜率: {result['win_rate']:.2f}%")
            logger.info(f"  交易次数: {result['trade_count']}")
            
        except Exception as e:
            logger.error(f"参数组合 (fast={fast}, slow={slow}) 运行失败: {e}")
            continue
    
    # 根据目标指标排序
    if target_metric == "max_drawdown":
        # 最大回撤越小越好（取绝对值最小的）
        results.sort(key=lambda x: abs(x[target_metric]))
    else:
        # 其他指标越大越好
        results.sort(key=lambda x: x[target_metric], reverse=True)
    
    # 输出最佳参数
    logger.info("\n" + "=" * 60)
    logger.info("参数优化完成 - TOP 10 结果")
    logger.info("=" * 60)
    
    for i, r in enumerate(results[:10], 1):
        param_info = f"快线={r['fast_window']}, 慢线={r['slow_window']}"
        if optimize_volume_filter:
            param_info += f", 量倍={r['volume_ratio']}"
        if optimize_volatility_filter:
            param_info += f", ATR={r['atr_threshold']}"
        
        logger.info(f"\n第 {i} 名:")
        logger.info(f"  参数: {param_info}")
        logger.info(f"  总收益率: {r['total_return']:.2f}%")
        logger.info(f"  夏普比率: {r['sharpe_ratio']:.2f}")
        logger.info(f"  最大回撤: {r['max_drawdown']:.2f}%")
        logger.info(f"  胜率: {r['win_rate']:.2f}%")
        logger.info(f"  交易次数: {r['trade_count']}")
    
    # 返回最佳参数
    best = results[0] if results else None
    if best:
        best_info = f"快线={best['fast_window']}, 慢线={best['slow_window']}"
        if optimize_volume_filter:
            best_info += f", 量倍={best['volume_ratio']}"
        if optimize_volatility_filter:
            best_info += f", ATR={best['atr_threshold']}"
        logger.info("\n" + "=" * 60)
        logger.info(f"最佳参数组合：{best_info}")
        logger.info("=" * 60)
        
    # 保存优化结果到文件
    if results:
        opt_file = save_optimization_log(
            optimization_results=results,
            symbol=symbol,
            strategy_name="双均线策略",
        )
        logger.info(f"参数优化结果已保存到：{opt_file}")
        
    return best, results


def save_optimization_results(results: list, filename: str = "../data/optimization_results.csv"):
    """保存优化结果到 CSV 文件"""
    df = pd.DataFrame(results)
    df.to_csv(filename, index=False, encoding="utf-8-sig")
    logger.info(f"优化结果已保存到: {filename}")


if __name__ == "__main__":
    # 导入策略
    from ma_strategy import DoubleMaStrategy
    
    # 参数配置
    SYMBOL = "000001"           # 平安银行
    EXCHANGE = Exchange.SZSE    # 深交所
    START_DATE = "20200101"
    END_DATE = "20241231"
    
    # 模式选择: "single" = 单次回测, "optimize" = 参数优化
    MODE = "optimize"  # 修改这里切换模式
    
    # 步骤1: 下载数据（可选，如果数据库中已有数据可跳过）
    df = download_data_from_akshare(SYMBOL, START_DATE, END_DATE)
    
    # 步骤2: 导入数据到 vn.py
    import_data_to_vnpy(df, SYMBOL, EXCHANGE)
    
    if MODE == "single":
        # 单次回测模式
        logger.info("\n运行单次回测模式...")
        engine, result_df, stats = run_single_backtest(
            strategy_class=DoubleMaStrategy,
            symbol=SYMBOL,
            exchange=EXCHANGE,
            start=datetime(2020, 1, 1),
            end=datetime(2024, 12, 31),
            initial_capital=100000.0,
            fast_window=10,
            slow_window=20,
        )
    
    elif MODE == "optimize":
        # 参数优化模式
        logger.info("\n运行参数优化模式...")
        
        # 定义参数搜索范围
        fast_range = range(5, 31, 5)    # 快线: 5, 10, 15, 20, 25, 30
        slow_range = range(10, 61, 10)  # 慢线: 10, 20, 30, 40, 50, 60
        
        # 运行优化
        best_params, all_results = run_parameter_optimization(
            strategy_class=DoubleMaStrategy,
            symbol=SYMBOL,
            exchange=EXCHANGE,
            start=datetime(2020, 1, 1),
            end=datetime(2024, 12, 31),
            initial_capital=100000.0,
            fast_window_range=fast_range,
            slow_window_range=slow_range,
            target_metric="sharpe_ratio",  # 优化目标: sharpe_ratio, total_return, max_drawdown, win_rate
        )
        
        # 保存优化结果
        save_optimization_results(all_results, f"../data/optimization_{SYMBOL}.csv")
        
        # 使用最佳参数运行一次详细回测
        if best_params:
            logger.info("\n使用最佳参数运行详细回测...")
            engine, result_df, stats = run_single_backtest(
                strategy_class=DoubleMaStrategy,
                symbol=SYMBOL,
                exchange=EXCHANGE,
                start=datetime(2020, 1, 1),
                end=datetime(2024, 12, 31),
                initial_capital=100000.0,
                fast_window=best_params["fast_window"],
                slow_window=best_params["slow_window"],
                use_volume_filter=True,
                volume_ratio=best_params.get("volume_ratio", 1.2),
                use_volatility_filter=True,
                atr_threshold=best_params.get("atr_threshold", 0.5),
            )
            
            # 显示图表
            try:
                engine.show_chart()
            except Exception as e:
                logger.warning(f"无法显示图表: {e}")
