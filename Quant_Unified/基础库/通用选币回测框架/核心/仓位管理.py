"""
Quant Unified 量化交易系统
仓位管理.py

功能：
    提供基于资金占比计算目标持仓的逻辑 (Rebalance Logic)。
    默认实现：总是调仓 (Always Rebalance)。
"""
import numpy as np
import numba as nb
from numba.experimental import jitclass

spec = [
    ('现货每手数量', nb.float64[:]),
    ('合约每手数量', nb.float64[:]),
]

@jitclass(spec)
class 仓位计算:
    def __init__(self, 现货每手数量, 合约每手数量):
        n_syms_spot = len(现货每手数量)
        n_syms_swap = len(合约每手数量)

        self.现货每手数量 = np.zeros(n_syms_spot, dtype=np.float64)
        self.现货每手数量[:] = 现货每手数量

        self.合约每手数量 = np.zeros(n_syms_swap, dtype=np.float64)
        self.合约每手数量[:] = 合约每手数量

    def _计算单边(self, equity, prices, ratios, lot_sizes):
        # 初始化目标持仓手数
        target_lots = np.zeros(len(lot_sizes), dtype=np.int64)

        # 每个币分配的资金(带方向)
        symbol_equity = equity * ratios

        # 分配资金大于 0.01U 则认为是有效持仓
        mask = np.abs(symbol_equity) > 0.01

        # 为有效持仓分配仓位
        target_lots[mask] = (symbol_equity[mask] / prices[mask] / lot_sizes[mask]).astype(np.int64)

        return target_lots

    def 计算目标持仓(self, equity, spot_prices, spot_lots, spot_ratios, swap_prices, swap_lots, swap_ratios):
        """
        计算每个币种的目标手数
        :param equity: 总权益
        :param spot_prices: 现货最新价格
        :param spot_lots: 现货当前持仓手数
        :param spot_ratios: 现货币种的资金比例
        :param swap_prices: 合约最新价格
        :param swap_lots: 合约当前持仓手数
        :param swap_ratios: 合约币种的资金比例
        :return: tuple[现货目标手数, 合约目标手数]
        """
        is_spot_only = False

        # 合约总权重小于极小值，认为是纯现货模式
        if np.sum(np.abs(swap_ratios)) < 1e-6:
            is_spot_only = True
            equity *= 0.99  # 纯现货留 1% 的资金作为缓冲            

        # 现货目标持仓手数
        spot_target_lots = self._计算单边(equity, spot_prices, spot_ratios, self.现货每手数量)

        if is_spot_only:
            swap_target_lots = np.zeros(len(self.合约每手数量), dtype=np.int64)
            return spot_target_lots, swap_target_lots

        # 合约目标持仓手数
        swap_target_lots = self._计算单边(equity, swap_prices, swap_ratios, self.合约每手数量)

        return spot_target_lots, swap_target_lots

# Alias for compatibility if needed
RebAlways = 仓位计算
