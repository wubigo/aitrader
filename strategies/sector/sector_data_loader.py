"""
行业数据和主线识别数据加载器
使用 AKShare 获取A股行业分类和资金流向数据
"""
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SectorDataLoader:
    """
    行业数据加载器
    
    功能：
    1. 获取A股行业分类
    2. 获取行业成分股
    3. 计算行业资金流向
    4. 识别强势行业
    """
    
    def __init__(self):
        self.sector_mapping: Dict[str, List[str]] = {}
        self.stock_info: Dict[str, Dict] = {}
    
    def get_industry_classification(self) -> pd.DataFrame:
        """
        获取A股行业分类（申万行业）
        
        :return: DataFrame with columns: [代码, 名称, 行业]
        """
        logger.info("获取A股行业分类...")
        
        try:
            # 获取申万行业分类
            df = ak.stock_sector_spot()
            return df
        except Exception as e:
            logger.error(f"获取行业分类失败: {e}")
            return pd.DataFrame()
    
    def get_sector_stocks(self, sector_name: str) -> List[str]:
        """
        获取某个行业的成分股
        
        :param sector_name: 行业名称
        :return: 股票代码列表
        """
        logger.info(f"获取 {sector_name} 行业成分股...")
        
        try:
            # 使用AKShare获取行业成分股
            df = ak.stock_board_industry_name_ths()
            
            # 查找匹配的行业
            matched = df[df["name"].str.contains(sector_name, na=False)]
            if matched.empty:
                logger.warning(f"未找到行业: {sector_name}")
                return []
            
            # 获取成分股
            industry_code = matched.iloc[0]["code"]
            stocks_df = ak.stock_board_industry_cons_ths(symbol=industry_code)
            
            return stocks_df["代码"].tolist()
        except Exception as e:
            logger.error(f"获取行业成分股失败: {e}")
            return []
    
    def get_sector_fund_flow(self, sector_code: str, period: str = "20") -> pd.DataFrame:
        """
        获取行业资金流向
        
        :param sector_code: 行业代码
        :param period: 统计周期（日）
        :return: 资金流向数据
        """
        logger.info(f"获取 {sector_code} 行业资金流向...")
        
        try:
            # 获取行业资金流向
            df = ak.stock_sector_fund_flow_rank(indicator=sector_code, period=period)
            return df
        except Exception as e:
            logger.error(f"获取资金流向失败: {e}")
            return pd.DataFrame()
    
    def calculate_sector_performance(
        self, 
        sector_stocks: Dict[str, List[str]], 
        start_date: str, 
        end_date: str
    ) -> Dict[str, Dict]:
        """
        计算各行业表现
        
        :param sector_stocks: {行业名: [股票代码列表]}
        :param start_date: 开始日期 "20240101"
        :param end_date: 结束日期 "20241231"
        :return: {行业名: {涨幅, 成交额, 得分}}
        """
        results = {}
        
        for sector_name, stocks in sector_stocks.items():
            logger.info(f"计算 {sector_name} 表现...")
            
            sector_returns = []
            sector_volumes = []
            
            for symbol in stocks[:10]:  # 每行业取前10只
                try:
                    # 获取个股历史数据
                    df = ak.stock_zh_a_hist(
                        symbol=symbol,
                        period="daily",
                        start_date=start_date,
                        end_date=end_date,
                        adjust="qfq"
                    )
                    
                    if len(df) < 2:
                        continue
                    
                    # 计算涨跌幅
                    start_price = df["收盘"].iloc[0]
                    end_price = df["收盘"].iloc[-1]
                    return_pct = (end_price - start_price) / start_price * 100
                    
                    # 计算平均成交额
                    avg_volume = df["成交量"].mean()
                    
                    sector_returns.append(return_pct)
                    sector_volumes.append(avg_volume)
                    
                except Exception as e:
                    logger.debug(f"获取 {symbol} 数据失败: {e}")
                    continue
            
            if sector_returns:
                results[sector_name] = {
                    "avg_return": np.mean(sector_returns),
                    "max_return": max(sector_returns),
                    "avg_volume": np.mean(sector_volumes) if sector_volumes else 0,
                    "stock_count": len(sector_returns),
                }
        
        return results
    
    def identify_leading_sectors(
        self, 
        sector_performance: Dict[str, Dict],
        top_n: int = 5
    ) -> List[Tuple[str, float]]:
        """
        识别强势行业（主线）
        
        评分公式：
        得分 = 平均涨幅×0.5 + 最大涨幅×0.3 + 成交量排名×0.2
        
        :param sector_performance: 行业表现数据
        :param top_n: 返回前N个行业
        :return: [(行业名, 得分), ...]
        """
        scores = []
        
        # 计算排名
        sorted_by_return = sorted(
            sector_performance.items(), 
            key=lambda x: x[1]["avg_return"], 
            reverse=True
        )
        sorted_by_volume = sorted(
            sector_performance.items(), 
            key=lambda x: x[1]["avg_volume"], 
            reverse=True
        )
        
        return_ranks = {name: i for i, (name, _) in enumerate(sorted_by_return)}
        volume_ranks = {name: i for i, (name, _) in enumerate(sorted_by_volume)}
        total_sectors = len(sector_performance)
        
        for sector_name, data in sector_performance.items():
            # 归一化得分（0-100）
            return_score = (1 - return_ranks.get(sector_name, total_sectors) / total_sectors) * 100
            volume_score = (1 - volume_ranks.get(sector_name, total_sectors) / total_sectors) * 100
            
            # 综合得分
            total_score = (
                data["avg_return"] * 0.5 +
                data["max_return"] * 0.3 +
                return_score * 0.2
            )
            
            scores.append((sector_name, total_score, data))
        
        # 排序并返回前N
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_n]
    
    def get_concept_leaders(self, concept_name: str) -> pd.DataFrame:
        """
        获取某个概念板块的龙头股
        
        :param concept_name: 概念名称，如 "人工智能"
        :return: DataFrame with 龙头股信息
        """
        logger.info(f"获取 {concept_name} 概念龙头股...")
        
        try:
            # 获取概念板块成分股
            df = ak.stock_board_concept_cons_em(symbol=concept_name)
            
            # 按成交额排序，取前10作为龙头
            df = df.sort_values("成交额", ascending=False).head(10)
            
            return df
        except Exception as e:
            logger.error(f"获取概念龙头股失败: {e}")
            return pd.DataFrame()


