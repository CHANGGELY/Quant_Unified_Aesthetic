# -*- coding: utf-8 -*-
import os
import sys

# 自动计算项目根目录 (Quant_Unified)
当前路径 = os.path.dirname(os.path.abspath(__file__))
项目根目录 = os.path.dirname(os.path.dirname(当前路径))
if 项目根目录 not in sys.path:
    sys.path.insert(0, 项目根目录)

class Config:
    """策略配置类"""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

# ==================== 策略核心配置 ====================
strategy_config = Config(
    # 基础信息
    symbol="ETHUSDC",
    leverage=1,                 # 杠杆倍数 (1.0x, 无杠杆)
    maker_fee=0.0,              # Maker 费率 (必须为 0)
    taker_fee=0.0005,           # Taker 费率 (参考值，策略不应做 Taker)

    # 波动率引擎 (Volatility Engine)
    vol_short_window=60,        # 短期波动率窗口 (分钟) - 1小时
    vol_long_window=1440,       # 长期波动率窗口 (分钟) - 24小时
    vol_ewma_alpha=0.05,        # EWMA 平滑系数 (用于计算基准波动率)
    
    # 状态切换阈值 (Regime Switching)
    # Ratio = Vol_short / Vol_long
    regime_spike_threshold=1.5, # Ratio > 1.5 -> Spike Mode
    regime_crush_threshold=0.5, # Ratio < 0.5 -> Crush Mode
    
    # 网格宽度系数 (Grid Width Multipliers)
    # Base_Width = k * EWMA_Vol
    vol_k_factor=1.0,           # 初始 K 值，回测优化项
    width_multiplier_spike=1.5, # Spike 模式下宽度放大倍数
    width_multiplier_crush=0.8, # Crush 模式下宽度收缩倍数
    
    # 物理下限 (Hard Constraints)
    min_grid_width_bps=5.0,     # 最小网格宽度 (基点, 1bp=0.01%) - 5bps = 0.05%
                                # 假设 ETH=2000, 0.05% = 1U，大于 Spread
    
    # CPRP 再平衡参数
    target_ratio=0.5,           # 目标持仓比例 (50% ETH / 50% USDC)
    rebalance_threshold=0.01,   # 触发再平衡的最小偏离度 (1%) - 可选
    
    # 订单更新参数 (Hysteresis)
    update_threshold_ratio=0.2, # 只有当新宽度变化超过 20% 时才撤单重挂
    
    # 资金管理
    total_capital_usdc=1000.0,  # 模拟资金 (回测用)
    max_position_usdc=2000.0,   # 最大持仓价值限制
)

# 实盘资金配置 (覆盖用)
# TOTAL_CAPITAL_CONFIG = "100%" 
