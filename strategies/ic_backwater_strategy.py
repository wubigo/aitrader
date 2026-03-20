"""
IC 股指期货滚贴水套利策略

核心逻辑：
1. 利用股指期货贴水（期货价格 < 现货价格）进行套利
2. 买入期货合约，同时卖出对应的 ETF 或一篮子股票
3. 定期滚动到下一个合约，持续获取贴水收益

适用标的：
- IC: 中证 500 股指期货
- IF: 沪深 300 股指期货  
- IH: 上证 50 股指期货
- IM: 中证 1000 股指期货
"""
from vnpy_ctastrategy import (
    CtaTemplate,
    BarGenerator,
    ArrayManager,
    BarData,
    TickData,
    TradeData,
    OrderData,
)
from vnpy.trader.constant import Direction, Offset
from typing import Dict, List, Optional
import numpy as np


class ICBackwaterArbitrageStrategy(CtaTemplate):
    """
    IC 期货滚贴水套利策略
    
    策略原理：
    1. 当期货出现贴水时（期货价格 < 现货价格）
    2. 做多期货合约（IC 当月/下月合约）
    3. 做空对应的一篮子股票或 ETF（如 500ETF）
    4. 持有至到期或基差收敛后平仓
    5. 滚动到下一个合约继续操作
    
    收益来源：
    - 贴水收敛收益（主要）
    - 股票分红收益
    - 现金管理收益
    """
    
    author = "AI Trader"
    
    # ========== 策略参数 ==========
    
    # 合约配置
    spot_symbol = "510500.SSE"      # 现货标的（500ETF）
    futures_symbol = "IC.SFF"       # 期货主力合约
    
    # 开仓条件
    open_basis_threshold = -0.02    # 开仓基差阈值（-2% 贴水）
    min_open_volume = 1             # 最小开仓手数
    
    # 平仓条件
    close_basis_threshold = -0.005  # 平仓基差阈值（-0.5%）
    max_holding_days = 20           # 最大持有天数
    stop_loss_pct = 0.03            # 止损比例 3%
    
    # 滚动参数
    roll_days_before_expiry = 5     # 到期前 N 天开始滚动
    roll_spread_threshold = 0.005   # 滚动价差阈值（0.5%）
    
    # 资金管理
    position_ratio = 0.8            # 仓位比例
    cash_reserve = 0.2              # 现金预留比例
    
    parameters = [
        "spot_symbol", "futures_symbol",
        "open_basis_threshold", "min_open_volume",
        "close_basis_threshold", "max_holding_days", "stop_loss_pct",
        "roll_days_before_expiry", "roll_spread_threshold",
        "position_ratio", "cash_reserve",
    ]
    
    variables = [
        "current_basis",           # 当前基差
        "futures_pos",             # 期货持仓
        "spot_pos",                # 现货持仓
        "entry_basis",             # 入场基差
        "entry_date",              # 入场日期
        "holding_days",            # 持有天数
        "contract_month",          # 当前合约月份
        "next_contract_month",     # 下一合约月份
    ]
    
    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        
        # K 线管理
        self.bg = BarGenerator(self.on_bar)
        self.am = ArrayManager(size=100)
        
        # 持仓数据
        self.futures_pos: int = 0      # 期货持仓（正数为多）
        self.spot_pos: int = 0         # 现货持仓（正数为空）
        
        # 交易记录
        self.entry_basis: float = 0.0
        self.entry_date = None
        self.holding_days: int = 0
        
        # 合约信息
        self.contract_month: str = ""      # 当前合约月份，如 "2406"
        self.next_contract_month: str = "" # 下一合约月份
        
        # 价格数据
        self.current_basis: float = 0.0
        self.futures_price: float = 0.0
        self.spot_price: float = 0.0
        
        # 状态标志
        self.is_position_opened = False    # 是否已开仓
        self.is_rolling = False            # 是否正在滚动
    
    def on_init(self):
        """策略初始化"""
        self.write_log("IC 滚贴水套利策略初始化")
        self.load_bar(30)
    
    def on_start(self):
        """策略启动"""
        self.write_log("策略启动")
        self.update_contract_info()
        self.put_event()
    
    def on_stop(self):
        """策略停止"""
        self.write_log("策略停止")
        self.write_log(f"最终持仓：期货 {self.futures_pos} 手，现货 {self.spot_pos} 手")
        self.put_event()
    
    def on_tick(self, tick: TickData):
        """收到 Tick 数据"""
        self.bg.update_tick(tick)
    
    def calculate_basis(self, futures_price: float, spot_price: float) -> float:
        """
        计算基差率
        
        基差率 = (期货价格 - 现货价格) / 现货价格
        
        :return: 基差率（负数表示贴水）
        """
        if spot_price == 0:
            return 0.0
        return (futures_price - spot_price) / spot_price
    
    def get_current_futures_price(self) -> float:
        """获取当前期货价格"""
        # 简化处理：使用最新价
        return self.futures_price
    
    def get_spot_price(self) -> float:
        """获取现货价格"""
        # 简化处理：使用 ETF 价格作为现货代理
        return self.spot_price
    
    def update_contract_info(self):
        """更新合约信息"""
        # 从 vt_symbol 解析合约月份
        # 例如："IC2406.SFF" -> "2406"
        parts = self.vt_symbol.split(".")
        if len(parts) >= 1:
            symbol_part = parts[0]
            # 提取数字部分作为合约月份
            month_str = ''.join(filter(str.isdigit, symbol_part))
            if len(month_str) >= 4:
                self.contract_month = month_str[-4:]
        
        # 计算下一合约月份
        if self.contract_month:
            year = int(self.contract_month[:2])
            month = int(self.contract_month[2:])
            
            # 下月合约
            next_month = month + 1
            next_year = year
            if next_month > 12:
                next_month = 1
                next_year += 1
            
            self.next_contract_month = f"{next_year:02d}{next_month:02d}"
    
    def check_open_condition(self) -> bool:
        """检查开仓条件"""
        # 条件 1: 基差低于阈值（贴水足够大）
        if self.current_basis >= self.open_basis_threshold:
            return False
        
        # 条件 2: 没有持仓
        if self.is_position_opened:
            return False
        
        # 条件 3: 距离到期还有足够时间（简化判断）
        # 实际应该查询交易所的到期日
        
        return True
    
    def check_close_condition(self) -> bool:
        """检查平仓条件"""
        if not self.is_position_opened:
            return False
        
        # 条件 1: 基差收敛到阈值内
        if self.current_basis >= self.close_basis_threshold:
            self.write_log(f"基差收敛至 {self.current_basis:.2%}，触发平仓")
            return True
        
        # 条件 2: 超过最大持有天数
        if self.holding_days >= self.max_holding_days:
            self.write_log(f"持有{self.holding_days}天，达到最大持有期")
            return True
        
        # 条件 3: 止损
        if self.entry_basis != 0:
            pnl_ratio = (self.current_basis - self.entry_basis) / abs(self.entry_basis)
            if pnl_ratio < -self.stop_loss_pct:
                self.write_log(f"亏损{pnl_ratio:.2%}，触发止损")
                return True
        
        return False
    
    def check_roll_condition(self) -> bool:
        """检查滚动条件"""
        if not self.is_position_opened:
            return False
        
        # 简化判断：假设每月第三个周五为交割日
        # 实际应该查询交易所公告
        
        # 这里用固定天数模拟
        days_to_expiry = 10  # 假设距离到期还有 10 天
        
        if days_to_expiry <= self.roll_days_before_expiry:
            self.write_log(f"距离到期{days_to_expiry}天，准备滚动")
            return True
        
        return False
    
    def execute_open(self, bar: BarData):
        """执行开仓"""
        # 计算开仓数量
        capital = self.capital * self.position_ratio
        futures_value = bar.close_price * 200  # IC 合约乘数 200 元/点
        volume = int(capital / futures_value)
        volume = max(volume, self.min_open_volume)
        
        # 开多期货
        self.buy(bar.close_price, volume)
        self.futures_pos = volume
        
        # 开空现货（简化：只记录，实际需要融券）
        # 实际中可以用 500ETF 替代
        self.write_log(f"开仓：买入{volume}手 IC@{bar.close_price:.2f}")
        self.write_log(f"当前基差：{self.current_basis:.2%}")
        
        # 记录入场信息
        self.entry_basis = self.current_basis
        self.entry_date = bar.datetime
        self.holding_days = 0
        self.is_position_opened = True
    
    def execute_close(self, bar: BarData):
        """执行平仓"""
        if self.futures_pos > 0:
            # 平掉期货多单
            self.sell(bar.close_price, abs(self.futures_pos))
            
            # 平掉现货空单（如果有）
            # 实际中需要买回 ETF
        
        self.write_log(f"平仓：卖出{abs(self.futures_pos)}手 IC@{bar.close_price:.2f}")
        self.write_log(f"平仓基差：{self.current_basis:.2%}")
        
        # 重置状态
        self.futures_pos = 0
        self.spot_pos = 0
        self.is_position_opened = False
        self.entry_basis = 0
        self.holding_days = 0
    
    def execute_roll(self, bar: BarData, next_contract_price: float):
        """执行滚动操作"""
        if self.futures_pos <= 0:
            return
        
        # 计算价差
        price_diff = (next_contract_price - bar.close_price) / bar.close_price
        
        if price_diff > self.roll_spread_threshold:
            self.write_log(f"远月合约升水{price_diff:.2%}，执行滚动")
            
            # 平掉近月合约
            self.sell(bar.close_price, abs(self.futures_pos))
            
            # 开远月合约（需要在另一个合约上操作）
            # 简化处理：这里只记录
            self.write_log(f"计划开仓远月合约 {self.next_contract_month}")
            
            # 更新合约信息
            self.contract_month = self.next_contract_month
            self.is_rolling = False
    
    def on_bar(self, bar: BarData):
        """收到 K 线数据"""
        self.am.update_bar(bar)
        
        if not self.am.inited:
            return
        
        # 更新价格
        self.futures_price = bar.close_price
        
        # 获取现货价格（简化：使用固定值或外部数据）
        # 实际中应该从行情源获取 500ETF 价格
        self.spot_price = self.get_spot_price()
        if self.spot_price == 0:
            # 如果没有现货价格，使用期货价格近似
            self.spot_price = bar.close_price * 0.99  # 假设 1% 贴水
        
        # 计算基差
        self.current_basis = self.calculate_basis(self.futures_price, self.spot_price)
        
        # 更新持有天数
        if self.is_position_opened and self.entry_date:
            self.holding_days = (bar.datetime - self.entry_date).days
        
        # 交易逻辑
        if not self.is_position_opened:
            # 检查开仓条件
            if self.check_open_condition():
                self.execute_open(bar)
        else:
            # 检查滚动条件
            if self.check_roll_condition():
                self.is_rolling = True
                # 这里简化处理，实际需要查询远月合约价格
                # next_price = self.get_next_contract_price()
                # self.execute_roll(bar, next_price)
            
            # 检查平仓条件
            elif self.check_close_condition():
                self.execute_close(bar)
        
        # 输出状态
        self.write_log(f"基差：{self.current_basis:.2%}, "
                      f"持仓：{self.futures_pos}, "
                      f"持有：{self.holding_days}天")
        
        self.put_event()
    
    def on_order(self, order: OrderData):
        """收到委托回报"""
        pass
    
    def on_trade(self, trade: TradeData):
        """收到成交回报"""
        self.write_log(
            f"成交：{trade.direction.value} {trade.offset.value} "
            f"{trade.volume}手 @ {trade.price:.2f}"
        )
        self.put_event()


# ========== 辅助函数 ==========

def get_ic_contracts() -> List[str]:
    """
    获取所有 IC 合约代码
    
    :return: 合约列表，如 ["IC2406", "IC2407", "IC2408", "IC2409"]
    """
    from datetime import datetime
    
    current_year = datetime.now().year % 100
    current_month = datetime.now().month
    
    contracts = []
    for i in range(12):  # 未来 12 个月
        month = current_month + i
        year = current_year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        contract = f"IC{year:02d}{month:02d}"
        contracts.append(contract)
    
    return contracts


def calculate_annualized_basis(basis: float, days_to_expiry: int) -> float:
    """
    计算年化基差
    
    :param basis: 基差率
    :param days_to_expiry: 到期天数
    :return: 年化基差率
    """
    if days_to_expiry <= 0:
        return 0.0
    return basis * (365 / days_to_expiry)
