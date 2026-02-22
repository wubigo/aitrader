import backtrader as bt
import pandas as pd
import tushare as ts
import matplotlib.pyplot as plt

# --- 1. 配置区 ---
TUSHARE_TOKEN = '1f832aa50ab6eda9166cf7ead111540c1eba28c7fb978'  # 替换为你的 Tushare Token
STOCK_CODE = '600519.SH'  # 股票代码
START_DATE = '20200101'  # 回测开始日期
END_DATE = '20241231'  # 回测结束日期


# --- 2. 数据获取与预处理 ---
def get_data_from_tushare():
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()

    # 获取复权数据 (前复权)
    df = pro.daily(ts_code=STOCK_CODE, start_date=START_DATE, end_date=END_DATE, adj='qfq')

    # 数据清洗与格式转换 (关键步骤)
    df = df.sort_values('trade_date')  # 按时间升序排列
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df.set_index('trade_date', inplace=True)

    # 重命名列名以匹配 backtrader 要求
    df.rename(columns={'vol': 'volume'}, inplace=True)

    # 选择核心列
    df = df[['open', 'high', 'low', 'close', 'volume']]

    # 处理缺失值
    df.dropna(inplace=True)

    return df


# --- 3. 定义交易策略 ---
class MyStrategy(bt.Strategy):
    params = (
        ('fast_period', 5),  # 快线周期
        ('slow_period', 20),  # 慢线周期
    )

    def __init__(self):
        # 初始化指标
        self.data_close = self.datas[0].close
        self.sma_fast = bt.indicators.SimpleMovingAverage(self.datas[0], period=self.p.fast_period)
        self.sma_slow = bt.indicators.SimpleMovingAverage(self.datas[0], period=self.p.slow_period)

        # 金叉与死叉信号
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)

    def next(self):
        # 如果没有持仓
        if not self.position:
            # 金叉：快线从下向上穿过慢线，买入
            if self.crossover > 0:
                self.buy(size=100)  # 买入100股

        # 如果持有仓位
        else:
            # 死叉：快线从上向下穿过慢线，卖出
            if self.crossover < 0:
                self.sell(size=100)


# --- 4. 执行回测与分析 ---
if __name__ == '__main__':
    # 1. 准备数据
    data_df = get_data_from_tushare()

    # 2. 创建 Cerebro 引擎
    cerebro = bt.Cerebro()

    # 3. 添加策略
    cerebro.addstrategy(MyStrategy)

    # 4. 创建数据源
    data_feed = bt.feeds.PandasData(dataname=data_df)

    # 5. 将数据添加到引擎
    cerebro.adddata(data_feed)

    # 6. 设置初始资金
    cerebro.broker.setcash(100000.0)  # 10万本金

    # 7. 设置手续费 (例如：万三)
    cerebro.broker.setcommission(commission=0.0003)

    # 8. 添加分析器 (绩效分析)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')  # 夏普比率
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')  # 最大回撤
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')  # 收益率

    # 9. 打印初始状态
    print(f'初始资金: {cerebro.broker.getvalue():.2f}')

    # 10. 运行回测
    results = cerebro.run()

    # 11. 打印最终结果
    strat = results[0]
    print(f'最终资金: {cerebro.broker.getvalue():.2f}')
    # print(f'夏普比率: {strat.analyzers.sharpe.get_analysis()["sharperatio"]:.2f}')
    print(f'最大回撤: {strat.analyzers.drawdown.get_analysis()["max"]["drawdown"]:.2f}%')

    # 12. 绘制图表
    cerebro.plot(style='candlestick', figsize=(15, 8), tight_layout=True)
    plt.show()
