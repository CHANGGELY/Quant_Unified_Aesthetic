from __future__ import annotations

"""
step4_simulate.py - 单标的回测撮合（始终持仓模式）

这个文件是干嘛的？
    它把“策略给出的仓位方向（做多/做空/空仓）”变成一条真实的资金曲线。

你可以把它理解成“交易所的简化模拟器”：
    - 每一根 bar（这里通常是 1 秒）都会用 mark 价结算浮动盈亏
    - 当方向改变时，会在 bid/ask 上成交（包含点差成本）
    - 会扣除手续费与滑点
    - 最重要：会做爆仓检查（保证金率低于阈值就归零）

术语解释：
    - mark 价：用于结算浮盈浮亏的“标记价格”（交易所通常用它来算你的盈亏）
    - bid/ask：买一/卖一价格（买入要付 ask，卖出拿 bid，中间差就是点差成本）
    - 保证金率：你账户的“安全垫厚度”，越低越危险；低于维持保证金率就会爆仓
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from 基础库.common_core.risk_ctrl.liquidation import LiquidationChecker


@dataclass(frozen=True)
class SimResult:
    equity: pd.Series
    position: pd.Series
    qty: pd.Series
    turnover: pd.Series
    cost: pd.Series


def simulate_always_in(
    df_1s: pd.DataFrame,
    position: np.ndarray,
    *,
    fee_rate: float,
    slippage_rate: float,
    qty_step: float,
    leverage: float | np.ndarray,
    initial_capital: float,
    min_order_notional: float = 0.0,
    min_margin_rate: float = 0.005,
    mark_col: str = "wmp",
    bid_col: str = "bid1_p",
    ask_col: str = "ask1_p",
) -> SimResult:
    """
    单标的、始终持仓模式：
    - mark 价格用于持仓收益结算（默认 WMP）
    - 成交按 bid/ask 执行，自动包含点差成本
    - 手续费 + 滑点按单边成交额计：turnover * (fee_rate + slippage_rate)
    """
    if len(df_1s) != len(position):
        raise ValueError("df_1s and position length mismatch")
    if qty_step <= 0:
        raise ValueError("qty_step must be > 0")

    n = len(df_1s)
    if isinstance(leverage, (int, float, np.floating)):
        leverage_arr = np.full(n, float(leverage), dtype=float)
    else:
        leverage_arr = np.asarray(leverage, dtype=float)
        if leverage_arr.shape != (n,):
            raise ValueError("leverage must be a scalar or a 1d array with length == len(df_1s)")
    if np.any(~np.isfinite(leverage_arr)) or np.any(leverage_arr < 0):
        raise ValueError("leverage values must be finite and >= 0")

    mark = df_1s[mark_col].to_numpy(dtype=float)
    bid = df_1s[bid_col].to_numpy(dtype=float)
    ask = df_1s[ask_col].to_numpy(dtype=float)
    pos = position.astype(np.int8, copy=False)

    equity = np.empty(n, dtype=float)
    qty = np.empty(n, dtype=float)
    turnover = np.zeros(n, dtype=float)
    cost = np.zeros(n, dtype=float)

    cur_equity = float(initial_capital)
    cur_qty = 0.0
    last_mark = mark[0]
    已爆仓 = False
    风控 = LiquidationChecker(min_margin_rate=float(min_margin_rate))

    def round_qty(raw_qty: float) -> float:
        lots = np.floor(np.abs(raw_qty) / qty_step)
        return np.sign(raw_qty) * lots * qty_step

    for i in range(n):
        if 已爆仓:
            equity[i] = 0.0
            qty[i] = 0.0
            continue

        m = mark[i]
        if not np.isfinite(m):
            equity[i] = cur_equity
            qty[i] = cur_qty
            continue

        # mark-to-market
        cur_equity += (m - last_mark) * cur_qty
        last_mark = m

        # ====== 爆仓检查（回测最重要的事：先活下来）======
        pos_val = abs(cur_qty) * m
        is_liq, _ = 风控.check_margin_rate(cur_equity, pos_val)
        if is_liq:
            已爆仓 = True
            cur_equity = 0.0
            cur_qty = 0.0
            equity[i] = 0.0
            qty[i] = 0.0
            continue

        desired = int(pos[i])
        desired_sign = 0 if desired == 0 else (1 if desired > 0 else -1)
        cur_sign = 0 if cur_qty == 0 else (1 if cur_qty > 0 else -1)

        if desired_sign != cur_sign:
            if desired_sign == 0:
                target_qty = 0.0
            else:
                lev = float(leverage_arr[i])
                target_notional = cur_equity * lev
                raw_qty = desired_sign * (target_notional / m)
                target_qty = round_qty(raw_qty)
                if abs(target_qty) * m < min_order_notional:
                    target_qty = 0.0

            delta_qty = target_qty - cur_qty
            if delta_qty != 0.0:
                exec_p = ask[i] if delta_qty > 0 else bid[i]
                if np.isfinite(exec_p) and exec_p > 0:
                    t = abs(delta_qty) * exec_p
                    # 点差/执行价偏离 mark 的瞬时影响
                    exec_impact = abs(delta_qty) * abs(exec_p - m)
                    # 手续费 + 滑点
                    tc = t * (fee_rate + slippage_rate)
                    cur_equity -= (exec_impact + tc)
                    turnover[i] = t
                    cost[i] = exec_impact + tc
                    cur_qty = target_qty

        # 调仓后再做一次爆仓检查（比如：刚加杠杆后保证金率变低）
        pos_val = abs(cur_qty) * m
        is_liq, _ = 风控.check_margin_rate(cur_equity, pos_val)
        if is_liq:
            已爆仓 = True
            cur_equity = 0.0
            cur_qty = 0.0
            equity[i] = 0.0
            qty[i] = 0.0
            continue

        equity[i] = cur_equity
        qty[i] = cur_qty

    idx = df_1s.index
    return SimResult(
        equity=pd.Series(equity, index=idx, name="equity"),
        position=pd.Series(pos, index=idx, name="position"),
        qty=pd.Series(qty, index=idx, name="qty"),
        turnover=pd.Series(turnover, index=idx, name="turnover"),
        cost=pd.Series(cost, index=idx, name="cost"),
    )
