"""
A股主线识别策略 V2 - 先选行业，再选标的

核心流程：
1. 行业筛选：基于行业指标选取候选行业（主线）
2. 个股筛选：在候选行业中挑选强势个股
3. 组合构建：构建最终交易组合

数据流向：
AKShare行业数据 → 行业强度排名 → 候选行业 → 行业成分股 → 个股筛选 → 交易标的
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
from vnpy.trader.constant import Exchange
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import json
import logging

logger = logging.getLogger(__name__)


class MainlineStrategy(CtaTemplate):
    """
    A股主线识别策略 - 完整实现
    
    策略流程：
    =========
    Step 1: 行业层面筛选（宏观）
        - 计算所有行业的强度得分
        - 选取前N个行业作为候选主线
    
    Step 2: 个股层面筛选（微观）
        - 在候选行业中获取成分股
        - 计算个股强度指标
        - 选取各行业龙头股
    
    Step 3: 组合构建与交易
        - 等权或按强度加权配置
        - 定期调仓与止损
    """
    author = "AI Trader"

    # ========== 行业筛选参数 ==========
    sector_scan_interval = 5      # 行业扫描周期（天）
    top_n_sectors = 3             # 选取前N个行业
    
    # 行业强度权重
    sector_momentum_weight = 0.4      # 行业动量权重
    sector_volume_weight = 0.3        # 行业成交量权重
    sector_fund_flow_weight = 0.3     # 资金流向权重
    
    # ========== 个股筛选参数 ==========
    stocks_per_sector = 2         # 每行业选几只股票
    
    # 个股强度权重
    stock_momentum_weight = 0.4       # 个股动量
    stock_volume_weight = 0.2         # 个股成交量
    stock_consistency_weight = 0.2    # 趋势一致性
    stock_market_cap_weight = 0.2     # 市值因子（偏好中大盘）
    
    # ========== 交易参数 ==========
    rebalance_days = 5            # 调仓周期
    max_holdings = 6              # 最大持仓数（top_n_sectors × stocks_per_sector）
    position_pct_per_stock = 0.15  # 单股仓位比例
    
    # 风控参数
    stop_loss_pct = 0.07          # 止损比例
    take_profit_pct = 0.20        # 止盈比例
    trailing_stop_pct = 0.10      # 移动止损

    parameters = [
        # 行业筛选
        "sector_scan_interval", "top_n_sectors",
        "sector_momentum_weight", "sector_volume_weight", "sector_fund_flow_weight",
        # 个股筛选
        "stocks_per_sector",
        "stock_momentum_weight", "stock_volume_weight", 
        "stock_consistency_weight", "stock_market_cap_weight",
        # 交易参数
        "rebalance_days", "max_holdings", "position_pct_per_stock",
        "stop_loss_pct", "take_profit_pct", "trailing_stop_pct",
    ]
    variables = [
        "selected_sectors", "selected_stocks", 
        "sector_scores", "stock_scores",
        "days_to_rebalance", "last_scan_date",
        "entry_prices", "highest_prices",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        
        # 数据管理器
        self.bg = BarGenerator(self.on_bar)
        self.am = ArrayManager(size=100)
        
        # 行业与股票映射配置
        # 格式: {行业名称: {"index_code": "行业指数代码", "stocks": [成分股列表]}}
        self.sector_config: Dict[str, Dict] = {}
        
        # 运行时数据
        self.selected_sectors: List[str] = []      # 当前选中的行业
        self.selected_stocks: List[str] = []       # 当前选中的股票
        self.sector_scores: Dict[str, float] = {}  # 行业得分
        self.stock_scores: Dict[str, float] = {}   # 个股得分
        self.days_to_rebalance = 0
        self.last_scan_date = None
        
        # 持仓管理
        self.entry_prices: Dict[str, float] = {}
        self.highest_prices: Dict[str, float] = {}
        self.current_positions: Dict[str, int] = {}  # 当前持仓 {symbol: volume}
        
        # 初始化配置
        self.init_sector_config()

    def init_sector_config(self):
        """
        初始化行业配置 - 使用申万行业指数代码
        
        申万行业代码查询: ak.index_stock_sw_df()
        """
        self.sector_config = {
            "半导体": {
                "index_code": "801081",  # 申万半导体
                "stocks": ["688981", "603501", "002371", "603893", "300782"],
            },
            "电力设备": {
                "index_code": "801730",  # 申万电力设备（新能源）
                "stocks": ["300750", "002594", "601012", "600438", "002459"],
            },
            "食品饮料": {
                "index_code": "801120",  # 申万食品饮料（白酒）
                "stocks": ["600519", "000858", "000568", "002304", "600809"],
            },
            "医药生物": {
                "index_code": "801150",  # 申万医药生物
                "stocks": ["600276", "000661", "300760", "603259", "600436"],
            },
            "银行": {
                "index_code": "801780",  # 申万银行
                "stocks": ["000001", "600000", "601398", "601288", "601939"],
            },
            "计算机": {
                "index_code": "801750",  # 申万计算机（AI相关）
                "stocks": ["000938", "002415", "600570", "603019", "300033"],
            },
            "国防军工": {
                "index_code": "801740",  # 申万国防军工
                "stocks": ["600893", "600760", "000768", "002179", "600372"],
            },
            "有色金属": {
                "index_code": "801050",  # 申万有色金属
                "stocks": ["601899", "603993", "002460", "600111", "000975"],
            },
        }

    def on_init(self):
        """策略初始化"""
        self.write_log("主线识别策略初始化")
        self.write_log(f"监控行业: {list(self.sector_config.keys())}")
        self.load_bar(30)

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

    # ========== Step 1: 行业筛选 ==========
    
    def calculate_sector_indicators(self, sector_name: str) -> Optional[Dict]:
        """
        计算行业层面指标
        
        需要从外部数据源获取行业指数数据
        简化实现：使用行业成分股的平均表现作为代理
        """
        config = self.sector_config.get(sector_name)
        if not config:
            return None
        
        stocks = config["stocks"]
        
        # 这里简化处理：假设可以通过某种方式获取数据
        # 实际应该调用AKShare获取行业指数数据
        
        # 模拟返回行业指标
        return {
            "momentum_20d": 0.0,      # 20日动量
            "volume_ratio": 1.0,       # 成交量比
            "fund_flow_pct": 0.0,      # 资金流向百分比
        }
    
    def calculate_sector_score(self, sector_name: str) -> float:
        """
        计算行业综合得分
        
        得分 = 动量×0.4 + 成交量×0.3 + 资金流向×0.3
        """
        indicators = self.calculate_sector_indicators(sector_name)
        if not indicators:
            return 0.0
        
        score = (
            self.sector_momentum_weight * indicators["momentum_20d"] +
            self.sector_volume_weight * (indicators["volume_ratio"] - 1) * 50 +
            self.sector_fund_flow_weight * indicators["fund_flow_pct"]
        )
        
        return score
    
    def scan_sectors(self) -> List[Tuple[str, float]]:
        """
        扫描所有行业，返回排序后的行业列表
        
        :return: [(行业名, 得分), ...] 按得分降序
        """
        self.write_log("开始行业扫描...")
        
        scores = {}
        for sector_name in self.sector_config.keys():
            score = self.calculate_sector_score(sector_name)
            scores[sector_name] = score
        
        # 排序
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        self.sector_scores = dict(ranked)
        
        # 选取前N个行业
        self.selected_sectors = [s[0] for s in ranked[:self.top_n_sectors]]
        
        self.write_log(f"行业扫描完成，选中行业: {self.selected_sectors}")
        for sector, score in ranked[:self.top_n_sectors]:
            self.write_log(f"  {sector}: {score:.2f}")
        
        return ranked

    # ========== Step 2: 个股筛选 ==========
    
    def calculate_stock_indicators(self, symbol: str) -> Optional[Dict]:
        """
        计算个股层面指标
        
        需要从外部数据源获取个股数据
        """
        # 简化实现：假设数据可用
        # 实际应该调用AKShare获取个股历史数据
        
        return {
            "momentum_20d": 0.0,
            "volume_ratio": 1.0,
            "trend_consistency": 0.5,  # 趋势一致性（0-1）
            "market_cap": 100,          # 市值（亿）
        }
    
    def calculate_stock_score(self, symbol: str) -> float:
        """
        计算个股综合得分
        
        得分 = 动量×0.4 + 成交量×0.2 + 一致性×0.2 + 市值×0.2
        """
        indicators = self.calculate_stock_indicators(symbol)
        if not indicators:
            return 0.0
        
        # 市值因子：偏好50-500亿中大盘股
        market_cap_score = 0.0
        cap = indicators["market_cap"]
        if 50 <= cap <= 500:
            market_cap_score = 100
        elif cap < 50:
            market_cap_score = cap / 50 * 100
        else:
            market_cap_score = max(0, 100 - (cap - 500) / 10)
        
        score = (
            self.stock_momentum_weight * indicators["momentum_20d"] +
            self.stock_volume_weight * (indicators["volume_ratio"] - 1) * 50 +
            self.stock_consistency_weight * indicators["trend_consistency"] * 100 +
            self.stock_market_cap_weight * market_cap_score
        )
        
        return score
    
    def select_stocks_from_sectors(self) -> List[str]:
        """
        从选中的行业中筛选个股
        
        每行业选取stocks_per_sector只得分最高的股票
        """
        self.write_log("开始个股筛选...")
        
        selected = []
        
        for sector in self.selected_sectors:
            config = self.sector_config.get(sector)
            if not config:
                continue
            
            stocks = config["stocks"]
            
            # 计算每只股票得分
            stock_scores = []
            for symbol in stocks:
                score = self.calculate_stock_score(symbol)
                stock_scores.append((symbol, score))
            
            # 排序选取前N
            stock_scores.sort(key=lambda x: x[1], reverse=True)
            top_stocks = [s[0] for s in stock_scores[:self.stocks_per_sector]]
            
            selected.extend(top_stocks)
            
            self.write_log(f"  {sector}: 选中 {top_stocks}")
        
        self.selected_stocks = selected[:self.max_holdings]
        self.write_log(f"个股筛选完成，共 {len(self.selected_stocks)} 只")
        
        return self.selected_stocks

    # ========== Step 3: 交易执行 ==========
    
    def check_stop_loss_take_profit(self, symbol: str, current_price: float) -> Tuple[bool, str]:
        """
        检查止损止盈
        
        :return: (是否触发, 触发类型)
        """
        if symbol not in self.entry_prices:
            return False, ""
        
        entry_price = self.entry_prices[symbol]
        pnl_pct = (current_price - entry_price) / entry_price
        
        # 止损检查
        if pnl_pct < -self.stop_loss_pct:
            return True, "stop_loss"
        
        # 止盈检查
        if pnl_pct > self.take_profit_pct:
            return True, "take_profit"
        
        # 移动止损检查
        if symbol in self.highest_prices:
            drawdown = (self.highest_prices[symbol] - current_price) / self.highest_prices[symbol]
            if drawdown > self.trailing_stop_pct:
                return True, "trailing_stop"
            
            # 更新最高价
            if current_price > self.highest_prices[symbol]:
                self.highest_prices[symbol] = current_price
        else:
            self.highest_prices[symbol] = current_price
        
        return False, ""
    
    def on_bar(self, bar: BarData):
        """收到 K 线数据"""
        self.am.update_bar(bar)
        
        if not self.am.inited:
            return
        
        current_date = bar.datetime.date()
        logger.info(f"收到{bar.symbol} K 线数据 {current_date} ")
        
        # 更新调仓计数
        self.days_to_rebalance += 1
        
        # 检查是否需要重新扫描行业
        need_sector_scan = (
            self.last_scan_date is None or
            (current_date - self.last_scan_date).days >= self.sector_scan_interval
        )
        
        if need_sector_scan:
            # Step 1: 行业筛选
            self.scan_sectors()
            
            # Step 2: 个股筛选
            self.select_stocks_from_sectors()
            
            self.last_scan_date = current_date
        
        # 检查调仓周期
        if self.days_to_rebalance < self.rebalance_days:
            self.put_event()
            return
        
        self.days_to_rebalance = 0
        
        # Step 3: 执行交易
        self.execute_trading(bar)
        
        self.put_event()
    
    def execute_trading(self, bar: BarData):
        """
        执行交易逻辑
        
        简化实现：只处理当前标的
        实际应该管理多个标的的持仓
        """
        symbol = bar.vt_symbol
        
        # 检查当前标的是否在选中列表中
        is_selected = symbol in self.selected_stocks
        
        # 检查止损止盈
        triggered, trigger_type = self.check_stop_loss_take_profit(symbol, bar.close_price)
        
        if triggered and self.pos != 0:
            # 平仓
            if self.pos > 0:
                self.sell(bar.close_price, abs(self.pos))
            else:
                self.cover(bar.close_price, abs(self.pos))
            
            self.write_log(f"{symbol} 触发{trigger_type}，平仓")
            
            if symbol in self.entry_prices:
                del self.entry_prices[symbol]
            if symbol in self.highest_prices:
                del self.highest_prices[symbol]
            return
        
        # 调仓逻辑
        if is_selected and self.pos == 0:
            # 买入信号
            capital = self.capital * self.position_pct_per_stock
            size = int(capital / bar.close_price / 100) * 100
            
            if size > 0:
                self.buy(bar.close_price, size)
                self.entry_prices[symbol] = bar.close_price
                self.highest_prices[symbol] = bar.close_price
                self.write_log(f"买入 {symbol} {size}股 @ {bar.close_price:.2f}")
                
        elif not is_selected and self.pos != 0:
            # 卖出信号（不在主线列表中）
            if self.pos > 0:
                self.sell(bar.close_price, abs(self.pos))
            else:
                self.cover(bar.close_price, abs(self.pos))
            
            self.write_log(f"卖出 {symbol}（退出主线）")
            
            if symbol in self.entry_prices:
                del self.entry_prices[symbol]
            if symbol in self.highest_prices:
                del self.highest_prices[symbol]

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
