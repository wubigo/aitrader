from vnpy_ctastrategy import (
    CtaTemplate,
    StopOrder,
    TickData,
    BarData,
    TradeData,
    OrderData,
    BarGenerator,
    ArrayManager
)
from vnpy_ctastrategy import CtaTemplate, BarGenerator, ArrayManager
from vnpy.trader.constant import Interval
import pandas as pd
import numpy as np
from typing import List


class MultiFactorStockPicker(CtaTemplate):
    """A股多因子选股策略"""
    author = "Perplexity"

    # 参数
    n_stocks = 10  # 选前N只股票
    rank_period = 20  # 因子计算窗口
    rebalance_days = 5  # 调仓周期（天）

    # 因子权重
    w_size = 0.2
    w_valuation = 0.3
    w_momentum = 0.3
    w_quality = 0.2

    parameters = ["n_stocks", "rank_period", "rebalance_days", "w_size", "w_valuation", "w_momentum", "w_quality"]
    variables = ["factor_scores"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.bg = BarGenerator(self.on_bar, 1, self.on_1d_bar)
        self.am = ArrayManager(size=100)
        self.stock_pool: List[str] = []  # 选股池
        self.last_rebalance = 0

        # 假设全市场数据已加载到 self.market_data (pd.DataFrame)
        self.init_stock_universe()

    def init_stock_universe(self):
        """初始化股票池（沪深300成分股示例）"""
        self.stock_universe = [
            "000001.SZSE", "600000.SSE", "000002.SZSE"  # ... 实际用AKShare获取全池
        ]

    def calculate_factors(self, symbol: str) -> dict:
        """计算单只股票因子分数"""
        if symbol not in self.market_data.columns:
            return {}

        df = self.market_data[symbol]
        price = df['close'].tail(self.rank_period)

        # 因子计算
        size_factor = np.log(price.iloc[-1])  # 简化：价格代理市值
        valuation_factor = 1 / (price.iloc[-1] / price.rolling(252).mean())  # 市净率近似
        momentum_factor = (price.iloc[-1] / price.iloc[0] - 1)
        volatility_factor = -price.pct_change().std()  # 低波动正收益

        # 标准化到[0,1]
        factors = np.array([size_factor, valuation_factor, momentum_factor, volatility_factor])
        factors = (factors - factors.mean()) / factors.std()

        score = (self.w_size * factors[0] +
                 self.w_valuation * factors[1] +
                 self.w_momentum * factors[2] +
                 self.w_quality * factors[3])

        return {"score": score, "close": price.iloc[-1]}

    def daily_rebalance(self):
        """每日调仓选股"""
        scores = {}
        for symbol in self.stock_universe[:100]:  # 测试前100只
            factors = self.calculate_factors(symbol)
            if factors:
                scores[symbol] = factors["score"]

        # 选Top N
        top_stocks = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:self.n_stocks]
        self.stock_pool = [s[0] for s in top_stocks]
        self.write_log(f"选股完成：{self.stock_pool}")

    def on_1d_bar(self, bar):
        """日线处理"""
        self.am.update_bar(bar)
        if not self.am.inited:
            return

        day_count = self.am.count % self.rebalance_days
        if day_count == 0:
            self.daily_rebalance()

        # 池内等权调仓逻辑
        if self.stock_pool and bar.vt_symbol in self.stock_pool:
            if self.pos == 0:
                self.buy(bar.vt_symbol, bar.close_price * 1.01, 1000)
            elif self.pos > 0 and bar.vt_symbol not in self.stock_pool:
                self.sell(bar.vt_symbol, bar.close_price * 0.99, abs(self.pos))
