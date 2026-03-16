# -*- coding: utf-8 -*-
"""
8号香农策略 - 回测专用配置

使用方法：
    1. 修改下面的参数
    2. 运行 backtest.py 即可

参数说明：
    - vol_short_window: 短期波动率窗口（分钟），越小对波动越敏感
    - vol_long_window: 长期波动率窗口（分钟），作为基准
    - target_ratio: 目标持仓比例，0.5 = 50%持仓50%现金
    - grid_width_base: 基础网格宽度，越大交易越少
"""

from __future__ import annotations

import os
from pathlib import Path

# ==================== 回测参数配置 ====================

# 📊 波动率引擎参数
vol_short_window = 60       # 短期波动率窗口 (分钟) - 推荐 30-240
vol_long_window = 1440      # 长期波动率窗口 (分钟) - 与实盘对齐（24小时）
vol_ewma_alpha = 0.05       # EWMA 平滑系数

# 🎯 核心策略参数
target_ratio = 0.5          # 目标持仓比例 (固定 0.5 = 50% ETH + 50% 现金)
                            # ⚠️ 香农策略核心逻辑：必须保持 50/50 平衡，不可修改

# 与实盘统一的网格宽度参数
vol_k_factor = 1.0          # 波动率K系数 (网格宽度 = EWMA_Vol * K)
                            # 💡 越大 = 网格越宽，交易越少
                            # 推荐: 0.8-1.5

# 物理下限（Hard Constraints）
min_grid_width_bps = 1.0    # 最小网格宽度 (基点, 1bp=0.01%)

# CPRP 挂单结构（与实盘对齐）
grid_layers = 3             # 网格层数（买/卖各 N 层）
force_order_band = 0.1      # 强制双边挂单缓冲带（防止只挂一边导致“断流动性”）
min_qty = 0.007             # 最小下单数量（ETH）

# 订单更新迟滞（Hysteresis：为了避免频繁撤单重挂）
update_threshold_ratio = 0.05  # 网格宽度变化超过 5% 才更新

# 📈 状态切换阈值
regime_spike_threshold = 1.5  # 波动率比率 > 1.5 进入 Spike 模式
regime_crush_threshold = 0.5  # 波动率比率 < 0.5 进入 Crush 模式

# 🎛️ 状态模式下的网格宽度倍数
width_multiplier_spike = 1.5  # Spike 模式：网格放大 1.5x
width_multiplier_crush = 0.8  # Crush 模式：网格收缩 0.8x

# 💰 资金配置
initial_capital = 1000    # 初始资金 (USDC)

# ====== 杠杆（合约保证金口径，非借贷）======
# 口径定义：
#   X = 持仓名义价值（币仓位价值）
#   Y = 空闲 USDT/USDC（available balance）
#   T = 占用保证金（used margin）
#   Z = 逐笔杠杆（交易所设置 leverage）
#   目标：始终维持 X 与 Y 的价值比例为 50/50（即 X == Y）
#
# 在该口径下（忽略资金费/维持保证金差异）：
#   T = X / Z
#   Y = E - T
#   可解得：X_target = E * Z / (Z + 1) ；名义杠杆 W = (X+Y)/E = 2Z/(Z+1) < 2
#
# 参数二选一：
nominal_leverage = None     # 名义杠杆 W（策略层，范围 [1, 2)；例 W=1.90 -> 需要 Z=19）
position_leverage = 2.0     # 逐笔杠杆 Z（交易所 leverage，范围 [1, ...]）
max_position_leverage = 125 # 逐笔杠杆上限（交易所限制；超出会报错）

# 若填写 nominal_leverage，则自动换算出 Z（这里默认 target_ratio 固定 0.5）
if nominal_leverage is not None:
    w = float(nominal_leverage)
    if w < 1.0 or w >= 2.0:
        raise ValueError(f"nominal_leverage 必须在 [1, 2) 内, 当前={w}")
    position_leverage = w / (2.0 - w)

if position_leverage > max_position_leverage:
    raise ValueError(f"position_leverage={position_leverage} 超过 max_position_leverage={max_position_leverage}")

# 兼容旧字段：leverage 作为 position_leverage 的别名
leverage = float(position_leverage)

# 📅 数据范围
data_start_date = "2021-01-01"  # 回测起始日期

# 🔇 调试选项
verbose_regime_switch = False  # 是否打印状态切换日志 (True 会刷屏)

# 📁 数据文件路径 (一般不用改)
def _默认数据文件路径() -> str:
    """
    统一数据入口（避免把路径写死在某台电脑上）。

    优先级：
      1) 环境变量 SHANNON8_DATA_FILE（你想临时切数据文件时用）
      2) common_core.data_center 自动定位（推荐）
      3) 兼容旧路径（仍然能跑，但不建议长期依赖）
    """
    v = os.getenv("SHANNON8_DATA_FILE", "").strip()
    if v:
        return v

    try:
        from common_core.data_center import 生成分钟K线文件名, 获取分钟K线H5文件

        文件名 = 生成分钟K线文件名("ETHUSDT", 开始日期="2019-11-01", 结束日期="2025-06-15", 带table后缀=True)
        return str(获取分钟K线H5文件(文件名))
    except Exception:
        quant_root = Path(__file__).resolve().parents[2]  # Quant_Unified
        return str(
            quant_root.parent
            / "数据"
            / "历史行情中心"
            / "分钟K线"
            / "ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5"
        )


data_file = _默认数据文件路径()


# ==================== 备注 ====================
# 如果你未来真的要做“非 50:50”的研究，建议新建一个策略编号（避免把 8号香农策略 的定义搞乱）。
