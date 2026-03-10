from vnpy_ctastrategy import CtaTemplate
from vnpy.trader.object import BarData


class TestStrategy(CtaTemplate):
    """最简化测试策略 - 只打印日志"""
    author = "TestUser"

    # 无参数
    parameters = []
    variables = ["counter"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.counter = 0

    def on_init(self):
        """策略初始化"""
        self.write_log("✅ 测试策略初始化成功")
        self.load_bar(10)  # 加载10条历史数据
        self.put_event()

    def on_start(self):
        """策略启动"""
        self.write_log("🚀 测试策略已启动")
        self.put_event()

    def on_stop(self):
        """策略停止"""
        self.write_log("🛑 测试策略已停止")
        self.put_event()

    def on_bar(self, bar: BarData):
        """收到K线"""
        self.counter += 1
        self.write_log(f"📊 第{self.counter}根K线: {bar.vt_symbol} 收{bar.close_price:.2f}")
        self.put_event()  # 刷新界面显示counter

    def on_tick(self, tick):
        """收到Tick（可选）"""
        pass
