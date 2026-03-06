# A股动量因子模块
# A-Share Momentum Factor Module
"""
动量因子是量化投资中最重要的因子之一。本模块提供多种动量因子的计算方法：

1. 简单动量 (Simple Momentum): 过去N日累计收益率
2. 相对动量 (Relative Momentum): 相对于基准的超额收益
3. 波动率调整动量 (Risk-Adjusted Momentum): ICIR加权动量
4. 时间加权动量 (Time-Weighted Momentum): 指数加权收益率
5. 行业内动量 (Industry Momentum): 行业内相对排名
6. 加速动量 (Acceleration Momentum): 动量变化率

因子预处理：
- 去极值处理 (MAD/百分位法)
- 标准化处理 (Z-Score)
"""

import pandas as pd
import numpy as np
from typing import Optional, Union, List
from datetime import datetime, timedelta


class MomentumFactor:
    """A股动量因子计算器"""
    
    def __init__(self, data: pd.DataFrame, price_col: str = 'close', 
                 date_col: str = 'date', code_col: str = 'code'):
        """
        初始化动量因子计算器
        
        Parameters:
        -----------
        data : pd.DataFrame
            股票数据，包含价格、日期、股票代码
        price_col : str
            价格列名，默认 'close'
        date_col : str
            日期列名，默认 'date'
        code_col : str
            股票代码列名，默认 'code'
        """
        self.data = data.copy()
        self.price_col = price_col
        self.date_col = date_col
        self.code_col = code_col
        
        # 确保数据按日期排序
        self.data = self.data.sort_values([self.code_col, self.date_col])
        
    def calculate_returns(self, periods: int = 1) -> pd.DataFrame:
        """
        计算收益率
        
        Parameters:
        -----------
        periods : int
            回看天数，默认1天
            
        Returns:
        --------
        pd.DataFrame : 包含收益率的数据
        """
        df = self.data.copy()
        df['return'] = df.groupby(self.code_col)[self.price_col].pct_change(periods)
        return df
    
    def simple_momentum(self, window: int = 20, min_periods: int = None) -> pd.DataFrame:
        """
        简单动量因子：过去N日累计收益率
        
        公式: Mom_{i,t} = (P_t / P_{t-N}) - 1
        
        Parameters:
        -----------
        window : int
            回看天数，常用值：20日(短期)、60日(中期)、120日/250日(长期)
        min_periods : int
            最小有效天数，默认等于window
            
        Returns:
        --------
        pd.DataFrame : 包含动量因子值
        """
        if min_periods is None:
            min_periods = window
            
        df = self.data.copy()
        
        # 计算N日累计收益率
        df['momentum'] = df.groupby(self.code_col)[self.price_col].transform(
            lambda x: x.pct_change(window)
        )
        
        # 标记有效数据
        df['momentum_valid'] = df.groupby(self.code_col)[self.price_col].transform(
            lambda x: x.rolling(window=window, min_periods=min_periods).count()
        ) >= min_periods
        
        return df
    
    def log_momentum(self, window: int = 20) -> pd.DataFrame:
        """
        对数动量因子：使用对数收益率
        
        公式: Mom_{i,t} = ln(P_t / P_{t-N})
        
        Parameters:
        -----------
        window : int
            回看天数
            
        Returns:
        --------
        pd.DataFrame : 包含对数动量因子值
        """
        df = self.data.copy()
        
        df['log_return'] = df.groupby(self.code_col)[self.price_col].transform(
            lambda x: np.log(x / x.shift(window))
        )
        df.rename(columns={'log_return': 'log_momentum'}, inplace=True)
        
        return df
    
    def time_weighted_momentum(self, window: int = 60, decay: float = 0.9) -> pd.DataFrame:
        """
        时间加权动量因子：指数加权收益率
        
        公式: Mom_{i,t} = Σ(weight_i * return_i), weight按时间指数衰减
        
        Parameters:
        -----------
        window : int
            回看天数
        decay : float
            衰减因子，越接近1越看重近期
            
        Returns:
        --------
        pd.DataFrame : 包含时间加权动量因子
        """
        df = self.data.copy()
        
        def calc_ewm_return(prices):
            """计算指数加权收益率"""
            returns = prices.pct_change()
            # 指数权重
            weights = np.array([decay ** (window - i - 1) for i in range(window)])
            weights = weights / weights.sum()
            # 加权收益率
            ewm_return = (returns.rolling(window=window).apply(
                lambda x: np.sum(x[-min(len(x), window):] * weights[-len(x):]) 
                if len(x) > 0 else np.nan,
                raw=False
            ))
            return ewm_return
        
        df['tw_momentum'] = df.groupby(self.code_col)[self.price_col].transform(
            calc_ewm_return
        )
        
        return df
    
    def relative_momentum(self, benchmark_col: str = 'benchmark', window: int = 60) -> pd.DataFrame:
        """
        相对动量因子：相对于基准的超额收益
        
        公式: RelMom_{i,t} = Mom_{i,t} - Mom_{bench,t}
        
        Parameters:
        -----------
        benchmark_col : str
            基准价格列名
        window : int
            回看天数
            
        Returns:
        --------
        pd.DataFrame : 包含相对动量因子
        """
        df = self.data.copy()
        
        # 计算个股动量
        df['stock_momentum'] = df.groupby(self.code_col)[self.price_col].transform(
            lambda x: x.pct_change(window)
        )
        
        # 计算基准动量
        df['benchmark_momentum'] = df[benchmark_col].pct_change(window)
        
        # 相对动量
        df['relative_momentum'] = df['stock_momentum'] - df['benchmark_momentum']
        
        return df
    
    def risk_adjusted_momentum(self, window: int = 60, vol_window: int = 20) -> pd.DataFrame:
        """
        风险调整动量：动量除以波动率
        
        公式: RAMom_{i,t} = Mom_{i,t} / Vol_{i,t}
        
        Parameters:
        -----------
        window : int
            动量回看天数
        vol_window : int
            波动率计算天数
            
        Returns:
        --------
        pd.DataFrame : 包含风险调整动量因子
        """
        df = self.data.copy()
        
        # 计算动量
        df['momentum'] = df.groupby(self.code_col)[self.price_col].transform(
            lambda x: x.pct_change(window)
        )
        
        # 计算波动率
        df['volatility'] = df.groupby(self.code_col)[self.price_col].transform(
            lambda x: x.pct_change().rolling(window=vol_window).std() * np.sqrt(252)
        )
        
        # 风险调整动量
        df['ra_momentum'] = df['momentum'] / df['volatility']
        
        return df
    
    def acceleration_momentum(self, short_window: int = 20, long_window: int = 60) -> pd.DataFrame:
        """
        加速动量因子：动量的变化率
        
        公式: AccMom_{i,t} = Mom_{i,t}^{short} - Mom_{i,t}^{long}
        
        或者使用一阶差分: AccMom = Mom_t - Mom_{t-1}
        
        Parameters:
        -----------
        short_window : int
            短期回看天数
        long_window : int
            长期回看天数
            
        Returns:
        --------
        pd.DataFrame : 包含加速动量因子
        """
        df = self.data.copy()
        
        # 计算短期动量
        df['short_momentum'] = df.groupby(self.code_col)[self.price_col].transform(
            lambda x: x.pct_change(short_window)
        )
        
        # 计算长期动量
        df['long_momentum'] = df.groupby(self.code_col)[self.price_col].transform(
            lambda x: x.pct_change(long_window)
        )
        
        # 加速动量（动量加速度）
        df['acceleration_momentum'] = df['short_momentum'] - df['long_momentum']
        
        return df
    
    def industry_relative_momentum(self, industry_col: str = 'industry', 
                                    window: int = 60) -> pd.DataFrame:
        """
        行业内相对动量：相对于行业的超额收益
        
        公式: IndRelMom_{i,t} = Mom_{i,t} - Mom_{industry,t}
        
        Parameters:
        -----------
        industry_col : str
            行业列名
        window : int
            回看天数
            
        Returns:
        --------
        pd.DataFrame : 包含行业内相对动量因子
        """
        df = self.data.copy()
        
        # 计算个股动量
        df['stock_momentum'] = df.groupby(self.code_col)[self.price_col].transform(
            lambda x: x.pct_change(window)
        )
        
        # 计算行业动量
        df['industry_momentum'] = df.groupby([self.date_col, industry_col])[self.price_col].transform(
            lambda x: x.pct_change(window)
        )
        
        # 行业内相对动量
        df['industry_relative_momentum'] = df['stock_momentum'] - df['industry_momentum']
        
        return df
    
    def momentum_ranking(self, window: int = 60, top_pct: float = 0.2) -> pd.DataFrame:
        """
        动量排名因子：计算动量在所有股票中的排名分位数
        
        Parameters:
        -----------
        window : int
            回看天数
        top_pct : float
            取前百分之几的股票
            
        Returns:
        --------
        pd.DataFrame : 包含动量排名因子
        """
        df = self.data.copy()
        
        # 计算动量
        df['momentum'] = df.groupby(self.code_col)[self.price_col].transform(
            lambda x: x.pct_change(window)
        )
        
        # 计算排名（分位数）
        df['momentum_rank'] = df.groupby(self.date_col)['momentum'].rank(
            pct=True, ascending=True
        )
        
        # 标记动量股
        df['is_top_momentum'] = df['momentum_rank'] >= (1 - top_pct)
        
        return df
    
    def cross_sectional_momentum(self, windows: List[int] = [20, 60, 120]) -> pd.DataFrame:
        """
        截面动量因子：结合多期动量
        
        公式: CSMom = w1 * Mom_20 + w2 * Mom_60 + w3 * Mom_120
        
        Parameters:
        -----------
        windows : List[int]
            多期回看天数列表
            
        Returns:
        --------
        pd.DataFrame : 包含截面动量因子
        """
        df = self.data.copy()
        
        # 计算各期动量
        for w in windows:
            df[f'momentum_{w}'] = df.groupby(self.code_col)[self.price_col].transform(
                lambda x: x.pct_change(w)
            )
        
        # 等权重组合
        n = len(windows)
        momentum_cols = [f'momentum_{w}' for w in windows]
        df['cross_momentum'] = df[momentum_cols].mean(axis=1)
        
        return df
    
    def compute_all_momentum(self) -> pd.DataFrame:
        """
        计算所有基础动量因子
        
        Returns:
        --------
        pd.DataFrame : 包含所有动量因子
        """
        df = self.data.copy()
        
        # 各周期动量
        for window in [20, 60, 120, 250]:
            df[f'momentum_{window}d'] = df.groupby(self.code_col)[self.price_col].transform(
                lambda x: x.pct_change(window)
            )
        
        # 波动率
        for window in [20, 60]:
            df[f'volatility_{window}d'] = df.groupby(self.code_col)[self.price_col].transform(
                lambda x: x.pct_change().rolling(window).std() * np.sqrt(252)
            )
        
        # 风险调整动量
        df['ra_momentum_60d'] = df['momentum_60d'] / df['volatility_60d']
        
        # 加速动量
        df['accel_momentum'] = df['momentum_20d'] - df['momentum_60d']
        
        return df


