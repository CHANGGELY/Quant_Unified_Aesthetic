"""
这份文件是【3号对冲策略】的实盘配置入口。
作用：
1. 定义一组实盘运行的策略参数（可一次运行多个）
2. 供 real_trading.py 加载
"""

from 策略仓库.三号对冲策略.config import Config

live_strategies = [
    Config(
        symbol='ETHUSDC',
        leverage=3,
        money=600.0,
        capital_ratio=1.0,
        grid_percent=0.0016,
        grid_levels=5,
        initial_long_size=0.005,
        initial_short_size=0.005,
        post_only=True,
        post_only_tick_offset_buy=1,
        post_only_tick_offset_sell=1,
        post_only_reject_retry_limit=2,
        tick_size=0.01,
    ),
]

