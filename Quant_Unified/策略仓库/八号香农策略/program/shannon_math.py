# -*- coding: utf-8 -*-
"""
shannon_math.py - 8号香农策略的“数学内核”（可被回测/实盘共用）

这个文件是干嘛的？
    你要的架构是「同一份策略逻辑，回测/实盘只换执行器」。
    那么最关键的是：指标递推（波动率/状态）和 CPRP 挂单计算，必须只有一套“权威口径”。

    所以这里把两块最核心的数学逻辑抽成一个独立模块：
      1) 波动率状态机（短/长波动率 + EWMA + Regime 切换）
      2) CPRP 多层挂单（维持 X:Y = target_ratio:(1-target_ratio)）

为什么要放在这里？
    - 放在 backtest.py 里：实盘想复用就很别扭，还容易产生“又写一份”的分叉
    - 放在 program/ 里：实盘、回测都能按同一个入口 import

性能说明（用人话）：
    - Numba：把 Python 的循环“即时编译成机器码”的库
      类比：把“手算”变成“按计算器”，结果一样但更快。
    - 这里用“可选 Numba”：有就加速，没有也能跑（只是慢一点）
"""

from __future__ import annotations

import math

import numpy as np

try:
    from numba import njit
except Exception:  # pragma: no cover
    njit = None


def _可选njit(*args, **kwargs):
    """
    一个“小开关”：
    - 如果环境里有 Numba，就用 njit 加速
    - 如果没有，也能跑（返回原函数）
    """

    if njit is None:  # pragma: no cover
        def 装饰器(fn):
            return fn

        return 装饰器
    return njit(*args, **kwargs)


@_可选njit(cache=True)
def _样本标准差(求和: float, 平方和: float, n: int) -> float:
    """样本标准差（ddof=1），用于对齐 pandas Series.std() 的默认口径。"""
    if n <= 1:
        return 0.0
    mean = 求和 / n
    var = (平方和 - 求和 * mean) / (n - 1.0)
    if var < 0.0:
        var = 0.0
    return math.sqrt(var)


@_可选njit(cache=True)
def _目标持仓名义(equity: float, position_leverage_z: float, target_ratio: float) -> float:
    """
    Numba 友好版的「目标持仓名义价值」：
        X_target = E * r / ((1-r) + r/Z)
    """
    r = target_ratio
    z = position_leverage_z
    return equity * r / ((1.0 - r) + r / z)


@_可选njit(cache=True)
def _波动率引擎_更新一次(
    price: float,
    prev_price: float,
    total_returns: int,
    short_buf: np.ndarray,
    long_buf: np.ndarray,
    short_pos: int,
    long_pos: int,
    short_count: int,
    long_count: int,
    short_sum: float,
    short_sumsq: float,
    long_sum: float,
    long_sumsq: float,
    vol_short_window: int,
    vol_long_window: int,
    vol_ewma_alpha: float,
    ewma_vol: float,
    ewma_price: float,
    regime_spike_threshold: float,
    regime_crush_threshold: float,
    regime: int,
):
    """
    用一根收盘价，递推更新波动率引擎状态（与实盘口径保持一致）。

    返回：更新后的所有状态（标量 + 指针），缓冲数组会在原地被修改。
    """
    if price <= 0.0 or prev_price <= 0.0:
        return (
            price,
            total_returns,
            short_pos,
            long_pos,
            short_count,
            long_count,
            short_sum,
            short_sumsq,
            long_sum,
            long_sumsq,
            ewma_vol,
            ewma_price,
            regime,
        )

    r = math.log(price / prev_price)
    prev_price = price
    total_returns += 1

    # long
    if long_count < vol_long_window:
        long_buf[long_pos] = r
        long_sum += r
        long_sumsq += r * r
        long_pos = (long_pos + 1) % vol_long_window
        long_count += 1
    else:
        old = long_buf[long_pos]
        long_buf[long_pos] = r
        long_sum += r - old
        long_sumsq += r * r - old * old
        long_pos = (long_pos + 1) % vol_long_window

    # short
    if short_count < vol_short_window:
        short_buf[short_pos] = r
        short_sum += r
        short_sumsq += r * r
        short_pos = (short_pos + 1) % vol_short_window
        short_count += 1
    else:
        old = short_buf[short_pos]
        short_buf[short_pos] = r
        short_sum += r - old
        short_sumsq += r * r - old * old
        short_pos = (short_pos + 1) % vol_short_window

    # 对齐实盘 VolatilityEngine：returns 不足 short_window 时，直接用“所有 returns 的 std”
    if total_returns < vol_short_window:
        vol_short = _样本标准差(long_sum, long_sumsq, long_count)
        ewma_vol = vol_short
        return (
            prev_price,
            total_returns,
            short_pos,
            long_pos,
            short_count,
            long_count,
            short_sum,
            short_sumsq,
            long_sum,
            long_sumsq,
            ewma_vol,
            ewma_price,
            regime,
        )

    vol_short = _样本标准差(short_sum, short_sumsq, vol_short_window)
    vol_long = _样本标准差(long_sum, long_sumsq, long_count)
    ratio = (vol_short / vol_long) if vol_long > 1e-9 else 1.0

    # EWMA 波动率
    if ewma_vol == 0.0:
        ewma_vol = vol_short
    else:
        ewma_vol = vol_ewma_alpha * vol_short + (1.0 - vol_ewma_alpha) * ewma_vol

    # EWMA 价格（与实盘一致：只有 returns 足够后才更新）
    if ewma_price == 0.0:
        ewma_price = price
    else:
        ewma_price = vol_ewma_alpha * price + (1.0 - vol_ewma_alpha) * ewma_price

    if ratio > regime_spike_threshold:
        regime = 1
    elif ratio < regime_crush_threshold:
        regime = 2
    else:
        regime = 0

    return (
        prev_price,
        total_returns,
        short_pos,
        long_pos,
        short_count,
        long_count,
        short_sum,
        short_sumsq,
        long_sum,
        long_sumsq,
        ewma_vol,
        ewma_price,
        regime,
    )


