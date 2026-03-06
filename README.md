#  量化系统概述

```
宏观评分 → 决定仓位
行业排名 → 决定方向
个股筛选 → 决定标的
趋势规则 → 决定买卖点
```

## 宏观评分

### 国债收益率曲线

### 信用利差

### 社融数据

### PMI

### 政策会议纪要


## 中观评分

## 微观评分

## 行业轮动

### 行业评分

```
行业总评分 =
趋势强度（30%）
 + 动量强度（20%）
 + 相对强弱RS（15%）
 + 资金活跃度（10%）
 + ⭐ 盈利增速（25%）
```

### 行业拥挤度监测

### 北向资金行业配置变化

### 盈利预期变化率

### A股主线识别引擎(Main Trend Detection Engine)

***主线 = 持续吸走流动性的行业***

```
        主线评分
            ↓
────────────────────
资金集中度      30%
盈利预期变化    25%
趋势扩散程度    20%
政策强化强度    15%
市场共识度      10%
────────────────────
```

## 个股基本面

###  东方财富-A股-财务分析-主要指标 

get_stock_profit_growth_em 

| 名称 | 类型 | 描述 |
|:---|:---|:---| 
| SECUCODE | object | 股票代码(带后缀) |
| SECURITY_CODE | object | 股票代码 |
| SECURITY_NAME_ABBR | object | 股票名称 |
| REPORT_DATE | object | 报告日期 |
| REPORT_TYPE | object | 报告类型 |
| REPORT_DATE_NAME | object | 报告日期名称 |
| EPSJB | float64 | 基本每股收益(元) |
| EPSKCJB | float64 | 扣非每股收益(元) |
| EPSXS | float64 | 稀释每股收益(元) |
| BPS | float64 | 每股净资产(元) |
| MGZBGJ | float64 | 每股公积金(元) |
| MGWFPLR | float64 | 每股未分配利润(元) |
| MGJYXJJE | float64 | 每股经营现金流(元) |
| TOTALOPERATEREVE | float64 | 营业总收入(元) |
| MLR | float64 | 毛利润(元) |
| PARENTNETPROFIT | float64 | 归属净利润(元) |
| KCFJCXSYJLR | float64 | 扣非净利润(元) |
| TOTALOPERATEREVETZ | float64 | 营业总收入同比增长(%) |
| PARENTNETPROFITTZ | float64 | 归属净利润同比增长(%) |
| KCFJCXSYJLRTZ | float64 | 扣非净利润同比增长(%) |
| YYZSRGDHBZC | float64 | 营业总收入滚动环比增长(%) |
| NETPROFITRPHBZC | float64 | 归属净利润滚动环比增长(%) |
| KFJLRGDHBZC | float64 | 扣非净利润滚动环比增长(%) |
| ROEJQ | float64 | 净资产收益率(加权)(%) |
| ROEKCJQ | float64 | 净资产收益率(扣非/加权)(%) |
| ZZCJLL | float64 | 总资产收益率(加权)(%) |
| XSJLL | float64 | 净利率(%) |
| XSMLL | float64 | 毛利率(%) |
| YSZKYYSR | float64 | 预收账款/营业收入 |
| XSJXLYYSR | float64 | 销售净现金流/营业收入 |
| JYXJLYYSR | float64 | 经营净现金流/营业收入 |
| TAXRATE | float64 | 实际税率(%) |
| LD | float64 | 流动比率 |
| SD | float64 | 速动比率 |
| XJLLB | float64 | 现金流量比率 |
| ZCFZL | float64 | 资产负债率(%) |
| QYCS | float64 | 权益系数 |
| CQBL | float64 | 产权比率 |
| ZZCZZTS | float64 | 总资产周转天数(天) |
| CHZZTS | float64 | 存货周转天数(天) |
| YSZKZZTS | float64 | 应收账款周转天数(天) |
| TOAZZL | float64 | 总资产周转率(次) |
| CHZZL | float64 | 存货周转率(次) |
| YSZKZZL | float64 | 应收账款周转率(次) |


## 仓位控制


# 因子引擎

## 趋势因子 (Trend Factor)  

## 价值因子 (Value Factor)

## 择股因子 (Select Factor)

## 择时因子 (Select Time Factor)

## 情绪因子 (Emotion Factor)

## 质量因子 (Quality Factor)

## 动量因子 (Momentum Factor)

### 核心因子类型

```
简单动量       = (P_t / P_{t-N}) - 1      # N日累计收益率
对数动量      = ln(P_t / P_{t-N})         # 对数收益率
时间加权动量   = Σ(weight_i × return_i)   # 指数加权收益率
相对动量      = Mom_stock - Mom_benchmark # 相对基准超额收益
风险调整动量   = Mom / Volatility          # 动量/波动率
加速动量      = Mom_short - Mom_long      # 动量变化率
行业内动量    = Mom_stock - Mom_industry  # 行业内相对强弱
```

### 时间周期

| 类型 | 回看天数 | 用途 |
|:---|:---|:---|
| 短期动量 | 20日 | 短期趋势交易 |
| 中期动量 | 60日/120日 | 中频策略 |
| 长期动量 | 250日 | 长线趋势 |

### 因子预处理

```
去极值  → MAD法或百分位法
标准化  → Z-Score或Min-Max
中性化  → 行业、市值中性化
```

### 使用示例

```python
from momentum import MomentumFactor, MomentumFactorProcessor, MomentumSignal

# 计算动量因子
mf = MomentumFactor(df)
df_with_momentum = mf.compute_all_momentum()

# 去极值和标准化
processor = MomentumFactorProcessor()
cols = ['momentum_20d', 'momentum_60d', 'momentum_120d']
df_processed = processor.winsorize(df_with_momentum, cols)
df_processed = processor.standardize(df_processed, cols)

# 生成交易信号
signal = MomentumSignal.generate_signals(df_processed, 'momentum_60d')
```