class MomentumFactorProcessor:
    """动量因子预处理器：去极值和标准化"""
    
    @staticmethod
    def winsorize(df: pd.DataFrame, cols: List[str], 
                  method: str = 'mad', limits: float = 3.0) -> pd.DataFrame:
        """
        去极值处理
        
        Parameters:
        -----------
        df : pd.DataFrame
            输入数据
        cols : List[str]
            需要去极值的列名
        method : str
            方法，'mad' (中位数绝对偏差法) 或 'percentile' (百分位法)
        limits : float
            MAD法：几倍MAD；百分位法：上下限百分位
            
        Returns:
        --------
        pd.DataFrame : 去极值后的数据
        """
        result = df.copy()
        
        for col in cols:
            if col not in df.columns:
                continue
                
            if method == 'mad':
                # MAD法
                median = result[col].median()
                mad = (result[col] - median).abs().median()
                lower = median - limits * mad
                upper = median + limits * mad
            else:
                # 百分位法
                lower = result[col].quantile(limits / 100)
                upper = result[col].quantile(1 - limits / 100)
            
            # 截断
            result[col] = result[col].clip(lower=lower, upper=upper)
        
        return result
    
    @staticmethod
    def standardize(df: pd.DataFrame, cols: List[str], 
                   method: str = 'zscore') -> pd.DataFrame:
        """
        标准化处理
        
        Parameters:
        -----------
        df : pd.DataFrame
            输入数据
        cols : List[str]
            需要标准化的列名
        method : str
            方法，'zscore' 或 'minmax'
            
        Returns:
        --------
        pd.DataFrame : 标准化后的数据
        """
        result = df.copy()
        
        for col in cols:
            if col not in df.columns:
                continue
                
            if method == 'zscore':
                # Z-Score标准化
                mean = result[col].mean()
                std = result[col].std()
                result[col] = (result[col] - mean) / std
            else:
                # Min-Max归一化
                min_val = result[col].min()
                max_val = result[col].max()
                result[col] = (result[col] - min_val) / (max_val - min_val)
        
        return result
    
    @staticmethod
    def neutralize(df: pd.DataFrame, cols: List[str], 
                   by: List[str] = ['industry', 'market_cap']) -> pd.DataFrame:
        """
        因子中性化：对行业、市值等进行中性化处理
        
        Parameters:
        -----------
        df : pd.DataFrame
            输入数据
        cols : List[str]
            需要中性化的列名
        by : List[str]
            中性化维度
            
        Returns:
        --------
        pd.DataFrame : 中性化后的数据
        """
        result = df.copy()
        
        for col in cols:
            if col not in df.columns:
                continue
                
            for group_col in by:
                if group_col not in df.columns:
                    continue
                    
                # 计算行业内均值
                group_mean = result.groupby(group_col)[col].transform('mean')
                # 减去行业均值
                result[f'{col}_neutral'] = result[col] - group_mean
        
        return result


