"""
A股主线识别策略 - 基于行业轮动和资金流向
核心逻辑：
1. 计算各行业/板块的相对强度（RS）
2. 识别资金流向（成交量+价格变动）
3. 选择最强主线行业中的龙头股
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
from typing import Dict, List, Tuple
import numpy as np


class SectorRotationStrategy(CtaTemplate):
    """
    A股主线识别策略
    
    主线识别逻辑：
    1. 价格强度：N日涨幅排名
    2. 资金强度：N日资金净流入排名（量价结合）
    3. 趋势强度：ADX或均线多头排列
    
    选股逻辑：
    - 在主线行业中选择龙头股（市值最大或涨幅最大）
    """
    author = "AI Trader"

    # 主线识别参数
    sector_count = 5          # 选择前N个强势行业
    ranking_period = 20       # 排名计算周期（日）
    
    # 强度计算权重
    price_weight = 0.5        # 价格涨幅权重
    volume_weight = 0.3       # 成交量放大权重
    trend_weight = 0.2        # 趋势强度权重
    
    # 交易参数
    max_holdings = 3          # 最大持仓数量
    fixed_capital = 30000     # 每只股票分配资金
    stop_loss_pct = 0.08      # 止损比例 8%
    take_profit_pct = 0.15    # 止盈比例 15%
    
    # 调仓周期
    rebalance_days = 5        # 每5天调仓一次

    parameters = [
        "sector_count", "ranking_period",
        "price_weight", "volume_weight", "trend_weight",
        "max_holdings", "fixed_capital",
        "stop_loss_pct", "take_profit_pct",
        "rebalance_days",
    ]
    variables = [
        "sector_scores", "leading_sectors", 
        "selected_stocks", "days_since_rebalance",
        "entry_prices",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        
        self.bg = BarGenerator(self.on_bar)
        self.am = ArrayManager(size=100)
        
        # 股票池数据（需要在初始化时加载）
        self.stock_pool: Dict[str, Dict] = {}  # {symbol: {sector, market_cap, ...}}
        self.sector_stocks: Dict[str, List[str]] = {}  # {sector: [symbols]}
        
        # 运行时数据
        self.sector_scores: Dict[str, float] = {}
        self.leading_sectors: List[str] = []
        self.selected_stocks: List[str] = []
        self.days_since_rebalance = 0
        self.entry_prices: Dict[str, float] = {}  # 记录入场价格
        
        # 初始化股票池
        self.init_stock_universe()
        print(self.stock_pool)

    def init_stock_universe(self):
        """
        初始化股票池和行业分类
        实际使用时从数据库或AKShare加载
        """
        # 示例：模拟股票池结构
        self.sector_stocks = {
            "technology": ["000938.SZSE", "002415.SZSE", "600570.SSE"],  # 科技
            "finance": ["000001.SZSE", "600000.SSE", "600030.SSE"],     # 金融
            "consumer": ["000858.SZSE", "600519.SSE", "002714.SZSE"],   # 消费
            "healthcare": ["600276.SSE", "000661.SZSE", "300760.SZSE"], # 医药
            "new_energy": ["300750.SZSE", "002594.SZSE", "601012.SSE"], # 新能源
        }
        
        # 合并所有股票
        all_stocks = []
        for sector, stocks in self.sector_stocks.items():
            all_stocks.extend(stocks)
            for stock in stocks:
                self.stock_pool[stock] = {"sector": sector}

    def on_init(self):
        """策略初始化"""
        self.write_log("主线识别策略初始化")
        self.load_`bar(self.ranking_period + 20)

    def on_start(self):
        """策略启动"""
        self.write_log("策略启动 - 开始识别市场主线")
        self.put_event()

    def on_stop(self):
        """策略停止"""
        self.write_log("策略停止")
        self.put_event()

    def on_tick(self, tick: TickData):
        """收到 Tick 数据"""
        self.bg.update_tick(tick)

    def calculate_sector_strength(self, sector: str) -> float:
        """
        计算行业强度得分
        
        综合评分 = 价格涨幅×0.5 + 资金强度×0.3 + 趋势强度×0.2
        
        :param sector: 行业名称
        :return: 强度得分
        """
        stocks = self.sector_stocks.get(sector, [])
        if not stocks:
            return 0.0
        
        sector_scores = []
        
        for symbol in stocks:
            # 这里假设可以通过某种方式获取该股票的数据
            # 实际使用时需要从数据库或外部数据源获取
            score = self.calculate_stock_strength(symbol)
            if score is not None:
                sector_scores.append(score)
        
        if not sector_scores:
            return 0.0
        
        # 取行业平均分
        return np.mean(sector_scores)

    def calculate_stock_strength(self, symbol: str) -> float:
        """
        计算单只股票的强度得分
        
        :param symbol: 股票代码
        :return: 综合强度得分
        """
        # 实际实现时需要从外部获取该股票的历史数据
        # 这里返回None表示数据不可用
        # 在完整实现中，应该：
        # 1. 从数据库查询该symbol的BarData
        # 2. 计算各项指标
        
        # 简化示例：假设当前策略只交易单个标的
        if symbol == self.vt_symbol:
            return self.calculate_current_strength()
        
        return None

    def calculate_current_strength(self) -> float:
        """
        计算当前交易标的的强度
        用于单标的回测模式
        """
        if not self.am.inited:
            return 0.0
        
        # 1. 价格强度（N日涨幅）
        close = self.am.close
        price_change = (close[-1] - close[-self.ranking_period]) / close[-self.ranking_period] * 100
        
        # 2. 资金强度（成交量放大 + 价格方向）
        volume = self.am.volume
        avg_volume = np.mean(volume[-self.ranking_period:-1])
        current_volume = volume[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        
        # 资金流向：上涨放量为正，下跌放量为负
        daily_return = (close[-1] - close[-2]) / close[-2] if len(close) > 1 else 0
        money_flow = volume_ratio * (1 if daily_return > 0 else -1)
        
        # 3. 趋势强度（ADX）
        adx_value = 25  # 默认值
        try:
            adx_array = self.am.adx(14)
            if adx_array is not None and len(adx_array) > 0:
                adx_value = adx_array[-1]
        except:
            pass
        
        # 归一化到0-100
        price_score = max(0, min(100, (price_change + 20) * 2.5))  # -20%~+20% 映射到 0-100
        volume_score = max(0, min(100, (volume_ratio - 0.5) * 66))  # 0.5-2.0 映射到 0-100
        trend_score = min(100, adx_value * 4)  # 0-25 映射到 0-100
        
        # 综合得分
        total_score = (
            self.price_weight * price_score +
            self.volume_weight * volume_score +
            self.trend_weight * trend_score
        )
        
        return total_score

    def identify_leading_sectors(self) -> List[str]:
        """
        识别市场主线行业
        
        :return: 强势行业列表（按强度排序）
        """
        scores = {}
        
        for sector in self.sector_stocks.keys():
            score = self.calculate_sector_strength(sector)
            scores[sector] = score
        
        # 排序取前N
        sorted_sectors = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        self.leading_sectors = [s[0] for s in sorted_sectors[:self.sector_count]]
        self.sector_scores = dict(sorted_sectors)
        
        return self.leading_sectors

    def select_stocks_from_sectors(self) -> List[str]:
        """
        从主线行业中选股
        
        策略：
        1. 只在主线行业中选股
        2. 选择强度最高的股票
        """
        selected = []
        
        for sector in self.leading_sectors:
            stocks = self.sector_stocks.get(sector, [])
            # 简化：选择第一个作为代表
            # 实际应该根据市值、涨幅等选择龙头
            if stocks:
                selected.extend(stocks[:1])  # 每行业选1只
        
        self.selected_stocks = selected[:self.max_holdings]
        return self.selected_stocks

    def check_stop_loss_take_profit(self, bar: BarData) -> bool:
        """
        检查止损止盈
        
        :return: True 表示触发止损/止盈
        """
        symbol = bar.vt_symbol
        if symbol not in self.entry_prices:
            return False
        
        entry_price = self.entry_prices[symbol]
        current_price = bar.close_price
        
        # 计算盈亏比例
        pnl_pct = (current_price - entry_price) / entry_price
        
        # 止损检查
        if pnl_pct < -self.stop_loss_pct:
            self.write_log(f"止损触发: {symbol} 亏损 {pnl_pct*100:.2f}%")
            return True
        
        # 止盈检查
        if pnl_pct > self.take_profit_pct:
            self.write_log(f"止盈触发: {symbol} 盈利 {pnl_pct*100:.2f}%")
            return True
        
        return False

    def on_bar(self, bar: BarData):
        """收到 K 线数据"""
        self.am.update_bar(bar)
        
        if not self.am.inited:
            return
        
        # 更新调仓计数
        self.days_since_rebalance += 1
        
        # 检查止损止盈（每天检查）
        if self.pos != 0 and self.check_stop_loss_take_profit(bar):
            if self.pos > 0:
                self.sell(bar.close_price, abs(self.pos))
                if bar.vt_symbol in self.entry_prices:
                    del self.entry_prices[bar.vt_symbol]
            elif self.pos < 0:
                self.cover(bar.close_price, abs(self.pos))
                if bar.vt_symbol in self.entry_prices:
                    del self.entry_prices[bar.vt_symbol]
            return
        
        # 调仓周期检查
        if self.days_since_rebalance < self.rebalance_days:
            return
        
        self.days_since_rebalance = 0
        
        # 识别主线
        self.identify_leading_sectors()
        self.write_log(f"当前主线: {self.leading_sectors}")
        self.write_log(f"行业得分: {self.sector_scores}")
        
        # 计算当前标的强度
        strength = self.calculate_current_strength()
        self.write_log(f"当前标的强度得分: {strength:.2f}")
        
        # 交易逻辑（简化版：只根据强度阈值交易单个标的）
        # 实际应该根据主线选择多个标的
        
        if strength > 60 and self.pos == 0:
            # 强势买入
            size = int(self.fixed_capital / bar.close_price / 100) * 100  # 100股整数
            if size > 0:
                self.buy(bar.close_price, size)
                self.entry_prices[bar.vt_symbol] = bar.close_price
                self.write_log(f"主线买入 {size}股 @ {bar.close_price:.2f}, 强度={strength:.2f}")
                
        elif strength < 40 and self.pos > 0:
            # 弱势卖出
            self.sell(bar.close_price, abs(self.pos))
            if bar.vt_symbol in self.entry_prices:
                del self.entry_prices[bar.vt_symbol]
            self.write_log(f"主线卖出 @ {bar.close_price:.2f}, 强度={strength:.2f}")

        self.put_event()

    def on_order(self, order: OrderData):
        """收到委托回报"""
        pass

    def on_trade(self, trade: TradeData):
        """收到成交回报"""
        self.write_log(
            f"成交: {trade.direction.value} {trade.volume} @ {trade.price:.2f}"
        )
        self.put_event()