def download_sector_data_example():
    """
    下载行业数据示例
    """
    loader = SectorDataLoader()
    
    # 定义关注的行业
    sectors = {
        "半导体": ["688981", "603501", "002371"],
        "新能源": ["300750", "002594", "601012"],
        "白酒": ["600519", "000858", "000568"],
        "医药": ["600276", "000661", "300760"],
        "银行": ["000001", "600000", "601398"],
        "人工智能": ["000938", "002415", "600570"],
    }
    
    # 计算行业表现
    start_date = "20240101"
    end_date = datetime.now().strftime("%Y%m%d")
    
    performance = loader.calculate_sector_performance(sectors, start_date, end_date)
    
    # 识别主线
    leading_sectors = loader.identify_leading_sectors(performance, top_n=3)
    
    print("\n" + "=" * 50)
    print("当前市场主线：")
    print("=" * 50)
    for i, (name, score, data) in enumerate(leading_sectors, 1):
        print(f"\n第{i}名: {name}")
        print(f"  综合得分: {score:.2f}")
        print(f"  平均涨幅: {data['avg_return']:.2f}%")
        print(f"  最大涨幅: {data['max_return']:.2f}%")
        print(f"  统计股票数: {data['stock_count']}")
    
    return leading_sectors


if __name__ == "__main__":
    # 运行示例
    download_sector_data_example()
