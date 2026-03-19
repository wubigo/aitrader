"""
回测日志工具使用示例

展示如何使用 utils.backtest_logger 模块中的通用函数
"""

from vnpy_ctastrategy.backtesting import BacktestingEngine
from datetime import datetime
from utils.backtest_logger import (
    save_backtest_log,
    save_optimization_log,
    quick_save_log
)


# ============================================================================
# 示例 1: 使用 save_backtest_log 保存回测日志
# ============================================================================
def example_1_save_backtest_log():
    """示例 1: 手动保存回测日志"""
    
    # 假设你已经运行了回测
    engine = BacktestingEngine()
    # ... 运行回测代码 ...
    
    # 计算统计结果
    statistics = engine.calculate_statistics()
    
    # 保存日志
    log_file = save_backtest_log(
        logs=engine.logs,                      # 引擎的日志列表
        statistics=statistics,                 # 统计字典
        symbol="600519",                       # 标的代码
        start_date="2024-01-01",              # 开始日期
        end_date="2024-12-31",                # 结束日期
        strategy_name="双均线策略",            # 策略名称（可选）
        output_dir="../../data",              # 输出目录（可选）
        extra_info={                          # 额外信息（可选）
            "fast_window": 10,
            "slow_window": 20,
        }
    )
    
    print(f"日志已保存到：{log_file}")


# ============================================================================
# 示例 2: 使用 quick_save_log 快速保存（推荐）
# ============================================================================
def example_2_quick_save():
    """示例 2: 快速保存回测日志（最简洁）"""
    
    engine = BacktestingEngine()
    # ... 运行回测 ...
    
    # 一行代码保存所有信息
    log_file = quick_save_log(
        engine=engine,
        symbol="600519",
        start=datetime(2024, 1, 1),
        end=datetime(2024, 12, 31),
        strategy_name="MA 策略"
    )
    
    print(f"日志已保存到：{log_file}")


# ============================================================================
# 示例 3: 保存参数优化结果
# ============================================================================
def example_3_save_optimization():
    """示例 3: 保存参数优化结果"""
    
    # 假设这是你的优化结果列表
    optimization_results = [
        {
            "fast_window": 10,
            "slow_window": 20,
            "volume_ratio": 1.2,
            "sharpe_ratio": 1.5,
            "total_return": 0.25,
            "max_drawdown": -0.08,
            "win_rate": 0.55,
        },
        {
            "fast_window": 15,
            "slow_window": 30,
            "volume_ratio": 1.5,
            "sharpe_ratio": 1.8,
            "total_return": 0.30,
            "max_drawdown": -0.06,
            "win_rate": 0.60,
        },
        # ... 更多结果
    ]
    
    # 保存优化结果
    opt_file = save_optimization_log(
        optimization_results=optimization_results,
        symbol="600519",
        strategy_name="双均线策略",
        output_dir="../../data"
    )
    
    print(f"优化结果已保存到：{opt_file}")


# ============================================================================
# 示例 4: 在实际策略中的应用
# ============================================================================
def example_4_real_usage():
    """示例 4: 实际策略回测中的完整应用"""
    
    from vnpy.trader.constant import Exchange, Interval
    
    # 创建回测引擎
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol="600519.SSE",
        interval=Interval.DAILY,
        start=datetime(2024, 1, 1),
        end=datetime(2024, 12, 31),
        rate=0.0003,
        slippage=0.01,
        size=1,
        pricetick=0.01,
        capital=100000,
    )
    
    # 添加策略
    # engine.add_strategy(MyStrategy, {...})
    
    # 运行回测
    engine.load_data()
    engine.run_backtesting()
    
    # 计算结果
    df = engine.calculate_result()
    statistics = engine.calculate_statistics()
    
    # 打印统计
    for key, value in statistics.items():
        if value is not None:
            print(f"{key}: {value}")
    
    # 保存日志（方法 1: 使用 quick_save_log）
    log_file = quick_save_log(
        engine=engine,
        symbol="600519",
        start=datetime(2024, 1, 1),
        end=datetime(2024, 12, 31),
        strategy_name="我的策略"
    )
    
    # 或者保存日志（方法 2: 使用 save_backtest_log，更灵活）
    log_file = save_backtest_log(
        logs=engine.logs,
        statistics=statistics,
        symbol="600519",
        start_date="2024-01-01",
        end_date="2024-12-31",
        strategy_name="我的策略",
        extra_info={
            "备注": "这是示例策略",
            "版本": "v1.0"
        }
    )


# ============================================================================
# 示例 5: 批量回测时保存多个日志
# ============================================================================
def example_5_batch_backtest():
    """示例 5: 批量回测多个标的"""
    
    symbols = ["600519", "000001", "300750"]
    results = []
    
    for symbol in symbols:
        engine = BacktestingEngine()
        # ... 配置和运行回测 ...
        
        statistics = engine.calculate_statistics()
        
        # 为每个标的保存独立的日志
        log_file = save_backtest_log(
            logs=engine.logs,
            statistics=statistics,
            symbol=symbol,
            start_date="2024-01-01",
            end_date="2024-12-31",
            strategy_name="批量回测",
        )
        
        results.append({
            "symbol": symbol,
            "return": statistics.get("total_return", 0),
            "log_file": log_file
        })
    
    # 汇总结果
    print("\n批量回测汇总:")
    for r in results:
        print(f"{r['symbol']}: 收益率 {r['return']:.2%}, 日志：{r['log_file']}")


if __name__ == "__main__":
    print("=" * 60)
    print("回测日志工具使用示例")
    print("=" * 60)
    
    # 取消注释以运行示例
    # example_1_save_backtest_log()
    # example_2_quick_save()
    # example_3_save_optimization()
    # example_4_real_usage()
    # example_5_batch_backtest()
    
    print("\n提示：取消注释相应的示例函数来运行测试")
