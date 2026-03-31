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


def run_ic_roll_basis_strategy(check_interval=60):  # 检查开仓信号的间隔（秒），建议 60~300 秒
    """IC 主连滚贴水策略 + 交易执行检查 + 动态盈亏"""

    print("🚀 IC 主连滚贴水策略启动（已优化 wait_update）")
    print("条件：年化贴水 > 8%  且  剩余天数 > 7天  且  空仓 → 买入 1 手")
    print("=" * 110)

    api = TqApi(TqKq(), auth=TqAuth(token, pa))

    fut_symbol = "KQ.m@CFFEX.IC"
    spot_sym = "SSE.000905"

    fut_quote = api.get_quote(fut_symbol)
    spot_quote = api.get_quote(spot_sym)
    position = api.get_position(fut_symbol)
    target_pos = TargetPosTask(api, fut_symbol)

    entry_price = None
    has_opened_today = False
    last_check_time = 0

    try:
        while True:
            api.wait_update()  # ← 必须每次都调用，不能轻易 continue

            now = datetime.now()
            current_pos = position.pos_long_today + position.pos_long_his

            # ================== 策略信号检查（降低频率） ==================
            if (now.timestamp() - last_check_time) >= check_interval:
                last_check_time = now.timestamp()

                fut_price = fut_quote.last_price
                spot_price = spot_quote.last_price
                days_left = fut_quote.underlying_quote.expire_rest_days
                underlying = fut_quote.underlying_symbol or fut_symbol
                ann_basis = calc_annualized_basis(fut_price, spot_price, days_left)

                if (ann_basis is not None and
                        ann_basis > 8.0 and
                        days_left > 7 and
                        current_pos == 0 and
                        not has_opened_today):
                    print(f"\n🔥 【开仓信号触发】 {now.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"年化贴水: {ann_basis:.2f}% | 剩余天数: {days_left} 天 | 主力: {underlying}")

                    target_pos.set_target_volume(1)
                    print("✅ 已下达【买入 1 手】指令，等待成交...")

            # ================== 交易执行检查 & 动态盈亏 ==================
            if current_pos > 0:
                if entry_price is None:
                    entry_price = position.open_price_long
                    has_opened_today = True
                    print(f"✅ 【开仓成功】 时间: {now.strftime('%H:%M:%S')} | 开仓价: {entry_price:.2f}")

                # 实时动态盈亏
                float_pnl = position.float_profit
                float_ratio = position.float_profit_ratio * 100
                print(f"📊 【持仓动态盈亏】 开仓价:{entry_price:.2f} | 当前价:{fut_quote.last_price:.2f} | "
                      f"浮动盈亏: {float_pnl:+.2f} 元 | 盈亏率: {float_ratio:+.2f}%", end="\r")

            # ================== 状态打印（每 30 秒） ==================
            if now.second % 30 == 0:
                fut_price = fut_quote.last_price
                spot_price = spot_quote.last_price
                days_left = fut_quote.underlying_quote.expire_rest_days
                ann_basis = calc_annualized_basis(fut_price, spot_price, days_left)
                print(f"\n[{now.strftime('%H:%M:%S')}] 年化贴水:{ann_basis:.2f}% | "
                      f"剩余:{days_left}天 | 持仓:{current_pos}手 | 现货:{spot_price:.2f}")

            # ================== 保存日志（每分钟） ==================
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
        print("\n\n⛔ 策略已停止")
    finally:
        # target_pos.set_target_volume(0)   # 需要平仓时取消注释
        api.close()

if __name__ == "__main__":
    print("启动 IC 主连年化贴水策略（带交易执行检查 & 动态盈亏）...\n")
    run_ic_roll_basis_strategy(check_interval=1800)