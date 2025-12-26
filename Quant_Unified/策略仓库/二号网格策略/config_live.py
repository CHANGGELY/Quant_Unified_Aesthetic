import os
import sys

# 【自动修复】将项目根目录加入 Python 搜索路径，防止 ModuleNotFoundError
# 获取当前文件的绝对路径，并向上追溯二层目录 (即 Quant_Unified)
# 这样无论你在哪个目录下运行此脚本，它都能找到 策略仓库 包。
当前路径 = os.path.dirname(os.path.abspath(__file__))
项目根目录 = os.path.dirname(os.path.dirname(当前路径))

if 项目根目录 not in sys.path:
    sys.path.insert(0, 项目根目录)

from 策略仓库.二号网格策略.config import Config
from 策略仓库.二号网格策略.quantity_precision import get_quantity_precision

# 本次实盘交易系统配置：
# - 统一 Maker 手续费: 0.0%
# - 统一 Taker 手续费: 0.036%
# - 互怼对冲逻辑：BTC 与 ETH 的参数必须保持【完全一致】以维持平衡
# - 虽然 100U 限制仅针对 BTC，但对冲组合必须同步采用 6 格配置

# 本次实盘总投入资金配置：
# - 字符串百分比，如 "100%" 表示使用账户当前总净值的 100%
# - 纯数字，如 900 表示本次最多投入 900 U，按权重在各策略间分配
TOTAL_CAPITAL_CONFIG = "100%"#使用百分比要加双引号，英文的

# ==================== 实盘挂单同步参数（全局） ====================
# 说明：
# - 这些参数控制 real_trading.py 在“对齐理想网格”时每轮最多撤/补多少单，用于消除网格中间的“空白带”。
# - 数值越大，修复空白带越快，但 API 操作频率越高；建议不超过 orders_per_side。

# 匹配容差：允许订单价格与理想网格价相差多少个 tick
GRID_PRICE_MATCH_TOL_TICKS = 2

# 每次同步每个方向最多补几单（默认建议设为 orders_per_side）
GRID_MAX_PLACES_PER_SIDE_PER_SYNC = 5

# 每次同步每个方向最多撤几单（用于“撤远端单为近端缺口让位”）
GRID_MAX_CANCELS_PER_SIDE_PER_SYNC = 5