class MomentumSignal:
    """动量信号生成器"""
    
    @staticmethod
    def generate_signals(df: pd.DataFrame, momentum_col: str = 'momentum',
                        threshold: float = 0.0, 
                        top_pct: float = 0.2) -> pd.DataFrame:
        """
        生成动量交易信号
        
        Parameters:
        -----------
        df : pd.DataFrame
            包含动量因子的数据
        momentum_col : str
            动量列名
        threshold : float
            动量阈值，正值above买入
        top_pct : float
            取动量排名前20%
            
        Returns:
        --------
        pd.DataFrame : 包含交易信号
        """
        result = df.copy()
        
        # 动量信号：动量大于阈值
        result['momentum_signal'] = (result[momentum_col] > threshold).astype(int)
        
        # 排名信号：动量排名前20%
        result['momentum_rank'] = result.groupby('date')[momentum_col].rank(pct=True)
        result['top_momentum_signal'] = (result['momentum_rank'] >= (1 - top_pct)).astype(int)
        
        return result
    
    @staticmethod
    def momentum_reversal_signal(df: pd.DataFrame, 
                                  momentum_col: str = 'momentum',
                                  lookback: int = 20) -> pd.DataFrame:
        """
        动量反转信号：检测动量是否即将反转
        
        当动量处于历史高位但开始回落时，可能预示反转
        
        Parameters:
        -----------
        df : pd.DataFrame
            包含动量因子的数据
        momentum_col : str
            动量列名
        lookback : int
            历史回看天数
            
        Returns:
        --------
        pd.DataFrame : 包含反转信号
        """
        result = df.copy()
        
        # 动量变化率
        result['momentum_change'] = result.groupby('code')[momentum_col].diff()
        
        # 动量在历史窗口的位置
        result['momentum_pct_rank'] = result.groupby('code')[momentum_col].transform(
            lambda x: x.rolling(lookback).apply(
                lambda y: pd.Series(y).rank(pct=True).iloc[-1] if len(y) > 0 else np.nan,
                raw=False
            )
        )
        
        # 反转信号：动量高位回落
        result['reversal_signal'] = (
            (result['momentum_pct_rank'] > 0.8) & 
            (result['momentum_change'] < 0)
        ).astype(int)
        
        return result


