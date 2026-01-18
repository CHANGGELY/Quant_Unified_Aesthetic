# -*- coding: utf-8 -*-
"""
4号做市策略 - 策略接口版回测配置

这个文件是干嘛的？
    给 `backtest_interface.py` 提供一组“回测参数”：
        - 交易对、时间范围、初始资金
        - 做市价差、动态下单量、仓位限制
        - 波动率（ATR）自适应参数

为什么单独拆出来？
    你以后调参，不用进回测主逻辑文件里翻半天。

术语解释：
    - ATR（Average True Range，平均真实波幅）：衡量“最近一段时间波动有多大”的指标。
      你可以把它当作“市场抖动强度计”——抖得越厉害，价差应该开得越大，避免被来回打脸。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class 四号做市回测配置:
    # ====== 数据与时间 ======
    symbol: str = "ETHUSDT"
    start_date: str = "2021-01-01"
    end_date: str = "2025-12-12"

    # ====== 账户 ======
    initial_capital: float = 700.0
    min_margin_rate: float = 0.005  # 维持保证金率（爆仓阈值）

    # ====== 做市核心参数 ======
    leverage: float = 125.0
    bid_spread: float = 0.002
    ask_spread: float = 0.002

    # 动态下单量
    use_dynamic_order_size: bool = True
    min_order_amount: float = 0.009
    max_order_amount: float = 999.0

    # 仓位限制：总持仓名义不超过 equity * leverage * ratio
    max_position_value_ratio: float = 1.0

    # ====== 挂单属性 ======
    post_only: bool = True
    tick_size: float = 0.01
    post_only_tick_offset_buy: int = 1
    post_only_tick_offset_sell: int = 1

    # ====== 波动率自适应（简化版） ======
    enable_volatility_adaptive: bool = True
    atr_period: int = 24 * 60  # 24小时（分钟K）
    high_volatility_threshold: float = 0.30  # 30%
    extreme_volatility_threshold: float = 0.50  # 50%
    max_spread_multiplier: float = 3.0
    spread_adjustment_factor: float = 2.0


backtest_strategies = [
    四号做市回测配置(),
]