# 实盘策略列表
# 每一个 Config 对象代表一个独立的实盘机器人
live_strategies = [
    # 策略 1: SOL 做多网格 (停用)
    Config(
        # ==================== 基础交易参数 ====================
        symbol="SOLUSDC",           # 交易对名称，必须大写，例如 "SOLUSDC", "ETHUSDC"
        direction_mode="long",      # 交易方向模式: "long" (做多网格), "short" (做空网格), "neutral" (中性网格)
        leverage=3,                 # 合约杠杆倍数 (建议新手从 1-3 倍开始)
        candle_period="1m",         # [预留参数] K线周期，目前实盘逻辑主要依赖实时成交驱动，此参数暂时不影响核心逻辑
        money=0,                    # (占位符) 脚本运行后会根据你账户的 607U 真实余额自动计算并覆盖此值
        capital_weight=0.5,
        capital_ratio=1.0,          # 资金利用率 (0.0 - 1.0)，默认 1.0 表示使用全部 money 对应的资金跑网格
        max_position_ratio=1.0,     # 持仓上限系数: 以 (money*leverage*capital_ratio) 为基准，0 表示不限制
        max_position_value=0.0,     # 绝对持仓上限(USDC): 0 表示不限制
        orders_per_side=3,          # [同步] 为了对冲平衡，两边都统一为同时挂 3 单
                                    # 因为 4x 杠杆下，挂 5 买 5 卖总额约 1700U，超过了 300U*4=1200U 的限额。
        qty_precision=get_quantity_precision("SOLUSDC"),

        # ==================== 网格区间参数 ====================
        # 网格价格区间设置 (min_price 和 max_price 必须设置)
        min_price=0,               # 设为0，以激活下面的 price_range 2% 区间计算
        max_price=0,               # 设为0，以激活下面的 price_range 2% 区间计算
        
        # 价格区间动态计算
        price_range=0.01 ,              # 0.01 表示上下波动 1%，总区间 2%
                                        # 因为每格利润预期是 0.2%，所以 2% 区间分 [ 10格 ] 太散了
                                        # 建议调减 num_steps (如下)

        num_steps=10,               # [核心调整] 格子数从 10 减到 6。
                                   # 这样每笔下单金额会从 ~90U 涨到 ~170U，稳定超过 PAPI 的 100U 限制。
        interval_mode="geometric_sequence", # 网格间隔模式: 
                                            # "geometric_sequence" (等比网格，每格涨跌幅百分比相同，适合大区间震荡)
                                            # "arithmetic_sequence" (等差网格，每格价格差固定，适合小区间震荡)

        # ==================== 高级功能参数 ====================
        enable_compound=True,       # 是否开启复利模式: 
                                    # True: 每次开仓数量 = (当前总权益 / 网格数)，随盈利增加自动加仓
                                    # False: 每次开仓数量 = (初始本金 / 网格数)，固定开仓量

        post_only=False,
        post_only_tick_offset_buy=1,
        post_only_tick_offset_sell=1,
        post_only_reject_retry_limit=2,
        tick_size=0.01,

        # ==================== 督导员对冲参数 ====================
        hedge_diff_threshold=0.2,   # 当两边价值差超过 20% 时触发补仓
        target_hedge_ratio=0.4,     # 补仓目标对冲比例 (40%)

        # ==================== 网格平移与边界控制 ====================
        # 1. 自动平移开关 (防止价格跑出区间)
        enable_upward_shift=True,   # 是否开启向上平移: 当价格突破最高价时，整体网格区间自动向上移动
        enable_downward_shift=True, # 是否开启向下平移: 当价格跌破最低价时，整体网格区间自动向下移动

        # 2. 平移停止边界 (限制平移的范围，防止无限追高或抄底)
        # 只有在开启了对应的平移开关时，这些参数才有效
        stop_up_price=None,         # [上移停止价格]: 当价格上涨超过此价格后，网格不再向上平移
                                    # 例如设置 200，当 SOL 涨到 200 以上时，即使 enable_upward_shift=True，网格也固定在 200，不再跟随上涨
                                    # (None 表示不设置上限，无限上移)

        stop_down_price=None,       # [下移停止价格]: 当价格下跌低于此价格后，网格不再向下平移
                                    # 例如设置 100，当 SOL 跌破 100 时，网格不再向下平移
                                    # (None 表示不设置下限，无限下移)
        enabled=True,             # 【开关】是否启用
    ),

    # 策略 2: ETH 做空网格 (启用)
    Config(
        # ==================== 基础交易参数 ====================
        symbol="ETHUSDC",           # 交易对名称，必须大写，例如 "SOLUSDC", "ETHUSDC"
        direction_mode="short",      # 交易方向模式: "long" (做多网格), "short" (做空网格), "neutral" (中性网格)
        leverage=3,                 # 合约杠杆倍数 (建议新手从 1-3 倍开始)
        candle_period="1m",         # [预留参数] K线周期，目前实盘逻辑主要依赖实时成交驱动，此参数暂时不影响核心逻辑
        money=0,                    # (占位符) 同上，会自动读取账户真实余额
        capital_weight=0.5,
        capital_ratio=1.0,          # 资金利用率 (0.0 - 1.0)，默认 1.0 表示使用全部 money 对应的资金跑网格
        max_position_ratio=1.0,     # 持仓上限系数: 以 (money*leverage*capital_ratio) 为基准，0 表示不限制
        max_position_value=0.0,     # 绝对持仓上限(USDC): 0 表示不限制
        orders_per_side=3,          # [同步] 为了对冲平衡，两边都统一为同时挂 3 单
        qty_precision=get_quantity_precision("ETHUSDC"),

        # ==================== 网格区间参数 ====================
        # 网格价格区间设置 (min_price 和 max_price 必须设置)
        min_price=0,           # 设为0
        max_price=0,           # 设为0
        
        # 价格区间动态计算
        price_range=0.01,              # 0 表示使用固定的 min/max_price。若设置非 0 (如 0.2)，则会根据当前价格动态计算 min/max，覆盖上面的设置。

        num_steps=10,               # [同步] 为了对冲平衡，跟随 BTC 设为 6 格 (解决 100U 限制)
        interval_mode="geometric_sequence", # 网格间隔模式: 
                                            # "geometric_sequence" (等比网格，每格涨跌幅百分比相同，适合大区间震荡)
                                            # "arithmetic_sequence" (等差网格，每格价格差固定，适合小区间震荡)

        # ==================== 高级功能参数 ====================
        enable_compound=True,       # 是否开启复利模式: 
                                    # True: 每次开仓数量 = (当前总权益 / 网格数)，随盈利增加自动加仓
                                    # False: 每次开仓数量 = (初始本金 / 网格数)，固定开仓量

        post_only=False,
        post_only_tick_offset_buy=1,
        post_only_tick_offset_sell=1,
        post_only_reject_retry_limit=2,
        tick_size=0.01,

        # ==================== 督导员对冲参数 ====================
        hedge_diff_threshold=0.2,   # 当两边价值差超过 20% 时触发补仓
        target_hedge_ratio=0.4,     # 补仓目标对冲比例 (40%)

        # ==================== 网格平移与边界控制 ====================
        # 1. 自动平移开关 (防止价格跑出区间)
        enable_upward_shift=True,   # 是否开启向上平移: 当价格突破最高价时，整体网格区间自动向上移动
        enable_downward_shift=True, # 是否开启向下平移: 当价格跌破最低价时，整体网格区间自动向下移动

        # 2. 平移停止边界 (限制平移的范围，防止无限追高或抄底)
        # 只有在开启了对应的平移开关时，这些参数才有效
        stop_up_price=None,         # [上移停止价格]: 当价格上涨超过此价格后，网格不再向上平移
                                    # 例如设置 200，当 SOL 涨到 200 以上时，即使 enable_upward_shift=True，网格也固定在 200，不再跟随上涨
                                    # (None 表示不设置上限，无限上移)

        stop_down_price=None,       # [下移停止价格]: 当价格下跌低于此价格后，网格不再向下平移
                                    # 例如设置 100，当 SOL 跌破 100 时，网格不再向下平移
                                    # (None 表示不设置下限，无限下移)
        enabled=True,              # 【开关】是否启用
    ),
]
# ==================== 自动化策略筛选逻辑 ====================
# [核心修复] 只运行标记为 enabled=True 的策略。
# 当只有一个策略被启用时，该策略将自动占用 TOTAL_CAPITAL_CONFIG 设定的 100% 资金权重。
live_strategies = [s for s in live_strategies if getattr(s, 'enabled', True)]
