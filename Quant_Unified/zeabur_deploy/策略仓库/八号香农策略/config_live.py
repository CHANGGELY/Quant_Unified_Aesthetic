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

# ==================== 杠杆配置（二选一）====================
# 策略口径（用户定义）：始终维持 X(持仓名义价值) 与 Y(空闲余额) 的价值比例为 50/50（即 X==Y）
# 在该口径下（忽略资金费/维持保证金差异），名义杠杆 W 与逐笔杠杆 Z 的关系为：
#   W = 2Z/(Z+1)  < 2
#   Z = W/(2-W)
NOMINAL_LEVERAGE = None          # 名义杠杆 W（范围 [1, 2)；例 W=1.90 -> 需要 Z=19）
POSITION_LEVERAGE = 2            # 逐笔杠杆 Z（交易所 leverage）
MAX_POSITION_LEVERAGE = 125      # 逐笔杠杆上限（交易所限制）
AUTO_SET_EXCHANGE_SETTINGS = False  # 是否启动时自动设置杠杆/保证金模式（建议测试网先开）

if NOMINAL_LEVERAGE is not None:
    w = float(NOMINAL_LEVERAGE)
    if w < 1.0 or w >= 2.0:
        raise ValueError(f"NOMINAL_LEVERAGE 必须在 [1, 2) 内, 当前={w}")
    POSITION_LEVERAGE = w / (2.0 - w)

if POSITION_LEVERAGE > MAX_POSITION_LEVERAGE:
    raise ValueError(f"POSITION_LEVERAGE={POSITION_LEVERAGE} 超过 MAX_POSITION_LEVERAGE={MAX_POSITION_LEVERAGE}")

# ==================== 策略核心配置 ====================
strategy_config = Config(
    # 基础信息
    symbol="ETHUSDC",
    # 账户净值/保证金计价币 (默认可从 symbol 推断；当账户同时有 USDT/USDC 时建议显式指定)
    equity_asset="USDC",
    # 初始本金 (用于 ROI 统计；单位需与 equity_asset 一致)
    initial_capital=5000.0,
    USE_REAL_TRADING=os.getenv("USE_REAL_TRADING", "").lower() in ("true", "1", "yes"),     # 环境配置: False=测试网 (默认), True=实盘 (Risk!)
    # ====== 杠杆（合约保证金口径，非借贷）======
    nominal_leverage=NOMINAL_LEVERAGE,            # 名义杠杆 W（策略层）
    position_leverage=POSITION_LEVERAGE,          # 逐笔杠杆 Z（交易所 leverage）
    max_position_leverage=MAX_POSITION_LEVERAGE,  # 逐笔杠杆上限
    leverage=POSITION_LEVERAGE,                   # 兼容旧字段：等同 position_leverage
    auto_set_exchange_settings=AUTO_SET_EXCHANGE_SETTINGS,  # 自动设置交易所参数
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
    min_grid_width_bps=1.0,     # 最小网格宽度 (基点, 1bp=0.01%) - 5bps = 0.05%
                                # 假设 ETH=2000, 0.05% = 1U，大于 Spread
    grid_layers=3,              # 网格层数 (多层阶梯挂单) - 建议 3-5 层以捕捉插针
    hedge_mode=False,           # 持仓模式: False=单向持仓, True=双向持仓 (需要账户设置匹配)
    post_only=False,            # 只做Maker模式: False=普通限价单(可能以Taker成交), True=只做Maker(越过盘口会拒单)
    
    # CPRP 再平衡参数
    target_ratio=0.5,           # 目标持仓比例 (50% ETH / 50% USDC)
    rebalance_threshold=0.01,   # 触发再平衡的最小偏离度 (1%) - 可选
    
    # 订单更新参数 (Hysteresis)
    update_threshold_ratio=0.05, # 只有当新宽度变化超过 5% 时才撤单重挂 (之前是20%太迟钝)
    
    # 资金管理
    total_capital_usdc=1000.0,  # 模拟资金 (回测用)
)

# 实盘资金配置 (覆盖用)
# TOTAL_CAPITAL_CONFIG = "100%" 
