"""
主线识别策略数据接口
连接AKShare实时/历史数据，为策略提供行业指标和个股数据
"""
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class MainlineDataFeed:
    """
    主线策略数据供给器
    
    功能：
    1. 获取行业指数数据
    2. 计算行业层面指标（动量、成交量、资金流向）
    3. 获取个股数据
    4. 计算个股层面指标
    """
    
    def __init__(self):
        self.cache: Dict[str, pd.DataFrame] = {}
        self.cache_time: Dict[str, datetime] = {}
        self.cache_duration = timedelta(minutes=5)  # 缓存5分钟
    
    def _get_cache(self, key: str) -> Optional[pd.DataFrame]:
        """获取缓存数据"""
        if key in self.cache:
            if datetime.now() - self.cache_time[key] < self.cache_duration:
                return self.cache[key]
        return None
    
    def _set_cache(self, key: str, data: pd.DataFrame):
        """设置缓存"""
        self.cache[key] = data
        self.cache_time[key] = datetime.now()
    
    # ========== 行业数据接口 ==========
    
    def get_sector_index_data(self, index_code: str, days: int = 60) -> pd.DataFrame:
        """
        获取行业指数历史数据
        
        :param index_code: 指数代码，如 "H30184"（中证半导体）
        :param days: 获取天数
        :return: DataFrame with OHLCV
        """
        cache_key = f"sector_{index_code}_{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached
        
        try:
            # 使用AKShare获取指数数据
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # 调用中证指数数据接口
            df = ak.index_zh_a_hist(
                symbol=index_code,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
            
            if df.empty:
                logger.warning(f"获取指数 {index_code} 数据为空")
                return pd.DataFrame()
            
            # 标准化列名
            df.columns = [c.lower() for c in df.columns]
            
            self._set_cache(cache_key, df)
            return df
            
        except Exception as e:
            logger.error(f"获取行业指数数据失败 {index_code}: {e}")
            return pd.DataFrame()
    
    def calculate_sector_indicators(self, index_code: str) -> Optional[Dict]:
        """
        计算行业层面指标
        
        :param index_code: 行业指数代码
        :return: {
            "momentum_5d": float,
            "momentum_20d": float,
            "volume_ratio": float,
            "fund_flow_pct": float,
            "volatility": float,
        }
        """
        df = self.get_sector_index_data(index_code, days=60)
        if df.empty or len(df) < 20:
            return None
        
        close = df["close"].values
        volume = df["volume"].values
        
        # 动量指标
        momentum_5d = (close[-1] - close[-5]) / close[-5] * 100 if len(close) >= 5 else 0
        momentum_20d = (close[-1] - close[-20]) / close[-20] * 100 if len(close) >= 20 else 0
        
        # 成交量比（近5日 vs 前20日均量）
        recent_vol = np.mean(volume[-5:])
        hist_vol = np.mean(volume[-25:-5]) if len(volume) >= 25 else np.mean(volume[:-5])
        volume_ratio = recent_vol / hist_vol if hist_vol > 0 else 1.0
        
        # 波动率（20日收益率标准差）
        returns = np.diff(close[-21:]) / close[-21:-1] * 100 if len(close) >= 21 else []
        volatility = np.std(returns) if len(returns) > 0 else 0
        
        # 资金流向（简化：涨时放量为正，跌时放量为负）
        fund_flow = 0
        for i in range(-5, 0):
            if i >= -len(close):
                daily_return = (close[i] - close[i-1]) / close[i-1] if i-1 >= -len(close) else 0
                vol_ratio = volume[i] / hist_vol if hist_vol > 0 else 1
                fund_flow += daily_return * (vol_ratio - 1)
        
        return {
            "momentum_5d": momentum_5d,
            "momentum_20d": momentum_20d,
            "volume_ratio": volume_ratio,
            "fund_flow_pct": fund_flow,
            "volatility": volatility,
        }
    
    def get_sector_ranking(self, sectors_config: Dict[str, Dict]) -> List[Tuple[str, float, Dict]]:
        """
        获取行业排名
        
        :param sectors_config: {行业名: {"index_code": "..."}}
        :return: [(行业名, 得分, 指标), ...]
        """
        results = []
        
        for sector_name, config in sectors_config.items():
            index_code = config.get("index_code")
            if not index_code:
                continue
            
            indicators = self.calculate_sector_indicators(index_code)
            if indicators is None:
                continue
            
            # 综合得分
            score = (
                indicators["momentum_20d"] * 0.4 +
                (indicators["volume_ratio"] - 1) * 30 +
                indicators["fund_flow_pct"] * 0.3
            )
            
            results.append((sector_name, score, indicators))
        
        # 排序
        results.sort(key=lambda x: x[1], reverse=True)
        return results
    
    # ========== 个股数据接口 ==========
    
    def get_stock_data(self, symbol: str, days: int = 60) -> pd.DataFrame:
        """
        获取个股历史数据
        
        :param symbol: 股票代码，如 "000001"
        :param days: 获取天数
        :return: DataFrame with OHLCV
        """
        cache_key = f"stock_{symbol}_{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="qfq"
            )
            
            if df.empty:
                return pd.DataFrame()
            
            self._set_cache(cache_key, df)
            return df
            
        except Exception as e:
            logger.error(f"获取股票数据失败 {symbol}: {e}")
            return pd.DataFrame()
    
    def calculate_stock_indicators(self, symbol: str) -> Optional[Dict]:
        """
        计算个股层面指标
        
        :param symbol: 股票代码
        :return: {
            "momentum_5d": float,
            "momentum_20d": float,
            "volume_ratio": float,
            "trend_consistency": float,
            "volatility": float,
            "market_cap": float,
        }
        """
        df = self.get_stock_data(symbol, days=60)
        if df.empty or len(df) < 20:
            return None
        
        close = df["收盘"].values
        volume = df["成交量"].values
        
        # 动量
        momentum_5d = (close[-1] - close[-5]) / close[-5] * 100 if len(close) >= 5 else 0
        momentum_20d = (close[-1] - close[-20]) / close[-20] * 100 if len(close) >= 20 else 0
        
        # 成交量比
        recent_vol = np.mean(volume[-5:])
        hist_vol = np.mean(volume[-25:-5]) if len(volume) >= 25 else np.mean(volume[:-5])
        volume_ratio = recent_vol / hist_vol if hist_vol > 0 else 1.0
        
        # 趋势一致性（近20日上涨天数占比）
        if len(close) >= 21:
            daily_returns = np.diff(close[-21:]) / close[-21:-1]
            up_days = np.sum(daily_returns > 0)
            trend_consistency = up_days / len(daily_returns)
        else:
            trend_consistency = 0.5
        
        # 波动率
        returns = np.diff(close[-21:]) / close[-21:-1] * 100 if len(close) >= 21 else []
        volatility = np.std(returns) if len(returns) > 0 else 0
        
        # 市值（使用最新收盘价 × 总股本，简化处理）
        # 实际应该从基本面数据获取
        market_cap = 100  # 默认值，单位：亿
        
        return {
            "momentum_5d": momentum_5d,
            "momentum_20d": momentum_20d,
            "volume_ratio": volume_ratio,
            "trend_consistency": trend_consistency,
            "volatility": volatility,
            "market_cap": market_cap,
        }
    
    def get_stock_ranking_in_sector(self, stocks: List[str]) -> List[Tuple[str, float, Dict]]:
        """
        获取行业内个股排名
        
        :param stocks: 股票代码列表
        :return: [(股票代码, 得分, 指标), ...]
        """
        results = []
        
        for symbol in stocks:
            indicators = self.calculate_stock_indicators(symbol)
            if indicators is None:
                continue
            
            # 市值因子处理
            cap = indicators["market_cap"]
            if 50 <= cap <= 500:
                market_cap_score = 100
            elif cap < 50:
                market_cap_score = cap / 50 * 100
            else:
                market_cap_score = max(0, 100 - (cap - 500) / 10)
            
            # 综合得分
            score = (
                indicators["momentum_20d"] * 0.4 +
                (indicators["volume_ratio"] - 1) * 25 +
                indicators["trend_consistency"] * 20 +
                market_cap_score * 0.2
            )
            
            results.append((symbol, score, indicators))
        
        # 排序
        results.sort(key=lambda x: x[1], reverse=True)
        return results


