# 回测日志工具说明

## 概述

`utils/backtest_logger.py` 提供了通用的回测日志保存功能，避免在各个策略回测脚本中重复编写相同的日志保存代码。

## 主要功能

### 1. `save_backtest_log()` - 保存回测日志

保存完整的回测日志和统计信息到文件。

**参数:**
- `logs`: 回测日志列表 (from engine.logs)
- `statistics`: 回测统计字典 (from engine.calculate_statistics())
- `symbol`: 交易标的代码
- `start_date`: 回测开始日期 (字符串)
- `end_date`: 回测结束日期 (字符串)
- `output_dir`: 输出目录，默认 "../../data"
- `filename_prefix`: 文件名前缀，默认 "backtest_log"
- `strategy_name`: 策略名称（可选，会加入文件名）
- `extra_info`: 额外信息字典（可选）

**返回值:**
- `str`: 保存的文件路径

**示例:**
```python
from utils.backtest_logger import save_backtest_log

log_file = save_backtest_log(
    logs=engine.logs,
    statistics=statistics,
    symbol="600519",
    start_date="2024-01-01",
    end_date="2024-12-31",
    strategy_name="双均线策略",
    extra_info={
        "fast_window": 10,
        "slow_window": 20
    }
)
```

---

### 2. `quick_save_log()` - 快速保存

便捷函数，一行代码保存回测日志。自动从 engine 提取 logs 和 statistics。

**参数:**
- `engine`: vn.py BacktestingEngine 实例
- `symbol`: 交易标的代码
- `start`: 开始日期 (datetime)
- `end`: 结束日期 (datetime)
- `**kwargs`: 传递给 save_backtest_log 的其他参数

**返回值:**
- `str`: 保存的文件路径

**示例:**
```python
from utils.backtest_logger import quick_save_log

log_file = quick_save_log(
    engine=engine,
    symbol="600519",
    start=datetime(2024, 1, 1),
    end=datetime(2024, 12, 31),
    strategy_name="MA 策略"
)
```

---

### 3. `save_optimization_log()` - 保存参数优化结果

保存参数优化的所有结果到文件，自动排序并显示 TOP 10。

**参数:**
- `optimization_results`: 参数优化结果列表
- `symbol`: 交易标的代码
- `output_dir`: 输出目录，默认 "../../data"
- `filename_prefix`: 文件名前缀，默认 "optimization_result"
- `strategy_name`: 策略名称（可选）

**返回值:**
- `str`: 保存的文件路径

**示例:**
```python
from utils.backtest_logger import save_optimization_log

results = [
    {"fast_window": 10, "slow_window": 20, "sharpe_ratio": 1.5, "total_return": 0.25},
    {"fast_window": 15, "slow_window": 30, "sharpe_ratio": 1.8, "total_return": 0.30},
]

opt_file = save_optimization_log(
    optimization_results=results,
    symbol="600519",
    strategy_name="双均线策略"
)
```

---

## 使用场景

### 场景 1: 单策略回测

```python
from vnpy_ctastrategy.backtesting import BacktestingEngine
from utils.backtest_logger import quick_save_log

# 运行回测
engine = BacktestingEngine()
# ... 配置和运行 ...

# 保存日志
quick_save_log(engine, "600519", datetime(2024, 1, 1), datetime(2024, 12, 31))
```

### 场景 2: 参数优化

```python
from utils.backtest_logger import save_optimization_log

# 运行参数优化得到 results 列表
best_params, results = run_parameter_optimization(...)

# 保存优化结果
save_optimization_log(results, symbol="600519")
```

### 场景 3: 批量回测

```python
from utils.backtest_logger import save_backtest_log

for symbol in ["600519", "000001", "300750"]:
    engine = BacktestingEngine()
    # ... 运行回测 ...
    
    statistics = engine.calculate_statistics()
    
    save_backtest_log(
        logs=engine.logs,
        statistics=statistics,
        symbol=symbol,
        start_date="2024-01-01",
        end_date="2024-12-31"
    )
```

---

## 输出文件格式

### 回测日志文件示例

```
Backtest Log for 600519
Strategy: 双均线策略
Start: 2024-01-01
End: 2024-12-31
============================================================

TRADING LOGS:
------------------------------------------------------------
2024-01-15 10:30:00: 买入 600519, 价格：180.5, 数量：100
2024-02-20 14:45:00: 卖出 600519, 价格：195.2, 数量：100
...

============================================================
STATISTICS:
------------------------------------------------------------
total_return: 25.30%
sharpe_ratio: 1.85
max_drawdown: -8.20%
win_rate: 58.50%
...
```

### 参数优化结果文件示例

```
Parameter Optimization Results for 600519
Strategy: 双均线策略
Timestamp: 2024-03-12 15:30:45
================================================================================

Total parameter combinations tested: 50

TOP 10 BEST PERFORMING PARAMETER SETS:
--------------------------------------------------------------------------------

Rank #1:
  Parameters:
    fast_window: 15
    slow_window: 30
  Performance:
    Sharpe Ratio: 1.85
    Total Return: 30.25%

Rank #2:
  Parameters:
    fast_window: 10
    slow_window: 20
  Performance:
    Sharpe Ratio: 1.52
    Total Return: 25.30%

...

================================================================================
ALL RESULTS (sorted by Sharpe Ratio):
--------------------------------------------------------------------------------
#1: fast_window=15, slow_window=30 | Sharpe=1.850, Return=30.25%
#2: fast_window=10, slow_window=20 | Sharpe=1.520, Return=25.30%
...
```

---

## 已使用该工具的脚本

- `strategies/backtest_ma.py` - 双均线策略回测
- `strategies/sector/backtest_mainline.py` - 主线选股策略回测

---

## 优势

1. **代码复用**: 避免在每个回测脚本中重复编写日志保存代码
2. **统一格式**: 所有策略的日志格式保持一致
3. **易于维护**: 修改日志格式只需改一处
4. **功能丰富**: 支持策略名称、额外信息、自动排序等
5. **简洁易用**: quick_save_log 一行代码搞定

---

## 注意事项

1. 确保输出目录存在（工具会自动创建）
2. 文件名会自动添加时间戳，避免覆盖
3. 如果提供了 strategy_name，会加入文件名中便于识别
4. extra_info 可以是任意字典，用于记录策略参数等额外信息