@_可选njit(cache=True)
def _预计算_波动率状态序列(
    close_arr: np.ndarray,
    交易起始索引: int,
    vol_short_window: int,
    vol_long_window: int,
    vol_ewma_alpha: float,
    regime_spike_threshold: float,
    regime_crush_threshold: float,
):
    """
    用同一套递推公式，把 (ewma_vol, ewma_price, regime) 预跑成数组。

    重要：
        这个函数必须和 “增量口径” 完全一致，否则会变成两套策略。

    口径对齐（非常关键）：
        在执行级回测里，我们是在「上一根 K 线收盘后」更新指标，然后把挂单挂到「下一根 K 线里」去撮合。
        所以对一根 K 线 idx 来说，它开盘时应使用的指标状态，来源于 close[idx-1] 更新后的状态。

        因此这里返回的数组长度为 (n - start)，并且：
            out_i = idx - start
            ewma_vol_in[out_i] / ewma_price_in[out_i] / regime_in[out_i]
            对应的是 “处理完 close[idx-1] 之后” 的状态
    """
    n = len(close_arr)
    start = 交易起始索引
    if start < 2:
        start = 2
    if start >= n:
        return (
            np.zeros(0, dtype=np.float64),
            np.zeros(0, dtype=np.float64),
            np.zeros(0, dtype=np.int8),
        )

    m = n - start
    ewma_vol_in = np.empty(m, dtype=np.float64)
    ewma_price_in = np.empty(m, dtype=np.float64)
    regime_in = np.empty(m, dtype=np.int8)

    short_buf = np.zeros(vol_short_window, dtype=np.float64)
    long_buf = np.zeros(vol_long_window, dtype=np.float64)
    short_pos = 0
    long_pos = 0
    short_count = 0
    long_count = 0
    short_sum = 0.0
    short_sumsq = 0.0
    long_sum = 0.0
    long_sumsq = 0.0

    ewma_vol = 0.0
    ewma_price = 0.0
    regime = 0
    prev_price = close_arr[0]
    total_returns = 0

    # out_i=0 对应 idx=start 的“开盘状态” -> 处理完 close[start-1] 之后
    store_from_i = start - 1
    store_to_i = n - 2  # idx 最大是 n-1，所以 idx-1 最大是 n-2

    for i in range(1, n):
        (
            prev_price,
            total_returns,
            short_pos,
            long_pos,
            short_count,
            long_count,
            short_sum,
            short_sumsq,
            long_sum,
            long_sumsq,
            ewma_vol,
            ewma_price,
            regime,
        ) = _波动率引擎_更新一次(
            close_arr[i],
            prev_price,
            total_returns,
            short_buf,
            long_buf,
            short_pos,
            long_pos,
            short_count,
            long_count,
            short_sum,
            short_sumsq,
            long_sum,
            long_sumsq,
            vol_short_window,
            vol_long_window,
            vol_ewma_alpha,
            ewma_vol,
            ewma_price,
            regime_spike_threshold,
            regime_crush_threshold,
            regime,
        )

        if store_from_i <= i <= store_to_i:
            out_i = i - store_from_i
            ewma_vol_in[out_i] = ewma_vol
            ewma_price_in[out_i] = ewma_price
            regime_in[out_i] = regime

    return ewma_vol_in, ewma_price_in, regime_in


