"""
回测日志工具模块
提供通用的回测日志保存功能
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def save_backtest_log(
    logs: List[str],
    statistics: Dict[str, Any],
    symbol: str,
    start_date: str,
    end_date: str,
    output_dir: Optional[str] = None,
    filename_prefix: str = "backtest_log",
    strategy_name: Optional[str] = None,
    extra_info: Optional[Dict[str, Any]] = None,
) -> str:
    """
    保存回测日志到文件
    
    Args:
        logs: 回测日志列表 (from engine.logs)
        statistics: 回测统计字典 (from engine.calculate_result())
        symbol: 交易标的代码
        start_date: 回测开始日期
        end_date: 回测结束日期
        output_dir: 输出目录，默认 "../../data"
        filename_prefix: 文件名前缀，默认 "backtest_log"
        strategy_name: 策略名称（可选）
        extra_info: 额外信息字典（可选）
    
    Returns:
        str: 保存的文件路径
    
    Example:
        >>> log_file = save_backtest_log(
        ...     logs=engine.logs,
        ...     statistics=statistics,
        ...     symbol="600519",
        ...     start_date="2024-01-01",
        ...     end_date="2024-12-31",
        ...     strategy_name="MA 策略"
        ... )
    """
    # 使用项目根目录 data 作为默认路径
    if output_dir is None:
        output_path = Path(__file__).resolve().parents[1] / "data"
    else:
        output_path = Path(output_dir)

    # 确保输出目录存在
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 生成文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if strategy_name:
        # 如果提供了策略名称，加入文件名
        safe_strategy_name = "".join(c for c in strategy_name if c.isalnum() or c in "-_")
        filename = f"{filename_prefix}_{safe_strategy_name}_{symbol}_{timestamp}.log"
    else:
        filename = f"{filename_prefix}_{symbol}_{timestamp}.log"
    
    log_filename = output_path / filename
    
    # 写入日志文件
    with open(log_filename, "w", encoding="utf-8") as f:
        # 标题信息
        f.write(f"Backtest Log for {symbol}\n")
        if strategy_name:
            f.write(f"Strategy: {strategy_name}\n")
        f.write(f"Start: {start_date}\n")
        f.write(f"End: {end_date}\n")
        f.write("=" * 60 + "\n\n")
        
        # 回测日志
        f.write("TRADING LOGS:\n")
        f.write("-" * 60 + "\n")
        for log in logs:
            f.write(log + "\n")
        
        # 统计信息
        f.write("\n" + "=" * 60 + "\n")
        f.write("STATISTICS:\n")
        f.write("-" * 60 + "\n")
        for key, value in statistics.items():
            if value is not None:
                f.write(f"{key}: {value}\n")
        
        # 额外信息
        if extra_info:
            f.write("\n" + "=" * 60 + "\n")
            f.write("EXTRA INFO:\n")
            f.write("-" * 60 + "\n")
            for key, value in extra_info.items():
                f.write(f"{key}: {value}\n")
    
    logger.info(f"回测日志已保存到：{log_filename}")
    return str(log_filename)


def save_optimization_log(
    optimization_results: List[Dict[str, Any]],
    symbol: str,
    output_dir: Optional[str] = None,
    filename_prefix: str = "optimization_result",
    strategy_name: Optional[str] = None,
) -> str:
    """
    保存参数优化结果到文件
    
    Args:
        optimization_results: 参数优化结果列表（每个元素是一个包含参数和结果的字典）
        symbol: 交易标的代码
        output_dir: 输出目录
        filename_prefix: 文件名前缀
        strategy_name: 策略名称
    
    Returns:
        str: 保存的文件路径
    
    Example:
        >>> results = [
        ...     {"fast_window": 10, "slow_window": 20, "sharpe": 1.5, "total_return": 0.25},
        ...     {"fast_window": 15, "slow_window": 30, "sharpe": 1.8, "total_return": 0.30},
        ... ]
        >>> opt_file = save_optimization_log(results, symbol="600519")
    """
    # 使用项目根目录 data 作为默认路径
    if output_dir is None:
        output_path = Path(__file__).resolve().parents[1] / "data"
    else:
        output_path = Path(output_dir)

    # 确保输出目录存在
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 生成文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if strategy_name:
        safe_strategy_name = "".join(c for c in strategy_name if c.isalnum() or c in "-_")
        filename = f"{filename_prefix}_{safe_strategy_name}_{symbol}_{timestamp}.log"
    else:
        filename = f"{filename_prefix}_{symbol}_{timestamp}.log"
    
    log_filename = output_path / filename
    
    # 写入优化结果
    with open(log_filename, "w", encoding="utf-8") as f:
        f.write(f"Parameter Optimization Results for {symbol}\n")
        if strategy_name:
            f.write(f"Strategy: {strategy_name}\n")
        f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")
        
        # 排序并显示最佳结果
        sorted_results = sorted(
            optimization_results,
            key=lambda x: x.get("sharpe_ratio", x.get("sharpe", 0)),
            reverse=True
        )
        
        f.write(f"Total parameter combinations tested: {len(optimization_results)}\n\n")
        
        # 显示前 10 个最佳结果
        f.write("TOP 10 BEST PERFORMING PARAMETER SETS:\n")
        f.write("-" * 80 + "\n")
        for i, result in enumerate(sorted_results[:10], 1):
            f.write(f"\nRank #{i}:\n")
            f.write(f"  Parameters:\n")
            for key, value in result.items():
                if key not in ["sharpe_ratio", "sharpe", "total_return", "pct_returns"]:
                    f.write(f"    {key}: {value}\n")
            f.write(f"  Performance:\n")
            if "sharpe_ratio" in result or "sharpe" in result:
                f.write(f"    Sharpe Ratio: {result.get('sharpe_ratio', result.get('sharpe', 'N/A'))}\n")
            if "total_return" in result or "pct_returns" in result:
                f.write(f"    Total Return: {result.get('total_return', result.get('pct_returns', 'N/A'))}\n")
        
        # 完整结果
        f.write("\n" + "=" * 80 + "\n")
        f.write("ALL RESULTS (sorted by Sharpe Ratio):\n")
        f.write("-" * 80 + "\n")
        for i, result in enumerate(sorted_results, 1):
            f.write(f"\n#{i}: ")
            params_str = ", ".join(f"{k}={v}" for k, v in result.items() 
                                  if k not in ["sharpe_ratio", "sharpe", "total_return", "pct_returns"])
            sharpe = result.get("sharpe_ratio", result.get("sharpe", 0))
            returns = result.get("total_return", result.get("pct_returns", 0))
            f.write(f"{params_str} | Sharpe={sharpe:.3f}, Return={returns:.2%}\n")
    
    logger.info(f"参数优化结果已保存到：{log_filename}")
    return str(log_filename)


# 便捷的单行调用函数
def quick_save_log(engine, symbol: str, start: str, end: str, **kwargs) -> str:
    """
    快速保存回测日志的便捷函数
    
    Args:
        engine: vn.py BacktestingEngine 实例
        symbol: 交易标的代码
        start: 开始日期
        end: 结束日期
        **kwargs: 传递给 save_backtest_log 的其他参数
    
    Returns:
        str: 保存的文件路径
    
    Example:
        >>> log_file = quick_save_log(engine, "600519", "2024-01-01", "2024-12-31")
    """
    from vnpy.trader.object import BarData
    
    # 从 engine 提取数据
    if hasattr(engine, 'logs'):
        logs = engine.logs
    else:
        logs = []
    
    # 计算统计信息（如果尚未计算）
    if hasattr(engine, 'calculate_result'):
        statistics = engine.calculate_result()
    elif hasattr(engine, 'statistics'):
        statistics = engine.statistics
    else:
        statistics = {}
    
    return save_backtest_log(
        logs=logs,
        statistics=statistics,
        symbol=symbol,
        start_date=start,
        end_date=end,
        **kwargs
    )