def demo():
    """演示动量因子计算"""
    # 创建示例数据
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=250, freq='D')
    codes = ['000001', '000002', '000003', '000004', '000005']
    
    data = []
    for code in codes:
        base_price = np.random.uniform(10, 100)
        prices = base_price * np.cumprod(1 + np.random.randn(250) * 0.02)
        for i, date in enumerate(dates):
            data.append({
                'date': date,
                'code': code,
                'close': prices[i],
                'industry': np.random.choice(['银行', '地产', '医药', '科技', '消费']),
                'market_cap': np.random.uniform(10, 1000)
            })
    
    df = pd.DataFrame(data)
    
    # 计算动量因子
    mf = MomentumFactor(df)
    
    # 简单动量
    df_mom = mf.simple_momentum(window=60)
    print("简单动量因子:")
    print(df_mom[['date', 'code', 'close', 'momentum']].head(20))
    
    # 计算所有动量因子
    df_all = mf.compute_all_momentum()
    print("\n所有动量因子:")
    print(df_all.columns.tolist())
    
    # 去极值和标准化
    processor = MomentumFactorProcessor()
    cols = ['momentum_20d', 'momentum_60d', 'momentum_120d']
    df_winsorized = processor.winsorize(df_all, cols, method='mad', limits=3)
    df_standardized = processor.standardize(df_winsorized, cols, method='zscore')
    print("\n标准化后的动量因子:")
    print(df_standardized[cols].describe())
    
    # 生成信号
    signal = MomentumSignal.generate_signals(df_standardized, 'momentum_60d')
    print("\n动量信号:")
    print(signal[signal['date'] == signal['date'].max()][['code', 'momentum_60d', 'momentum_signal', 'top_momentum_signal']])


if __name__ == '__main__':
    demo()