@_可选njit(cache=True)
def _计算_cprp_多层挂单(
    current_price: float,
    position_qty: float,
    total_equity: float,
    base_grid_width: float,
    grid_layers: int,
    min_qty: float,
    force_order_band: float,
    position_leverage_z: float,
    target_ratio: float,
    buy_prices: np.ndarray,
    buy_qtys: np.ndarray,
    sell_prices: np.ndarray,
    sell_qtys: np.ndarray,
):
    """
    计算 CPRP 多层挂单（与 program/cprp.py 的 calculate_rebalance 逻辑保持一致）。

    注意：
        - 这里不返回 Python list（Numba 不擅长），而是把结果写入固定长度数组
        - qty=0 表示该层不挂
    """
    # 当前持仓名义/权益比例（用于“强制双边挂单”的缓冲带）
    if total_equity > 0.0:
        current_notional = abs(position_qty) * current_price
        current_frac = current_notional / total_equity
        target_notional_now = _目标持仓名义(total_equity, position_leverage_z, target_ratio)
        target_frac = target_notional_now / total_equity
    else:
        current_frac = 0.0
        target_frac = 0.0

    band = force_order_band
    lower_frac = target_frac - band
    upper_frac = target_frac + band

    # ====== 买单（向下阶梯）======
    cumulative_buy_qty = 0.0
    for i in range(grid_layers):
        layer = i + 1
        price_bid = current_price * (1.0 - layer * base_grid_width)

        estimated_equity = total_equity - position_qty * (current_price - price_bid)
        if estimated_equity < 0.0:
            estimated_equity = 0.0

        if price_bid > 0.0:
            target_notional = _目标持仓名义(estimated_equity, position_leverage_z, target_ratio)
            target_pos_qty = target_notional / price_bid
        else:
            target_pos_qty = 0.0

        needed_qty = target_pos_qty - position_qty - cumulative_buy_qty

        qty_to_place = 0.0
        if needed_qty > 0.0:
            qty_to_place = needed_qty
            if qty_to_place < min_qty:
                qty_to_place = min_qty
        else:
            if current_frac < upper_frac:
                qty_to_place = min_qty

        buy_prices[i] = price_bid
        buy_qtys[i] = qty_to_place
        if qty_to_place > 0.0:
            cumulative_buy_qty += qty_to_place

    # ====== 卖单（向上阶梯）======
    cumulative_sell_qty = 0.0
    for i in range(grid_layers):
        layer = i + 1
        price_ask = current_price * (1.0 + layer * base_grid_width)

        estimated_equity = total_equity + position_qty * (price_ask - current_price)
        if estimated_equity < 0.0:
            estimated_equity = 0.0

        if price_ask > 0.0:
            target_notional = _目标持仓名义(estimated_equity, position_leverage_z, target_ratio)
            target_pos_qty = target_notional / price_ask
        else:
            target_pos_qty = 0.0

        needed_sell = position_qty - target_pos_qty - cumulative_sell_qty

        qty_to_place = 0.0
        if needed_sell > 0.0:
            qty_to_place = needed_sell
            if qty_to_place < min_qty:
                qty_to_place = min_qty
        else:
            if current_frac > lower_frac:
                qty_to_place = min_qty

        sell_prices[i] = price_ask
        sell_qtys[i] = qty_to_place
        if qty_to_place > 0.0:
            cumulative_sell_qty += qty_to_place
