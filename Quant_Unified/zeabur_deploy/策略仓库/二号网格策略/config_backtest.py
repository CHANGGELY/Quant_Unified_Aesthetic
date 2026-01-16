"""
2 号网格策略 - 回测专用配置
在这里修改参数，仅影响 backtest.py 回测脚本。
支持配置多个策略组合进行批量回测（例如同时回测 ETH 做多和做空）。
"""
from datetime import datetime

from 策略仓库.二号网格策略.config import Config

run_id = datetime.now().strftime('%Y%m%d-%H%M%S-%f')

# 回测策略列表
# 每一个 Config 对象代表一个独立的回测任务
backtest_strategies = [
    # 策略 1: BTC 做多网格
    Config(
        # ==================== 基础交易参数 ====================
        symbol="BTCUSDC",           # 交易对
        direction_mode="long",      # 做多
        leverage=3,                 # 杠杆
        money=438.5,                 # 初始本金
        capital_ratio=1.0,          # 资金利用率
        orders_per_side=4,          # 每个价格方向上同时挂出的网格订单数量
        
        # ==================== 回测时间设置 ====================
        candle_period="1m",         # K线周期: "1m", "5m", "15m", "1h", "4h", "1d"
                                    # 周期越短，回测精度越高，但速度越慢。建议默认 "1m" 以获得最接近真实的网格触碰模拟。
        start_time="2025-1-01 00:00:00",
        end_time="2025-12-14 00:00:00",
        num_hours=0,                # 0 表示使用 start/end time
        
        # ==================== 网格参数 ====================
        min_price=3806.55,
        max_price=3883.45,
        num_steps=22,#网格数
        price_range=0.01,              # 0 表示使用固定的 min/max_price。若设置非 0 (如 0.2)，则会根据当前价格动态计算 min/max，覆盖上面的设置。
        # 计算公式 :
        #   上限 (max_price) = 当前价格 × (1 + price_range)
        #   下限 (min_price) = 当前价格 × (1 - price_range)
        # 数值含义：
        #   如果您设置为 0.2，意思是上下 20%。
        #   如果您想要上下 2%，应该设置为 0.02。
        interval_mode="geometric_sequence",#GS 是等比的意思
        enable_compound=True,#复利开关
        post_only=True,                 # [Maker 模式] 开启后仅挂单 (Maker)，赚取手续费 rebate，如果会立刻成交(Taker)则取消
        post_only_tick_offset_buy=1,    # [Maker 买入微调] 挂买单时价格自动向下微调几个 Tick，确保不吃单
        post_only_tick_offset_sell=1,   # [Maker 卖出微调] 挂卖单时价格自动向上微调几个 Tick，确保不吃单
        post_only_reject_retry_limit=2, # [重试限制] 如果 Maker 订单被交易所拒绝，尝试调整价格重试的次数
        tick_size=0.01,                 # [最小跳动单位] 交易对的价格最小变动精度 (如 ETHUSDT 通常为 0.01)
        
        # ==================== 高级开关 ====================
        enable_upward_shift=True,       # [自动上移] 价格涨破网格上限时，是否自动整体上移网格 (类似无限网格)
        enable_downward_shift=True,     # [自动下移] 价格跌破网格下限时，是否自动整体下移网格 (保持持仓在网格区间内)
        stop_up_price=None,             # [向上止损] 价格涨到此值时停止策略 (None 代表不设限)
        stop_down_price=None,            # [向下止损] 价格跌到此值时停止策略 (None 代表不设限)
        run_id=run_id,

        # ==================== 对冲与自动建仓 ====================
        auto_build_position=True,       # 是否自动构建底仓
        min_hedge_ratio=0.1,            # 最小对冲比例 (0.1 = 10%)
        target_hedge_ratio=0.4          # 目标对冲比例 (0.4 = 40%)
    ),
    
    # 策略 2: ETH 做空网格 (双向持仓对冲测试)
    Config(
        # ==================== 基础交易参数 ====================
        symbol="ETHUSDC",           # 交易对
        direction_mode="short",     # 做空
        leverage=3,                 # 杠杆
        money=438.5,                 # 初始本金
        capital_ratio=1.0,          # 资金利用率
        orders_per_side=4,          # 每个方向 (买/卖) 同时挂出的网格订单数量
        
        # ==================== 回测时间设置 ====================
        candle_period="1m",
        start_time="2025-1-01 00:00:00",
        end_time="2025-12-14 00:00:00",
        num_hours=0,                # 保持时间一致以便对比
        
        # ==================== 网格参数 ====================
        min_price=3806.55,
        max_price=3883.45,
        num_steps=22,
        price_range=0.01,
        interval_mode="geometric_sequence",
        enable_compound=True,
        post_only=True,                 # [Maker 模式] 开启后仅挂单 (Maker)，赚取手续费 rebate，如果会立刻成交(Taker)则取消
        post_only_tick_offset_buy=1,    # [Maker 买入微调] 挂买单时价格自动向下微调几个 Tick，确保不吃单
        post_only_tick_offset_sell=1,   # [Maker 卖出微调] 挂卖单时价格自动向上微调几个 Tick，确保不吃单
        post_only_reject_retry_limit=2, # [重试限制] 如果 Maker 订单被交易所拒绝，尝试调整价格重试的次数
        tick_size=0.01,                 # [最小跳动单位] 交易对的价格最小变动精度 (如 ETHUSDT 通常为 0.01)
        
        # ==================== 高级开关 ====================
        enable_upward_shift=True,       # [自动上移] 价格涨破网格上限时，是否自动整体上移网格 (类似无限网格)
        enable_downward_shift=True,     # [自动下移] 价格跌破网格下限时，是否自动整体下移网格 (保持持仓在网格区间内)
        stop_up_price=None,             # [向上止损] 价格涨到此值时停止策略 (None 代表不设限)
        stop_down_price=None,            # [向下止损] 价格跌到此值时停止策略 (None 代表不设限)
        run_id=run_id,

        # ==================== 对冲与自动建仓 ====================
        auto_build_position=True,       # 是否自动构建底仓
        min_hedge_ratio=0.1,            # 最小对冲比例
        target_hedge_ratio=0.4          # 目标对冲比例
    )
]
