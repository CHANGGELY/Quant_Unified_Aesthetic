"""
Quant Unified 量化交易系统
signal.py

概率信号 -> 仓位（带迟滞 / hysteresis）
"""

from __future__ import annotations

import numba as nb
import numpy as np


@nb.njit(cache=True)
def positions_from_probs_hysteresis(
    p_up: np.ndarray,
    p_down: np.ndarray,
    p_enter: float = 0.55,
    p_exit: float = 0.55,
    diff_enter: float = 0.0,
    diff_exit: float = 0.0,
    init_pos: int = 0,
) -> np.ndarray:
    """
    将 (p_up, p_down) 转换成 {-1,0,1} 仓位序列，并加入迟滞以降低来回翻仓。

    规则（默认）：
    - 空仓：p_up>=p_enter 且 (p_up-p_down)>=diff_enter -> 做多；
            p_down>=p_enter 且 (p_down-p_up)>=diff_enter -> 做空；
    - 多仓：p_down>=p_exit 且 (p_down-p_up)>=diff_exit -> 反手做空；
    - 空仓：p_up>=p_exit 且 (p_up-p_down)>=diff_exit -> 反手做多；
    - 其他情况保持原仓位。
    """
    n = len(p_up)
    pos = np.empty(n, dtype=np.int8)
    cur = np.int8(init_pos)

    for i in range(n):
        up = p_up[i]
        down = p_down[i]

        if np.isnan(up) or np.isnan(down):
            pos[i] = cur
            continue

        if cur == 0:
            if up >= p_enter and (up - down) >= diff_enter:
                cur = np.int8(1)
            elif down >= p_enter and (down - up) >= diff_enter:
                cur = np.int8(-1)
        elif cur == 1:
            if down >= p_exit and (down - up) >= diff_exit:
                cur = np.int8(-1)
        else:  # cur == -1
            if up >= p_exit and (up - down) >= diff_exit:
                cur = np.int8(1)

        pos[i] = cur

    return pos


def positions_from_probs_hysteresis_py(
    p_up: np.ndarray,
    p_down: np.ndarray,
    p_enter: float = 0.55,
    p_exit: float = 0.55,
    diff_enter: float = 0.0,
    diff_exit: float = 0.0,
    init_pos: int = 0,
) -> np.ndarray:
    """
    Python 版本（便于调试），输出与 numba 版一致。
    """
    p_up = np.asarray(p_up, dtype=float)
    p_down = np.asarray(p_down, dtype=float)
    out = np.empty(len(p_up), dtype=np.int8)
    cur = np.int8(init_pos)

    for i, (up, down) in enumerate(zip(p_up, p_down)):
        if np.isnan(up) or np.isnan(down):
            out[i] = cur
            continue
        if cur == 0:
            if up >= p_enter and (up - down) >= diff_enter:
                cur = np.int8(1)
            elif down >= p_enter and (down - up) >= diff_enter:
                cur = np.int8(-1)
        elif cur == 1:
            if down >= p_exit and (down - up) >= diff_exit:
                cur = np.int8(-1)
        else:
            if up >= p_exit and (up - down) >= diff_exit:
                cur = np.int8(1)
        out[i] = cur

    return out

