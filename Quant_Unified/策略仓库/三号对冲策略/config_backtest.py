"""
这份文件是【3号对冲策略】的回测配置入口。
作用：
1. 定义一组回测策略参数（可一次回测多个）
2. 仅影响三号策略的 backtest.py，不影响其他策略
"""

from 策略仓库.三号对冲策略.config import Config

backtest_strategies = [
    Config(
        symbol='ETHUSDC',
        leverage=3,
        money=636.6 / 2,  # 资金一半用于多、另一半用于空的初始规模估算
        capital_ratio=1.0,
        grid_percent=0.0016,
        grid_levels=5,
        initial_long_size=0.005,
        initial_short_size=0.005,
        max_individual_position_size=0.05,
        post_only=True,
        post_only_tick_offset_buy=1,
        post_only_tick_offset_sell=1,
        post_only_reject_retry_limit=2,
        tick_size=0.01,

        candle_period='1m',
        start_time='2025-07-01 00:00:00',
        end_time='2025-10-09 00:00:00',
        num_hours=0,
    ),
]
