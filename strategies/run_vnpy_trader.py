"""
启动 vn.py Trader 界面（包含回测模块）
"""
from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy.trader.ui import MainWindow, create_qapp

from vnpy_ctastrategy import CtaStrategyApp
from vnpy_ctabacktester import CtaBacktesterApp
from vnpy_datamanager import DataManagerApp


def main():
    """启动 VeighNa Trader"""
    qapp = create_qapp()

    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)

    # 添加应用模块
    main_engine.add_app(CtaStrategyApp)       # CTA策略模块
    main_engine.add_app(CtaBacktesterApp)     # CTA回测模块
    main_engine.add_app(DataManagerApp)       # 数据管理模块

    main_window = MainWindow(main_engine, event_engine)
    main_window.showMaximized()

    qapp.exec()


if __name__ == "__main__":
    main()
