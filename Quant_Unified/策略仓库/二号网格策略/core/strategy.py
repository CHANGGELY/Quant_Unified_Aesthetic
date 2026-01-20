"""
core/strategy.py - 策略接口（最小抽象）

这个文件是干嘛的？
    这里定义了 Strategy 抽象基类（用人话：只规定“你必须有哪些方法”，不提供具体实现）。
    回测引擎（BacktestEngine）会调用这些方法来驱动策略运行：
    - `on_tick(timestamp, price)`：来了一次价格更新（tick）
    - `on_bar(bar)`：来了一根 K 线（开/高/低/收的一根蜡烛图）

怎么用？
    你一般不需要直接运行本文件。
    当你写一个新策略时，让它继承 `Strategy`，并实现上面两个方法即可。
"""

from abc import ABC, abstractmethod

class Strategy(ABC):
    """
    Abstract base class for trading strategies.
    """
    def __init__(self):
        pass

    @abstractmethod
    def on_tick(self, timestamp, price):
        """
        Called when a new price tick is received.
        """
        pass

    @abstractmethod
    def on_bar(self, bar):
        """
        Called when a new candle/bar is received.
        bar should be a dictionary or object with open, high, low, close, etc.
        """
        pass
