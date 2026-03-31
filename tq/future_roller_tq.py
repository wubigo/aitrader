import logging
import os

import pandas as pd
from datetime import datetime
import time
import warnings

from tqsdk import TqApi, TqAuth
from utils.backtest_logger import backup_dataframe

warnings.filterwarnings('ignore')


# 从环境变量获取账号密码
token = os.getenv("TQ_ID")
pa = os.getenv("TQ_PASS")


def calc_annualized_basis(fut_price, spot_price, days):
    """计算年化贴水率（保留原逻辑）"""
    if pd.isna(fut_price) or pd.isna(spot_price) or days <= 0:
        return None
    if fut_price is None or spot_price is None:
        return None

    basis_ratio = (spot_price - fut_price) / spot_price
    annualized = basis_ratio * 365 / days * 100
    return round(annualized, 3)


def monitor_ic_basis(interval=1800):  # 默认 30 分钟（1800秒）
    """使用 TqSdk 实时监控 IC 主连年化贴水策略"""
    print("🚀 【TqSdk IC 主连滚贴水策略监控】启动")
    print("合约：KQ.m@CFFEX.IC（中证500指数期货主连）")
    print("现货：SSE.000905（中证500指数）")
    print(f"刷新间隔：{interval // 60} 分钟")
    print("=" * 90)

    # 创建 TqSdk 连接（实盘模式）
    api = TqApi(auth=TqAuth(token, pa))
    symbol = "KQ.m@CFFEX.IC"
    spot_sym = "SSE.000905"

    # 订阅主连期货和现货指数
    fut_quote = api.get_quote(symbol)  # IC 主连
    spot_quote = api.get_quote(spot_sym)  # 中证500指数

    last_print_time = 0

    try:
        while True:
            api.wait_update()

            now = datetime.now()
            if (now.timestamp() - last_print_time) < interval:
                continue  # 控制打印频率

            last_print_time = now.timestamp()

            # ================== 获取实时价格 ==================
            fut_price = fut_quote.last_price
            spot_price = spot_quote.last_price

            # symbol = api.query_cont_quotes(product_id="IC").pop()
            symbol_info = api.query_symbol_info(symbol)
            underlying_symbol = symbol_info.iloc[-1]["underlying_symbol"]
            symbol_info = api.query_symbol_info(underlying_symbol)
            expire_rest_days = symbol_info.iloc[-1]["expire_rest_days"]

            days = expire_rest_days  # TqSdk 自动提供剩余自然日（比手动算更准）

            ann_basis = calc_annualized_basis(fut_price, spot_price, days)

            # ================== 策略信号 ==================
            status = ""
            if ann_basis is not None:
                if ann_basis > 8:
                    status = "🚨 厚贴水 - 建仓信号！"
                elif ann_basis > 6:
                    status = "📊 中等贴水 - 观察"
                elif ann_basis > 3:
                    status = "✅ 轻微贴水"
                else:
                    status = "➡️ 基本平水"

            point = (spot_price - fut_price) if (fut_price and spot_price) else None

            # ================== 打印 & 保存 ==================
            print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] IC 主连滚贴水更新")
            print(f"期货价: {fut_price:.2f} | 现货价: {spot_price:.2f} | 贴水点数: {point:.2f}")
            print(f"剩余天数: {days} 天 | 年化贴水: {ann_basis:.2f}% {status}")
            print(
                f"主力合约: {fut_quote.underlying_symbol if hasattr(fut_quote, 'underlying_symbol') else 'KQ.m@CFFEX.IC'}")
            print("-" * 80)

            # 保存数据（和原来一样）
            df = pd.DataFrame([{
                'code': 'IC主连',
                '期货价': fut_price,
                '现货价': spot_price,
                '贴水点数': point,
                '年化贴水%': ann_basis,
                '剩余天数': days,
                '状态': status,
                'timestamp': now
            }])
            backup_dataframe(df, f"IC主连-年化贴水-{now.strftime('%Y%m%d_%H%M')}.csv")

    except KeyboardInterrupt:
        print("\n\n⛔ 监控已停止")
    except Exception as e:
        print(f"❌ 发生错误: {e}")
    finally:
        api.close()


if __name__ == "__main__":
    print("\n启动 IC 主连滚贴水策略监控 (Ctrl+C 停止)\n")
    monitor_ic_basis(interval=60 * 30)  # 每 30 分钟刷新一次