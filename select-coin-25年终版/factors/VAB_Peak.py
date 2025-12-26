# -*- coding: utf-8 -*-
"""
VAB_Peak 因子 (Velocity-Acceleration-Breakout Peak)
===================================================
作者: Gemini (Based on User Idea)
类型: 辅助过滤/逃顶因子

核心逻辑：
寻找行情极度狂热的时刻。
当 价格涨速(Vel)、涨速的变化(Acc)、以及突破前高的幅度(Brk)
三者同时创出 N 周期新高时，标记为 1。

适用场景：
建议在策略配置中 filter_list 使用：('VAB_Peak', 20, 'val:==0')
意为：如果不处于这种极度狂热状态，才允许开仓；或者如果是持仓状态，遇到 1 则平仓。
"""

import pandas as pd
import numpy as np


def signal(candle_df, param, *args):
    """
    VAB_Peak 因子计算函数
    :param candle_df: K线数据
    :param param: int, 滚动窗口周期数 n (如 20)
    :param args: tuple, args[0] 为因子列名
    :return: candle_df
    """
    n = int(param)
    factor_name = args[0]

    # --- 1. 计算速度 (Velocity) ---
    # 使用比率：Current Close / Prev Close
    # 含义：今天的价格是昨天的多少倍
    velocity = candle_df['close'] / candle_df['close'].shift(1)

    # --- 2. 计算加速度 (Acceleration) ---
    # 使用比率的比率：Current Vel / Prev Vel
    # 含义：今天的涨势比昨天猛多少倍
    acceleration = velocity / velocity.shift(1)

    # --- 3. 计算突破强度 (Breakout Strength) ---
    # 获取过去 N 周期内的最高价（不包含当前K线，防止未来函数）
    # shift(1) 确保取的是截至昨天的最高价
    prev_n_high = candle_df['high'].shift(1).rolling(window=n, min_periods=1).max()

    # 计算当前收盘价相对于前高点的突破比率
    breakout_ratio = candle_df['close'] / prev_n_high

    # --- 4. 寻找峰值 (Find Peaks) ---
    # 判断当前值是否为过去 N 周期内的最大值
    is_vel_peak = velocity == velocity.rolling(window=n, min_periods=1).max()
    is_acc_peak = acceleration == acceleration.rolling(window=n, min_periods=1).max()
    is_brk_peak = breakout_ratio == breakout_ratio.rolling(window=n, min_periods=1).max()

    # --- 5. 趋势确认 ---
    # 确保价格确实是上涨的（当前价 > N天前价格）
    is_uptrend = candle_df['close'] > candle_df['close'].shift(n)

    # --- 6. 合成信号 ---
    # 所有条件必须同时满足
    signal_cond = is_vel_peak & is_acc_peak & is_brk_peak & is_uptrend

    # 转换为整型 (1 或 0)
    candle_df[factor_name] = signal_cond.astype(int)

    return candle_df