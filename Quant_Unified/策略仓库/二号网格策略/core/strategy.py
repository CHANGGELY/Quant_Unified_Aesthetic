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
