from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


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

    def round_qty(raw_qty: float) -> float:
        lots = np.floor(np.abs(raw_qty) / qty_step)
        return np.sign(raw_qty) * lots * qty_step

    for i in range(n):
        m = mark[i]
        if not np.isfinite(m):
            equity[i] = cur_equity
            qty[i] = cur_qty
            continue

        # mark-to-market
        cur_equity += (m - last_mark) * cur_qty
        last_mark = m

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
