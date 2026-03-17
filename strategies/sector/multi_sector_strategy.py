"""
多行业主线轮动策略 - 完整实现
支持同时监控和交易多个行业ETF或龙头股
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
from typing import Dict, List, Optional
import numpy as np
import json


class MultiSectorRotationStrategy(CtaTemplate):
    """
    多行业主线轮动策略
    
    核心逻辑：
    1. 监控多个行业ETF或代表股
    2. 每日计算各行业强度得分
    3. 只持有得分前N的行业
    4. 定期轮动调仓
    
    适用标的：行业ETF（如科技ETF、医药ETF等）
    """
    author = "AI Trader"

    # 监控的行业标的（在vt_symbol中配置多个，用逗号分隔）
    # 例如: "510050.SSE,512000.SSE,512010.SSE"  # 50ETF,券商ETF,医药ETF
    
    # 策略参数
    ranking_period = 20       # 强度计算周期
    top_n_sectors = 2         # 持有前N个强势行业
    rebalance_days = 5        # 调仓周期
    
    # 强度计算权重
    momentum_weight = 0.5     # 动量权重
    volume_weight = 0.3       # 成交量权重
    volatility_penalty = 0.2  # 高波动惩罚
    
    # 风控参数
    max_position_pct = 0.5    # 单标的最大仓位比例
    stop_loss_pct = 0.05      # 止损比例
    trailing_stop_pct = 0.08  # 移动止损

    parameters = [
        "ranking_period", "top_n_sectors", "rebalance_days",
        "momentum_weight", "volume_weight", "volatility_penalty",
        "max_position_pct", "stop_loss_pct", "trailing_stop_pct",
    ]
    variables = [
        "sector_scores", "current_holdings", 
        "next_holdings", "days_to_rebalance",
        "highest_prices",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        
        # 解析多个标的
        self.symbols = [s.strip() for s in vt_symbol.split(",")]
        
        # 为每个标的创建ArrayManager
        self.ams: Dict[str, ArrayManager] = {}
        self.bgs: Dict[str, BarGenerator] = {}
        
        for symbol in self.symbols:
            self.ams[symbol] = ArrayManager(size=100)
            self.bgs[symbol] = BarGenerator(self.on_bar)
        
        # 运行时数据
        self.sector_scores: Dict[str, float] = {}
        self.current_holdings: List[str] = []  # 当前持有的标的
        self.next_holdings: List[str] = []     # 计划调仓的标的
        self.days_to_rebalance = 0
        self.highest_prices: Dict[str, float] = {}  # 用于移动止损
        self.entry_prices: Dict[str, float] = {}

    def on_init(self):
        """策略初始化"""
        self.write_log(f"多行业轮动策略初始化")
        self.write_log(f"监控标的: {self.symbols}")
        self.load_bar(self.ranking_period + 10)

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
        symbol = tick.vt_symbol
        if symbol in self.bgs:
            self.bgs[symbol].update_tick(tick)

    def calculate_momentum_score(self, symbol: str) -> float:
        """
        计算动量得分
        
        使用多周期动量综合评分：
        - 5日动量 × 0.4
        - 10日动量 × 0.3
        - 20日动量 × 0.3
        """
        am = self.ams.get(symbol)
        if not am or not am.inited:
            return 0.0
        
        close = am.close
        
        # 多周期动量
        mom_5 = (close[-1] - close[-5]) / close[-5] * 100 if len(close) >= 5 else 0
        mom_10 = (close[-1] - close[-10]) / close[-10] * 100 if len(close) >= 10 else 0
        mom_20 = (close[-1] - close[-20]) / close[-20] * 100 if len(close) >= 20 else 0
        
        # 加权综合
        score = mom_5 * 0.4 + mom_10 * 0.3 + mom_20 * 0.3
        
        return score

    def calculate_volume_score(self, symbol: str) -> float:
        """
        计算成交量得分
        
        近期成交量相对历史均量的放大程度
        """
        am = self.ams.get(symbol)
        if not am or not am.inited:
            return 0.0
        
        volume = am.volume
        if len(volume) < self.ranking_period:
            return 0.0
        
        # 近期均量 vs 历史均量
        recent_vol = np.mean(volume[-5:])
        hist_vol = np.mean(volume[-self.ranking_period:-5])
        
        if hist_vol == 0:
            return 0.0
        
        volume_ratio = recent_vol / hist_vol
        
        # 成交量放大得分（1.0为基准，最高2.0得满分）
        score = min(100, (volume_ratio - 0.5) * 66.7)
        
        return score

    def calculate_volatility_penalty(self, symbol: str) -> float:
        """
        计算波动率惩罚
        
        波动率过高会降低得分
        """
        am = self.ams.get(symbol)
        if not am or not am.inited:
            return 0.0
        
        # 使用ATR计算波动率
        atr = am.atr(14)
        close = am.close[-1]
        
        if close == 0:
            return 0.0
        
        atr_pct = atr / close * 100
        
        # 波动率超过3%开始惩罚
        if atr_pct > 3.0:
            penalty = (atr_pct - 3.0) * 10  # 每超1%扣10分
            return min(50, penalty)  # 最高扣50分
        
        return 0.0

    def calculate_sector_score(self, symbol: str) -> float:
        """
        计算行业综合得分
        """
        momentum = self.calculate_momentum_score(symbol)
        volume = self.calculate_volume_score(symbol)
        volatility = self.calculate_volatility_penalty(symbol)
        
        score = (
            self.momentum_weight * momentum +
            self.volume_weight * volume -
            self.volatility_penalty * volatility
        )
        
        return score

    def rank_sectors(self) -> List[tuple]:
        """
        对所有行业进行排名
        
        :return: [(symbol, score), ...] 按得分降序
        """
        scores = {}
        
        for symbol in self.symbols:
            score = self.calculate_sector_score(symbol)
            scores[symbol] = score
        
        # 排序
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        self.sector_scores = dict(ranked)
        
        return ranked

    def check_stop_loss(self, symbol: str, current_price: float) -> bool:
        """检查是否触发止损"""
        if symbol not in self.entry_prices:
            return False
        
        entry_price = self.entry_prices[symbol]
        loss_pct = (current_price - entry_price) / entry_price
        
        if loss_pct < -self.stop_loss_pct:
            self.write_log(f"{symbol} 止损触发: 亏损 {loss_pct*100:.2f}%")
            return True
        
        return False

    def check_trailing_stop(self, symbol: str, current_price: float) -> bool:
        """检查移动止损"""
        if symbol not in self.highest_prices:
            self.highest_prices[symbol] = current_price
            return False
        
        # 更新最高价
        if current_price > self.highest_prices[symbol]:
            self.highest_prices[symbol] = current_price
            return False
        
        # 计算回撤
        drawdown = (self.highest_prices[symbol] - current_price) / self.highest_prices[symbol]
        
        if drawdown > self.trailing_stop_pct:
            self.write_log(f"{symbol} 移动止损触发: 回撤 {drawdown*100:.2f}%")
            return True
        
        return False

    def on_bar(self, bar: BarData):
        """收到 K 线数据"""
        symbol = bar.vt_symbol
        
        # 更新对应标的的ArrayManager
        if symbol in self.ams:
            self.ams[symbol].update_bar(bar)
        
        # 只处理第一个标的的bar作为触发（假设所有标的同步）
        if symbol != self.symbols[0]:
            return
        
        # 检查所有标的的数据是否准备就绪
        for sym, am in self.ams.items():
            if not am.inited:
                return
        
        # 更新调仓计数
        self.days_to_rebalance += 1
        
        # 检查止损（每天检查所有持仓）
        for sym in self.current_holdings[:]:
            if sym in self.ams:
                current_price = self.ams[sym].close[-1]
                
                if self.check_stop_loss(sym, current_price) or \
                   self.check_trailing_stop(sym, current_price):
                    # 触发止损，标记为需要卖出
                    if sym in self.current_holdings:
                        self.current_holdings.remove(sym)
                    # 实际交易在调仓时统一处理
        
        # 调仓周期检查
        if self.days_to_rebalance < self.rebalance_days:
            self.put_event()
            return
        
        self.days_to_rebalance = 0
        
        # 行业排名
        ranked_sectors = self.rank_sectors()
        
        self.write_log(f"\n{'='*50}")
        self.write_log("行业排名:")
        for i, (sym, score) in enumerate(ranked_sectors[:5], 1):
            self.write_log(f"  {i}. {sym}: {score:.2f}")
        
        # 选择前N个行业
        self.next_holdings = [s[0] for s in ranked_sectors[:self.top_n_sectors]]
        
        self.write_log(f"目标持仓: {self.next_holdings}")
        self.write_log(f"当前持仓: {self.current_holdings}")
        
        # 执行调仓
        self.execute_rebalance(bar)
        
        self.put_event()

    def execute_rebalance(self, bar: BarData):
        """
        执行调仓
        
        卖出不在目标列表的持仓，买入目标列表中未持有的
        """
        # 计算每标的仓位
        capital_per_sector = self.capital * self.max_position_pct
        
        # 卖出
        for sym in self.current_holdings[:]:
            if sym not in self.next_holdings:
                # 需要卖出
                if sym == bar.vt_symbol and self.pos != 0:
                    if self.pos > 0:
                        self.sell(bar.close_price, abs(self.pos))
                    elif self.pos < 0:
                        self.cover(bar.close_price, abs(self.pos))
                    
                    self.write_log(f"卖出 {sym}")
                    
                    if sym in self.entry_prices:
                        del self.entry_prices[sym]
                    if sym in self.highest_prices:
                        del self.highest_prices[sym]
                    
                    self.current_holdings.remove(sym)
        
        # 买入
        for sym in self.next_holdings:
            if sym not in self.current_holdings:
                # 需要买入
                if sym == bar.vt_symbol:
                    size = int(capital_per_sector / bar.close_price / 100) * 100
                    if size > 0:
                        self.buy(bar.close_price, size)
                        self.entry_prices[sym] = bar.close_price
                        self.highest_prices[sym] = bar.close_price
                        
                        self.write_log(f"买入 {sym} {size}股 @ {bar.close_price:.2f}")
                        self.current_holdings.append(sym)
        
        # 更新持仓列表
        self.current_holdings = self.next_holdings.copy()

    def on_order(self, order: OrderData):
        """收到委托回报"""
        pass

    def on_trade(self, trade: TradeData):
        """收到成交回报"""
        self.write_log(
            f"成交: {trade.vt_symbol} {trade.direction.value} "
            f"{trade.volume} @ {trade.price:.2f}"
        )
        self.put_event()
