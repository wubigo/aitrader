"""
双均线策略 - 基于 vn.py CTA 模块
金叉买入，死叉卖出
增加成交量和波动率过滤
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
    双均线策略（带过滤条件）
    快线 > 慢线：买入
    快线 < 慢线：卖出
    
    过滤条件：
    - 成交量过滤：当前成交量 > 均量 * volume_ratio
    - 波动率过滤：ATR > 阈值，排除低波动行情
    - 趋势强度过滤：ADX > 阈值，确保趋势明确
    """
    author = "AI Trader"

    # 均线参数
    fast_window = 10      # 快线周期
    slow_window = 20      # 慢线周期
    fixed_size = 100      # 每次交易股数
    
    # 成交量过滤参数
    # 逻辑: 当前成交量 > 成交量均线 × 倍数阈值
    # 用途: 排除缩量假突破，只在放量时交易
    use_volume_filter = True      # 是否启用成交量过滤
    volume_window = 20            # 成交量均线周期
    volume_ratio = 1.2            # 成交量倍数阈值（当前量 > 均量 * 1.2）
    
    # 波动率过滤参数 
    # 逻辑: ATR(14) / 收盘价 × 100% > 阈值
    # 用途: 排除低波动盘整行情，避免无效交易
    use_volatility_filter = True  # 是否启用波动率过滤
    atr_window = 14               # ATR周期
    atr_threshold = 0.5           # ATR最小阈值（价格百分比）
    
    # 趋势强度过滤参数
    # 逻辑: ADX(14) > 阈值
    # 用途: 确保趋势明确，避免跟随假突破
    use_trend_filter = False      # 是否启用趋势强度过滤
    adx_window = 14               # ADX周期
    adx_threshold = 25            # ADX阈值（>25认为趋势较强）

    parameters = [
        "fast_window", "slow_window", "fixed_size",
        "use_volume_filter", "volume_window", "volume_ratio",
        "use_volatility_filter", "atr_window", "atr_threshold",
        "use_trend_filter", "adx_window", "adx_threshold",
    ]
    variables = [
        "fast_ma", "slow_ma", "ma_signal",
        "volume_ma", "current_volume_ratio",
        "atr_value", "atr_pct",
        "adx_value", "filter_status",
    ]

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
        # 计算所需的最小数据条数
        required_size = max(
            self.slow_window,
            self.volume_window,
            self.atr_window + 10,
            self.adx_window + 10,
        ) + 20
        self.load_bar(required_size)
        
        # 初始化过滤状态
        self.filter_status = "N/A"

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
        
        # 计算过滤条件
        filters_passed = self.check_filters(bar)
        
        # 如果没有通过过滤，只记录信号不交易
        if not filters_passed:
            if cross_over:
                self.ma_signal = 1
                self.write_log(f"金叉信号被过滤 @ {bar.close_price:.2f} [{self.filter_status}]")
            elif cross_below:
                self.ma_signal = -1
                self.write_log(f"死叉信号被过滤 @ {bar.close_price:.2f} [{self.filter_status}]")
            self.put_event()
            return

        # 交易逻辑（通过过滤后执行）
        if cross_over:
            # 金叉：买入
            self.ma_signal = 1
            if self.pos == 0:
                self.buy(bar.close_price, self.fixed_size)
                self.write_log(f"金叉买入 @ {bar.close_price:.2f} [过滤通过]")
            elif self.pos < 0:
                # 如果有空头仓位，先平仓再开多
                self.cover(bar.close_price, abs(self.pos))
                self.buy(bar.close_price, self.fixed_size)
                self.write_log(f"金叉平空开多 @ {bar.close_price:.2f} [过滤通过]")
                
        elif cross_below:
            # 死叉：卖出
            self.ma_signal = -1
            if self.pos == 0:
                self.short(bar.close_price, self.fixed_size)
                self.write_log(f"死叉开空 @ {bar.close_price:.2f} [过滤通过]")
            elif self.pos > 0:
                # 如果有多头仓位，先平仓再开空
                self.sell(bar.close_price, abs(self.pos))
                self.short(bar.close_price, self.fixed_size)
                self.write_log(f"死叉平多开空 @ {bar.close_price:.2f} [过滤通过]")

        self.put_event()
    
    def check_filters(self, bar: BarData) -> bool:
        """
        检查过滤条件
        
        :return: True 表示通过所有过滤条件，False 表示被过滤
        """
        filter_messages = []
        
        # 1. 成交量过滤
        if self.use_volume_filter:
            # 计算成交量均线
            volume_array = self.am.volume
            if len(volume_array) >= self.volume_window:
                self.volume_ma = sum(volume_array[-self.volume_window:]) / self.volume_window
                self.current_volume_ratio = bar.volume / self.volume_ma if self.volume_ma > 0 else 0
                
                if self.current_volume_ratio < self.volume_ratio:
                    filter_messages.append(f"成交量不足({self.current_volume_ratio:.2f}<{self.volume_ratio})")
            else:
                filter_messages.append("成交量数据不足")
        
        # 2. 波动率过滤（使用ATR）
        if self.use_volatility_filter:
            self.atr_value = self.am.atr(self.atr_window)
            self.atr_pct = (self.atr_value / bar.close_price * 100) if bar.close_price > 0 else 0
            
            if self.atr_pct < self.atr_threshold:
                filter_messages.append(f"波动率过低({self.atr_pct:.2f}%<{self.atr_threshold}%)")
        
        # 3. 趋势强度过滤（使用ADX）
        if self.use_trend_filter:
            # 使用ArrayManager计算ADX
            adx_array = self.am.adx(self.adx_window)
            if adx_array is not None and len(adx_array) > 0:
                self.adx_value = adx_array[-1]
                if self.adx_value < self.adx_threshold:
                    filter_messages.append(f"趋势太弱({self.adx_value:.1f}<{self.adx_threshold})")
            else:
                filter_messages.append("ADX计算失败")
        
        # 更新过滤状态
        if filter_messages:
            self.filter_status = "; ".join(filter_messages)
            return False
        else:
            self.filter_status = "PASS"
            return True

    def on_order(self, order: OrderData):
        """收到委托回报"""
        pass

    def on_trade(self, trade: TradeData):
        """收到成交回报"""
        self.write_log(f"成交: {trade.direction.value} {trade.volume} @ {trade.price:.2f}")
        self.put_event()