# ========== 数据适配器（用于回测）==========

class MainlineDataAdapter:
    """
    将AKShare数据适配为vn.py格式
    用于回测时导入数据
    """
    
    @staticmethod
    def prepare_sector_data_for_backtest(
        data_feed: MainlineDataFeed,
        sectors_config: Dict[str, Dict],
        start_date: str,
        end_date: str,
    ) -> Dict[str, pd.DataFrame]:
        """
        准备回测数据
        
        :return: {symbol: DataFrame}
        """
        all_data = {}
        
        # 获取所有行业指数数据
        for sector_name, config in sectors_config.items():
            index_code = config.get("index_code")
            if index_code:
                df = data_feed.get_sector_index_data(index_code)
                if not df.empty:
                    all_data[index_code] = df
        
        # 获取所有个股数据
        for sector_name, config in sectors_config.items():
            for symbol in config.get("stocks", []):
                df = data_feed.get_stock_data(symbol)
                if not df.empty:
                    all_data[symbol] = df
        
        return all_data


# ========== 使用示例 ==========

def demo_data_feed():
    """数据接口使用示例"""
    feed = MainlineDataFeed()
    
    # 行业配置
    sectors = {
        "半导体": {"index_code": "H30184", "stocks": ["688981", "603501"]},
        "新能源": {"index_code": "399808", "stocks": ["300750", "002594"]},
    }
    
    print("=" * 60)
    print("行业排名")
    print("=" * 60)
    
    sector_ranking = feed.get_sector_ranking(sectors)
    for i, (name, score, indicators) in enumerate(sector_ranking[:3], 1):
        print(f"\n第{i}名: {name} (得分: {score:.2f})")
        print(f"  20日动量: {indicators['momentum_20d']:.2f}%")
        print(f"  成交量比: {indicators['volume_ratio']:.2f}")
        print(f"  资金流向: {indicators['fund_flow_pct']:.2f}%")
    
    print("\n" + "=" * 60)
    print("个股排名示例（半导体行业）")
    print("=" * 60)
    
    stock_ranking = feed.get_stock_ranking_in_sector(sectors["半导体"]["stocks"])
    for i, (symbol, score, indicators) in enumerate(stock_ranking, 1):
        print(f"{i}. {symbol}: {score:.2f}")


if __name__ == "__main__":
    demo_data_feed()
