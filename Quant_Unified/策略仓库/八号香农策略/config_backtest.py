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

# ==================== 回测参数配置 ====================

# 📊 波动率引擎参数
vol_short_window = 60       # 短期波动率窗口 (分钟) - 推荐 30-240
vol_long_window = 2880      # 长期波动率窗口 (分钟) - 推荐 720-2880
vol_ewma_alpha = 0.05       # EWMA 平滑系数

# 🎯 核心策略参数
target_ratio = 0.5          # 目标持仓比例 (固定 0.5 = 50% ETH + 50% 现金)
                            # ⚠️ 香农策略核心逻辑：必须保持 50/50 平衡，不可修改

# 与实盘统一的网格宽度参数
vol_k_factor = 1.0          # 波动率K系数 (网格宽度 = EWMA_Vol * K)
                            # 💡 越大 = 网格越宽，交易越少
                            # 推荐: 0.8-1.5

# 📈 状态切换阈值
regime_spike_threshold = 1.5  # 波动率比率 > 1.5 进入 Spike 模式
regime_crush_threshold = 0.5  # 波动率比率 < 0.5 进入 Crush 模式

# 🎛️ 状态模式下的网格宽度倍数
width_multiplier_spike = 1.5  # Spike 模式：网格放大 1.5x
width_multiplier_crush = 0.8  # Crush 模式：网格收缩 0.8x

# 💰 资金配置
initial_capital = 1000.0    # 初始资金 (USDC)
leverage = 2.0              # 杠杆倍数 (1.0 = 无杠杆, 2.0 = 2倍杠杆)
                            # 回测使用「借贷杠杆」建模：
                            #   总资产 = initial_capital * leverage
                            #   借款   = initial_capital * (leverage - 1)
                            #   策略在【总资产】上做 50/50 CPRP；权益 = 总资产 - 借款
                            #   （未计入借贷利息/资金费）

# 📅 数据范围
data_start_date = "2021-01-01"  # 回测起始日期

# 🔇 调试选项
verbose_regime_switch = False  # 是否打印状态切换日志 (True 会刷屏)

# 📁 数据文件路径 (一般不用改)
data_file = "/Users/chuan/Desktop/xiangmu/客户端/Quant_Unified/策略仓库/二号网格策略/data_center/ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5"


# ==================== 以下是高级配置，一般不用改 ====================

# 物理下限
min_grid_width_bps = 1   # 最小网格宽度 (基点, 5bps = 0.05%)

# 波动率 K 系数
vol_k_factor = 1.0

# ==================== 参数优化推荐组合 ====================
"""
🏆 低回撤组合 (适合加杠杆):
    target_ratio = 0.2
    grid_width_base = 0.01
    预期: 年化 12.7%, 回撤 -25.7%, 卡玛 0.50
    2x杠杆: 年化 25.4%, 回撤 -51.4%

📊 平衡组合:
    target_ratio = 0.3
    grid_width_base = 0.008
    预期: 年化 17.5%, 回撤 -36.8%

💰 激进组合:
    target_ratio = 0.5
    grid_width_base = 0.004
    预期: 年化 26%, 回撤 -54.7%
"""
