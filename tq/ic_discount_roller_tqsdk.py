import os
import pandas as pd
from datetime import datetime
import time
import warnings

from tqsdk import TqApi, TqAuth, TargetPosTask, TqKq
from utils.backtest_logger import backup_dataframe

warnings.filterwarnings('ignore')

# 从环境变量获取账号密码
token = os.getenv("TQ_ID")
pa = os.getenv("TQ_PASS")


def calc_annualized_basis(fut_price, spot_price, days):
    """计算年化贴水率"""
    if pd.isna(fut_price) or pd.isna(spot_price) or days <= 0:
        return None
    if fut_price is None or spot_price is None:
        return None

    basis_ratio = (spot_price - fut_price) / spot_price
    annualized = basis_ratio * 365 / days * 100
    return round(annualized, 3)


def run_ic_roll_basis_strategy(interval=1800):  # 每半个小时检查一次开仓信号
    """IC 主连滚贴水策略 + 交易执行检查 + 动态盈亏实时显示"""

    print("🚀 IC 主连滚贴水策略（带交易执行检查 & 动态盈亏）启动")
    print("交易条件：年化贴水 > 8%  且  剩余天数 > 7天  且  空仓 → 买入 1 手")
    print("=" * 110)

    api = TqApi(TqKq(), auth=TqAuth(token, pa))

    fut_symbol = "KQ.m@CFFEX.IC"  # IC 主连
    spot_sym = "SSE.000905"

    fut_quote = api.get_quote(fut_symbol)
    spot_quote = api.get_quote(spot_sym)
    position = api.get_position(fut_symbol)  # 持仓对象
    target_pos = TargetPosTask(api, fut_symbol)  # 仓位管理器

    entry_price = None  # 记录开仓成交价
    has_opened_today = False

    try:
        while True:
            api.wait_update()

            now = datetime.now()

            # ================== 实时数据 ==================
            fut_price = fut_quote.last_price
            spot_price = spot_quote.last_price
            days_left = fut_quote.underlying_quote.expire_rest_days
            underlying = fut_quote.underlying_symbol or fut_symbol

            ann_basis = calc_annualized_basis(fut_price, spot_price, days_left)

            # 当前实际持仓
            current_pos = position.pos_long_today + position.pos_long_his

            # ================== 策略开仓判断 ==================
            if (ann_basis is not None and
                    ann_basis > 8.0 and
                    days_left > 7 and
                    current_pos == 0 and
                    not has_opened_today):
                print(f"\n🔥 【开仓信号触发】 {now.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"年化贴水: {ann_basis:.2f}% | 剩余天数: {days_left} 天 | 主力合约: {underlying}")

                target_pos.set_target_volume(1)  # 下单买入1手
                print("✅ 已下达【买入 1 手】指令，等待成交...")

            # ================== 交易执行结果检查 ==================
            if current_pos > 0 and entry_price is None:
                # 首次检测到持仓 → 记录开仓价
                entry_price = position.open_price_long
                has_opened_today = True
                print(f"✅ 【开仓成功】 成交时间: {now.strftime('%H:%M:%S')} | 开仓价: {entry_price:.2f} 元")

            # ================== 动态盈亏实时显示 ==================
            if current_pos > 0:
                float_pnl = position.float_profit  # 浮动盈亏（元）
                float_pnl_ratio = position.float_profit_ratio * 100  # 浮动盈亏率（%）

                print(f"📊 【持仓动态盈亏】 开仓价: {entry_price:.2f} | 当前价: {fut_price:.2f} | "
                      f"浮动盈亏: {float_pnl:+.2f} 元 | 盈亏率: {float_pnl_ratio:+.2f}%")

            # ================== 状态打印（每30秒） ==================
            if now.second % 30 == 0:
                status_str = "【信号触发】" if (
                            ann_basis and ann_basis > 8 and days_left > 7 and current_pos == 0) else ""
                print(f"[{now.strftime('%H:%M:%S')}] 年化贴水:{ann_basis:.2f}% | "
                      f"剩余:{days_left}天 | 持仓:{current_pos}手 | 现货:{spot_price:.2f} {status_str}")

            # ================== 保存日志 ==================
            if now.minute % 1 == 0 and now.second < 10:
                df = pd.DataFrame([{
                    'timestamp': now,
                    '期货价': fut_price,
                    '现货价': spot_price,
                    '年化贴水%': ann_basis,
                    '剩余天数': days_left,
                    '当前持仓': current_pos,
                    '开仓价': entry_price,
                    '浮动盈亏': position.float_profit if current_pos > 0 else None,
                    '浮动盈亏率%': position.float_profit_ratio * 100 if current_pos > 0 else None,
                    '主力合约': underlying,
                    '信号': '买入1手' if (ann_basis and ann_basis > 8 and days_left > 7 and current_pos == 0) else ''
                }])
                backup_dataframe(df, f"IC滚贴水策略日志-{now.strftime('%Y%m%d')}.csv")

    except KeyboardInterrupt:
        print("\n\n⛔ 策略已手动停止")
    except Exception as e:
        print(f"❌ 发生错误: {e}")
    finally:
        # 退出时可选自动平仓（根据风控需求决定是否打开）
        # target_pos.set_target_volume(0)
        api.close()


if __name__ == "__main__":
    print("启动 IC 主连年化贴水策略（带交易执行检查 & 动态盈亏）...\n")
    run_ic_roll_basis_strategy(interval=1800)