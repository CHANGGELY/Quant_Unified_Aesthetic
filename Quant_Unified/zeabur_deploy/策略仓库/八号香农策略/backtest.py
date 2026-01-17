# -*- coding: utf-8 -*-
"""
8号香农策略 - 执行级回测（贴近实盘“挂单被撞上才成交”）

这个文件是干嘛的？
    你现在的实盘策略是“被动挂单吃波动”（Maker：先挂单，等价格走到那儿才成交），因为你 Maker 手续费为 0。
    所以回测如果还用“每分钟收盘瞬移调仓到 50:50”，就会严重失真（那等价于你能无限快成交，通常还得吃滑点）。

本回测的核心改动：
    1) 下单：复用实盘 CPRP 思想（维持 X:Y = 50:50），每分钟生成多层限价挂单（买/卖各多层）
    2) 撮合：用 1 分钟 K 线的 open/high/low/close 来模拟“价格在这一分钟里怎么走”
       - 阳线（close >= open）：开 → 低 → 高 → 收
       - 阴线（close <  open）：开 → 高 → 低 → 收
       这是在只有 OHLC 的前提下，一个非常常用、且顺序明确的近似方案
    3) 波动率引擎：用“增量更新”的方式（每根 K 线收盘更新一次），并用 Numba 加速循环

运行方法：
    cd /Users/chuan/Desktop/xiangmu/客户端/Quant_Unified
    python3 -X utf8 策略仓库/八号香农策略/backtest.py --no-chart
"""

from __future__ import annotations

import os
import sys
import math
import logging
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from numba import njit
except Exception:  # pragma: no cover
    njit = None


def _可选njit(*args, **kwargs):
    """
    一个“小开关”：
    - 如果环境里有 numba，就用 njit 把循环编译成机器码（速度接近 C）
    - 如果没有 numba，也能跑，只是会慢很多
    """

    if njit is None:  # pragma: no cover
        def 装饰器(fn):
            return fn
        return 装饰器
    return njit(*args, **kwargs)


# ====== 自动计算项目根目录 ======
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ====== 导入统一模块 ======
from 策略仓库.八号香农策略.config_live import Config
from 策略仓库.八号香农策略 import config_backtest as cfg  # 回测配置
from 策略仓库.八号香农策略.program.leverage_model import resolve_leverage_spec

# 导入统一回测指标和进度条
from 基础库.common_core.backtest.metrics import 回测指标计算器
from 基础库.common_core.backtest.进度条 import 分块进度条
from 基础库.common_core.backtest.可视化 import 回测可视化

# ====== 日志配置 ======
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("Backtest")


# ====================================================================
# 数据加载
# ====================================================================

def 加载数据(文件路径: str) -> tuple[pd.DataFrame, int]:
    """
    读取真实历史 K 线数据（HDF5），并返回“交易起始索引”。

    重要：
    - 严禁模拟数据（Mock Data）
    - 为了让波动率引擎更像实盘：会在 start_date 之前额外保留一段“预热数据”
    """
    if not 文件路径 or not os.path.exists(文件路径):
        raise FileNotFoundError(f"❌ 数据文件不存在: {文件路径}")

    logger.info(f"📂 正在加载数据文件: {文件路径}")

    import h5py
    import hdf5plugin  # 自动注册 BLOSC 等压缩插件

    with h5py.File(文件路径, 'r') as f:
        if 'klines' in f and 'table' in f['klines']:
            table = f['klines']['table']
            data = table[:]

            df = pd.DataFrame({
                'open': data['open'],
                'high': data['high'],
                'low': data['low'],
                'close': data['close'],
                'volume': data['volume'],
                'candle_begin_time': pd.to_datetime(data['candle_begin_time_GMT8'], unit='ns'),
            })
        else:
            raise ValueError("❌ H5 文件格式不正确：找不到 /klines/table")

    df = df.sort_values('candle_begin_time').reset_index(drop=True)

    开始日期 = pd.Timestamp(getattr(cfg, "data_start_date", "2021-01-01"))

    # 预热：至少给波动率引擎留出 long_window 的历史
    vol_short = int(getattr(cfg, "vol_short_window", 60))
    vol_long = int(getattr(cfg, "vol_long_window", 1440))
    预热分钟数 = max(vol_short, vol_long) + 10
    预热开始日期 = 开始日期 - pd.Timedelta(minutes=int(预热分钟数))

    df = df[df['candle_begin_time'] >= 预热开始日期].copy()
    df = df.reset_index(drop=True)

    时间序列 = df['candle_begin_time'].to_numpy()
    交易起始索引 = int(np.searchsorted(时间序列, np.datetime64(开始日期)))

    if len(df) < 10:
        raise ValueError("❌ 数据量太少，无法回测（请检查 data_file / data_start_date）")
    if not (0 <= 交易起始索引 < len(df)):
        raise ValueError("❌ start_date 超出数据范围（请检查 data_start_date）")

    logger.info(
        f"✅ 数据加载成功: {len(df):,} 条 | "
        f"预热开始: {df['candle_begin_time'].iloc[0]} | "
        f"交易开始: {df['candle_begin_time'].iloc[交易起始索引]} | "
        f"结束: {df['candle_begin_time'].iloc[-1]}"
    )
    return df, 交易起始索引


