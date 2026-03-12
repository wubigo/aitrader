"""
双均线策略 - 基于 vn.py CTA 模块
金叉买入，死叉卖出
"""
from vnpy_ctastrategy import (
    CtaTemplate,
    BarGenerator,
    ArrayManager,
    BarData,
    TradeData,
    OrderData,
)
from vnpy.trader.object import TickData


class DoubleMaStrategy(CtaTemplate):
    """
    双均线策略
    快线 > 慢线：买入
    快线 < 慢线：卖出
    """
    author = "AI Trader"

    # 策略参数
    fast_window = 10      # 快线周期
    slow_window = 20      # 慢线周期
    fixed_size = 100      # 每次交易股数

    parameters = ["fast_window", "slow_window", "fixed_size"]
    variables = ["fast_ma", "slow_ma", "ma_signal"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        """构造函数"""
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        
        # K线合成器：1分钟合成日线（可根据需要调整）
        self.bg = BarGenerator(self.on_bar)
        # 数组管理器：用于计算技术指标
        self.am = ArrayManager()

    def on_init(self):
        """策略初始化"""
        self.write_log("策略初始化")
        # 加载历史数据用于计算均线（至少 slow_window 条）
        self.load_bar(self.slow_window + 10)

    def on_start(self):
        """策略启动"""
        self.write_log("策略启动")
        self.put_event()

    def on_stop(self):
        """策略停止"""
        self.write_log("策略停止")
        self.put_event()

    def on_tick(self, tick: TickData):
        """收到 Tick 数据"""
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData):
        """收到 K 线数据"""
        # 更新 K 线到数组管理器
        self.am.update_bar(bar)
        
        # 数据未准备好，不交易
        if not self.am.inited:
            return

        # 计算均线
        self.fast_ma = self.am.sma(self.fast_window, array=True)[-1]
        self.slow_ma = self.am.sma(self.slow_window, array=True)[-1]
        
        # 计算上一周期的均线（用于判断交叉）
        fast_ma_last = self.am.sma(self.fast_window, array=True)[-2]
        slow_ma_last = self.am.sma(self.slow_window, array=True)[-2]

        # 判断金叉死叉
        cross_over = (self.fast_ma > self.slow_ma) and (fast_ma_last <= slow_ma_last)
        cross_below = (self.fast_ma < self.slow_ma) and (fast_ma_last >= slow_ma_last)

        # 交易逻辑
        if cross_over:
            # 金叉：买入
            self.ma_signal = 1
            if self.pos == 0:
                self.buy(bar.close_price, self.fixed_size)
                self.write_log(f"金叉买入 @ {bar.close_price:.2f}")
            elif self.pos < 0:
                # 如果有空头仓位，先平仓再开多
                self.cover(bar.close_price, abs(self.pos))
                self.buy(bar.close_price, self.fixed_size)
                self.write_log(f"金叉平空开多 @ {bar.close_price:.2f}")
                
        elif cross_below:
            # 死叉：卖出
            self.ma_signal = -1
            if self.pos == 0:
                self.short(bar.close_price, self.fixed_size)
                self.write_log(f"死叉开空 @ {bar.close_price:.2f}")
            elif self.pos > 0:
                # 如果有多头仓位，先平仓再开空
                self.sell(bar.close_price, abs(self.pos))
                self.short(bar.close_price, self.fixed_size)
                self.write_log(f"死叉平多开空 @ {bar.close_price:.2f}")

        self.put_event()

    def on_order(self, order: OrderData):
        """收到委托回报"""
        pass

    def on_trade(self, trade: TradeData):
        """收到成交回报"""
        self.write_log(f"成交: {trade.direction.value} {trade.volume} @ {trade.price:.2f}")
        self.put_event()
