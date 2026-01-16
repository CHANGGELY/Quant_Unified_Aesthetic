"""
Quant Unified 量化交易系统
[爆仓检查模块]
功能：提供通用的保证金率计算与爆仓检测逻辑，支持单币种和多币种组合模式。
"""
import numpy as np

class LiquidationChecker:
    """
    通用爆仓检查器
    """
    def __init__(self, min_margin_rate=0.005):
        """
        初始化
        :param min_margin_rate: 维持保证金率 (默认 0.5%)
        """
        self.min_margin_rate = min_margin_rate

    def check_margin_rate(self, equity, position_value):
        """
        检查保证金率
        :param equity: 当前账户权益 (USDT)
        :param position_value: 当前持仓名义价值 (USDT, 绝对值之和)
        :return: (is_liquidated, margin_rate)
                 is_liquidated: 是否爆仓 (True/False)
                 margin_rate: 当前保证金率
        """
        if position_value < 1e-8:
            # 无持仓，无限安全
            return False, 999.0
            
        margin_rate = equity / float(position_value)
        
        is_liquidated = margin_rate < self.min_margin_rate
        
        return is_liquidated, margin_rate

    @staticmethod
    def calculate_margin_rate(equity, position_value):
        """
        静态方法：纯计算保证金率
        """
        if position_value < 1e-8:
            return 999.0
        return equity / float(position_value)