# ====================================================================
# Numba 加速：波动率 + CPRP 挂单 + K线内撮合
# ====================================================================

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
    与 program/leverage_model.py 的 target_position_notional 同口径（但这里写成 numba 友好版本）。
    """
    r = target_ratio
    z = position_leverage_z
    return equity * r / ((1.0 - r) + r / z)


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
    - 这里不返回 Python list（numba 不擅长），而是把结果写入固定长度数组
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


@_可选njit(cache=True)
def _执行级回测_核心循环(
    open_arr: np.ndarray,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    close_arr: np.ndarray,
    交易起始索引: int,
    初始资金: float,
    target_ratio: float,
    vol_short_window: int,
    vol_long_window: int,
    vol_ewma_alpha: float,
    regime_spike_threshold: float,
    regime_crush_threshold: float,
    vol_k_factor: float,
    width_multiplier_spike: float,
    width_multiplier_crush: float,
    min_grid_width_bps: float,
    grid_layers: int,
    min_qty: float,
    force_order_band: float,
    position_leverage_z: float,
    update_threshold_ratio: float,
):
    """
    执行级回测主循环（在 numba 下会非常快）。

    返回：
    - 权益曲线（从交易开始索引开始的每分钟收盘权益）
    - 网格宽度曲线
    - 市场状态曲线：0=NORMAL, 1=SPIKE, 2=CRUSH
    - 成交次数
    """
    n = len(close_arr)
    start = 交易起始索引
    if start < 2:
        start = 2
    if start >= n:
        return np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.int8), 0

    m = n - start
    权益曲线 = np.empty(m, dtype=np.float64)
    宽度曲线 = np.empty(m, dtype=np.float64)
    状态曲线 = np.empty(m, dtype=np.int8)

    # ====== 波动率引擎（增量版本）======
    # 维护两个窗口的 log return：short 与 long
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

    vol_short = 0.0
    vol_long = 0.0
    ratio = 1.0
    ewma_vol = 0.0
    ewma_price = 0.0
    regime = 0  # 0 NORMAL, 1 SPIKE, 2 CRUSH

    prev_price = close_arr[0]
    total_returns = 0

    # ====== 预热：把 start 之前的收盘价都喂给波动率引擎 ======
    for i in range(1, start):
        price = close_arr[i]
        if price <= 0.0 or prev_price <= 0.0:
            prev_price = price
            continue

        r = math.log(price / prev_price)
        prev_price = price
        total_returns += 1

        # 更新 long 窗口
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

        # 更新 short 窗口
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
            vol_long = vol_short
            ratio = 1.0
            ewma_vol = vol_short
            continue

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

    # ====== 账户初始化（保证金口径）======
    last_close = close_arr[start - 1]
    wallet_balance = 初始资金
    position_qty = 0.0
    entry_price = 0.0

    # 初始建仓：直接把“组合状态”放在目标点（更像策略稳定运行时的状态）
    if last_close > 0.0:
        x0 = _目标持仓名义(wallet_balance, position_leverage_z, target_ratio)
        position_qty = x0 / last_close
        entry_price = last_close if position_qty > 0.0 else 0.0

    # ====== 挂单状态（理想挂单 vs 活跃挂单）======
    # 理想挂单：每分钟都重新计算（用于判断要不要撤单重挂）
    ideal_buy_prices = np.zeros(grid_layers, dtype=np.float64)
    ideal_buy_qtys = np.zeros(grid_layers, dtype=np.float64)
    ideal_sell_prices = np.zeros(grid_layers, dtype=np.float64)
    ideal_sell_qtys = np.zeros(grid_layers, dtype=np.float64)

    # 活跃挂单：只有触发更新时才会被替换；否则会跨分钟继续挂着等待成交
    buy_prices = np.zeros(grid_layers, dtype=np.float64)
    buy_qtys = np.zeros(grid_layers, dtype=np.float64)
    buy_active = np.zeros(grid_layers, dtype=np.uint8)  # 1=还在挂，0=未挂/已成交
    sell_prices = np.zeros(grid_layers, dtype=np.float64)
    sell_qtys = np.zeros(grid_layers, dtype=np.float64)
    sell_active = np.zeros(grid_layers, dtype=np.uint8)

    last_grid_width = 0.0
    last_regime = 0
    上一根有成交 = True  # 第一次一定要挂单
    成交次数 = 0

    min_width = min_grid_width_bps / 10000.0

    # ====== 交易循环：从 start 开始，每根 K 线模拟“挂单→被撞→成交”======
    for idx in range(start, n):
        # 1) 基于上一根 close 的状态，计算 width/regime
        base_width = ewma_vol * vol_k_factor
        multiplier = 1.0
        if regime == 1:
            multiplier = width_multiplier_spike
        elif regime == 2:
            multiplier = width_multiplier_crush
        width = base_width * multiplier
        if width < min_width:
            width = min_width

        # 2) 中心价：0.5*last + 0.5*ewma
        if ewma_price > 0.0:
            center_price = 0.5 * last_close + 0.5 * ewma_price
        else:
            center_price = last_close

        # 3) 当前权益（用 last_close 计价）
        if position_qty != 0.0:
            equity_mark = wallet_balance + position_qty * (last_close - entry_price)
        else:
            equity_mark = wallet_balance

        # 简化爆仓：权益 <= 0 视为爆仓（未计维持保证金/资金费）
        if equity_mark <= 0.0:
            # 剩余曲线置 0
            for j in range(idx - start, m):
                权益曲线[j] = 0.0
                宽度曲线[j] = width
                状态曲线[j] = regime
            return 权益曲线, 宽度曲线, 状态曲线, 成交次数

        # 4) 计算理想挂单（每分钟都会算，但不一定更新“活跃挂单”）
        _计算_cprp_多层挂单(
            center_price,
            position_qty,
            equity_mark,
            width,
            grid_layers,
            min_qty,
            force_order_band,
            position_leverage_z,
            target_ratio,
            ideal_buy_prices,
            ideal_buy_qtys,
            ideal_sell_prices,
            ideal_sell_qtys,
        )

        # 5) 是否需要更新挂单（撤旧挂新）
        should_update = False

        # 5.0 首次启动/缺单：必须挂单
        has_any_active = False
        for i in range(grid_layers):
            if buy_active[i] == 1 or sell_active[i] == 1:
                has_any_active = True
                break
        if not has_any_active:
            should_update = True

        # 5.1 有成交：下一分钟必须补单（对齐实盘的“仓位变化触发更新”）
        if 上一根有成交:
            should_update = True

        # 5.2 宽度变化过大：撤单重挂
        if not should_update and last_grid_width > 0.0:
            diff_ratio = abs(width - last_grid_width) / last_grid_width
            if diff_ratio > update_threshold_ratio:
                should_update = True
        if not should_update and last_grid_width <= 0.0:
            should_update = True

        # 5.3 SPIKE（暴涨暴跌）风控：更积极更新
        if not should_update and regime == 1 and last_regime != 1:
            should_update = True

        # 5.4 如果活跃挂单里有“空洞”，而理想挂单希望挂：也更新
        if not should_update:
            for i in range(grid_layers):
                if buy_active[i] == 0 and ideal_buy_qtys[i] > 0.0:
                    should_update = True
                    break
                if sell_active[i] == 0 and ideal_sell_qtys[i] > 0.0:
                    should_update = True
                    break

        if should_update:
            for i in range(grid_layers):
                buy_prices[i] = ideal_buy_prices[i]
                buy_qtys[i] = ideal_buy_qtys[i]
                buy_active[i] = 1 if buy_qtys[i] > 0.0 else 0

                sell_prices[i] = ideal_sell_prices[i]
                sell_qtys[i] = ideal_sell_qtys[i]
                sell_active[i] = 1 if sell_qtys[i] > 0.0 else 0

            last_grid_width = width
            last_regime = regime

        # 6) 本根 K 线内撮合成交
        o = open_arr[idx]
        h = high_arr[idx]
        l = low_arr[idx]
        c = close_arr[idx]

        # 按你定义的“OHLC 内部路径”
        if c >= o:
            p0, p1, p2, p3 = o, l, h, c
        else:
            p0, p1, p2, p3 = o, h, l, c

        本根有成交 = False

        # 6.1 开盘价可能直接“跨过”挂单价：用最保守的方式撮合（按挂单价成交）
        # 买单：open <= buy_price 视为立刻成交
        for i in range(grid_layers):
            if buy_active[i] == 1 and buy_qtys[i] > 0.0:
                if p0 <= buy_prices[i]:
                    fill_price = buy_prices[i]
                    fill_qty = buy_qtys[i]
                    new_qty = position_qty + fill_qty
                    if new_qty > 0.0:
                        if position_qty > 0.0:
                            entry_price = (position_qty * entry_price + fill_qty * fill_price) / new_qty
                        else:
                            entry_price = fill_price
                    position_qty = new_qty
                    buy_active[i] = 0
                    成交次数 += 1
                    本根有成交 = True
        # 卖单：open >= sell_price 视为立刻成交（不允许做空：卖出量最多到持仓）
        for i in range(grid_layers):
            if sell_active[i] == 1 and sell_qtys[i] > 0.0 and position_qty > 0.0:
                if p0 >= sell_prices[i]:
                    fill_price = sell_prices[i]
                    fill_qty = sell_qtys[i]
                    if fill_qty > position_qty:
                        fill_qty = position_qty
                    if fill_qty > 0.0:
                        wallet_balance += fill_qty * (fill_price - entry_price)
                        position_qty -= fill_qty
                        if position_qty <= 1e-12:
                            position_qty = 0.0
                            entry_price = 0.0
                        sell_active[i] = 0
                        成交次数 += 1
                        本根有成交 = True

        # 6.2 逐段撮合：下跌段撮合买单，上涨段撮合卖单
        for seg in range(3):
            if seg == 0:
                start_p, end_p = p0, p1
            elif seg == 1:
                start_p, end_p = p1, p2
            else:
                start_p, end_p = p2, p3

            if end_p < start_p:
                # 下跌段：触发买单（从高到低依次触发）
                hi = start_p
                lo = end_p
                for i in range(grid_layers):
                    if buy_active[i] == 1 and buy_qtys[i] > 0.0:
                        px = buy_prices[i]
                        if lo <= px <= hi:
                            fill_price = px
                            fill_qty = buy_qtys[i]
                            new_qty = position_qty + fill_qty
                            if new_qty > 0.0:
                                if position_qty > 0.0:
                                    entry_price = (position_qty * entry_price + fill_qty * fill_price) / new_qty
                                else:
                                    entry_price = fill_price
                            position_qty = new_qty
                            buy_active[i] = 0
                            成交次数 += 1
                            本根有成交 = True

            elif end_p > start_p:
                # 上涨段：触发卖单（从低到高依次触发）
                lo = start_p
                hi = end_p
                if position_qty > 0.0:
                    for i in range(grid_layers):
                        if sell_active[i] == 1 and sell_qtys[i] > 0.0:
                            px = sell_prices[i]
                            if lo <= px <= hi:
                                fill_price = px
                                fill_qty = sell_qtys[i]
                                if fill_qty > position_qty:
                                    fill_qty = position_qty
                                if fill_qty > 0.0:
                                    wallet_balance += fill_qty * (fill_price - entry_price)
                                    position_qty -= fill_qty
                                    if position_qty <= 1e-12:
                                        position_qty = 0.0
                                        entry_price = 0.0
                                    sell_active[i] = 0
                                    成交次数 += 1
                                    本根有成交 = True

        # 7) 记录本根收盘权益（用于绩效曲线）
        if position_qty != 0.0:
            equity_close = wallet_balance + position_qty * (c - entry_price)
        else:
            equity_close = wallet_balance

        out_i = idx - start
        权益曲线[out_i] = equity_close
        宽度曲线[out_i] = width
        状态曲线[out_i] = regime

        上一根有成交 = 本根有成交
        last_close = c

        # 8) 用本根收盘价更新波动率引擎（供下一根使用）
        if c > 0.0 and prev_price > 0.0:
            r = math.log(c / prev_price)
            prev_price = c
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

            if total_returns < vol_short_window:
                vol_short = _样本标准差(long_sum, long_sumsq, long_count)
                vol_long = vol_short
                ratio = 1.0
                ewma_vol = vol_short
            else:
                vol_short = _样本标准差(short_sum, short_sumsq, vol_short_window)
                vol_long = _样本标准差(long_sum, long_sumsq, long_count)
                ratio = (vol_short / vol_long) if vol_long > 1e-9 else 1.0

                if ewma_vol == 0.0:
                    ewma_vol = vol_short
                else:
                    ewma_vol = vol_ewma_alpha * vol_short + (1.0 - vol_ewma_alpha) * ewma_vol

                if ewma_price == 0.0:
                    ewma_price = c
                else:
                    ewma_price = vol_ewma_alpha * c + (1.0 - vol_ewma_alpha) * ewma_price

                if ratio > regime_spike_threshold:
                    regime = 1
                elif ratio < regime_crush_threshold:
                    regime = 2
                else:
                    regime = 0

    return 权益曲线, 宽度曲线, 状态曲线, 成交次数


# ====================================================================
# 主流程
# ====================================================================

def 运行回测(*, 显示图表: bool = True, 限制条数: int | None = None):
    """主回测函数（执行级撮合）。"""
    print()
    print("🚀" * 20)
    print("    8号香农策略 - 执行级回测 (挂单撮合)")
    print("🚀" * 20)
    print()

    进度 = 分块进度条(总步骤=5, 描述="回测进度")

    try:
        # ====== 1. 配置 ======
        配置 = Config(
            vol_short_window=int(getattr(cfg, "vol_short_window", 60)),
            vol_long_window=int(getattr(cfg, "vol_long_window", 1440)),
            target_ratio=float(getattr(cfg, "target_ratio", 0.5)),
            regime_spike_threshold=float(getattr(cfg, "regime_spike_threshold", 1.5)),
            regime_crush_threshold=float(getattr(cfg, "regime_crush_threshold", 0.5)),
            verbose_regime_switch=bool(getattr(cfg, "verbose_regime_switch", False)),
            vol_ewma_alpha=float(getattr(cfg, "vol_ewma_alpha", 0.05)),
            vol_k_factor=float(getattr(cfg, "vol_k_factor", 1.0)),
            width_multiplier_spike=float(getattr(cfg, "width_multiplier_spike", 1.5)),
            width_multiplier_crush=float(getattr(cfg, "width_multiplier_crush", 0.8)),
            min_grid_width_bps=float(getattr(cfg, "min_grid_width_bps", 1.0)),
            grid_layers=int(getattr(cfg, "grid_layers", 3)),
            force_order_band=float(getattr(cfg, "force_order_band", 0.1)),
            update_threshold_ratio=float(getattr(cfg, "update_threshold_ratio", 0.05)),
            initial_capital=float(getattr(cfg, "initial_capital", 1000.0)),
        )
        进度.完成步骤("加载配置")

        # ====== 2. 加载数据 ======
        数据文件 = getattr(cfg, "data_file", None)
        df, 交易起始索引 = 加载数据(数据文件)
        if 限制条数 is not None and int(限制条数) > 0:
            df = df.iloc[: int(限制条数)].copy()
            df = df.reset_index(drop=True)
            交易起始索引 = min(交易起始索引, len(df) - 1)

        # 保护：波动率计算至少要有 2 根 K 线才能形成 1 个收益率
        交易起始索引 = int(max(2, int(交易起始索引)))
        if len(df) - 交易起始索引 < 10:
            raise ValueError("❌ 交易起始点之后的数据太少，无法回测（请检查 start_date / limit）")

        开 = np.ascontiguousarray(df['open'].to_numpy(dtype=np.float64))
        高 = np.ascontiguousarray(df['high'].to_numpy(dtype=np.float64))
        低 = np.ascontiguousarray(df['low'].to_numpy(dtype=np.float64))
        收 = np.ascontiguousarray(df['close'].to_numpy(dtype=np.float64))
        时间 = df['candle_begin_time'].to_numpy()
        进度.完成步骤("加载数据")

        # ====== 3. 执行级回测（Numba 加速） ======
        logger.info(f"⚡ 开始执行级回测 | 数据量: {len(df):,} 条 | 交易起点index={交易起始索引}")

        杠杆信息 = resolve_leverage_spec(
            cfg,
            target_ratio=float(getattr(cfg, "target_ratio", 0.5)),
            max_position_leverage=getattr(cfg, "max_position_leverage", None),
        )

        权益曲线, 宽度曲线, 状态曲线, 成交次数 = _执行级回测_核心循环(
            开, 高, 低, 收,
            int(交易起始索引),
            float(配置.initial_capital),
            float(配置.target_ratio),
            int(配置.vol_short_window),
            int(配置.vol_long_window),
            float(配置.vol_ewma_alpha),
            float(配置.regime_spike_threshold),
            float(配置.regime_crush_threshold),
            float(配置.vol_k_factor),
            float(配置.width_multiplier_spike),
            float(配置.width_multiplier_crush),
            float(配置.min_grid_width_bps),
            int(配置.grid_layers),
            float(getattr(cfg, "min_qty", 0.007)),  # 与实盘 CPRP 一致的最小下单量
            float(配置.force_order_band),
            float(杠杆信息.position_leverage),
            float(配置.update_threshold_ratio),
        )
        进度.完成步骤("执行回测")

        # 对齐曲线对应的时间/价格（从交易开始索引开始的“每分钟收盘”）
        时间_交易段 = 时间[int(交易起始索引):]
        价格_交易段 = 收[int(交易起始索引):]

        # ====== 4. 计算并输出指标 ======
        计算器 = 回测指标计算器(
            权益曲线=权益曲线,
            初始资金=float(配置.initial_capital),
            时间戳=时间_交易段,
            周期每年数量=525600,  # 分钟级
        )
        计算器.打印报告(策略名称="8号香农策略 (CPRP) - 执行级回测")
        进度.完成步骤("生成报告")

        print(f"🔄 总成交次数: {成交次数}")

        # 状态分布统计
        状态名称 = {0: 'NORMAL', 1: 'SPIKE', 2: 'CRUSH'}
        print("\n📊 市场状态分布:")
        for 状态码 in [0, 1, 2]:
            数量 = int(np.sum(状态曲线 == 状态码))
            占比 = 数量 / len(状态曲线) * 100 if len(状态曲线) else 0
            print(f"   {状态名称[状态码]}: {数量:,} ({占比:.1f}%)")

        # ====== 5. 可视化 ======
        回测配置参数 = {
            "data_file": getattr(cfg, "data_file", None),
            "data_start_date": getattr(cfg, "data_start_date", None),
            "data_points_total": int(len(df)),
            "data_points_traded": int(len(权益曲线)),
            "initial_capital": float(配置.initial_capital),
            "target_ratio": float(配置.target_ratio),
            "vol_short_window": int(配置.vol_short_window),
            "vol_long_window": int(配置.vol_long_window),
            "vol_ewma_alpha": float(配置.vol_ewma_alpha),
            "vol_k_factor": float(配置.vol_k_factor),
            "min_grid_width_bps": float(配置.min_grid_width_bps),
            "regime_spike_threshold": float(配置.regime_spike_threshold),
            "regime_crush_threshold": float(配置.regime_crush_threshold),
            "width_multiplier_spike": float(配置.width_multiplier_spike),
            "width_multiplier_crush": float(配置.width_multiplier_crush),
            "grid_layers": int(配置.grid_layers),
            "force_order_band": float(配置.force_order_band),
            "update_threshold_ratio": float(配置.update_threshold_ratio),
            "position_leverage(Z)_resolved": float(杠杆信息.position_leverage),
            "nominal_leverage(W)_resolved": float(杠杆信息.nominal_leverage),
            "execution_model": "OHLC路径撮合: 阳=O-L-H-C, 阴=O-H-L-C",
        }

        可视化器 = 回测可视化(
            权益曲线=权益曲线,
            时间序列=时间_交易段,
            初始资金=float(配置.initial_capital),
            价格序列=价格_交易段,
            显示图表=显示图表,
            保存路径=PROJECT_ROOT / "策略仓库/八号香农策略",
            报告参数=回测配置参数,
        )
        可视化器.生成报告(策略名称="8号香农策略 (CPRP) - 执行级回测")
        进度.完成步骤("生成图表")

        进度.结束()

    except Exception as e:
        进度.结束()
        logger.error(f"❌ 回测失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="8号香农策略回测（执行级挂单撮合）")
    parser.add_argument("--no-chart", action="store_true", help="不自动打开浏览器（仍会保存 HTML）")
    parser.add_argument("--limit", type=int, default=None, help="只取前 N 条数据做快速自检（正式回测不要用）")
    args = parser.parse_args()

    运行回测(显示图表=not args.no_chart, 限制条数=args.limit)
