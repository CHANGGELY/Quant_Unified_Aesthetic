from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import numba as nb

# 将 Quant_Unified 和关键目录加入搜索路径（与其他策略保持一致）
QUANT_ROOT = Path(__file__).resolve().parents[2]
if str(QUANT_ROOT) not in sys.path:
    sys.path.append(str(QUANT_ROOT))

for folder in ["基础库", "服务", "策略仓库", "应用"]:
    p = QUANT_ROOT / folder
    if p.exists() and str(p) not in sys.path:
        sys.path.append(str(p))

from 策略仓库.六号MACD策略.config_backtest import MacdStrategy6Config  # noqa: E402


def _parse_grid(spec: str) -> list[int]:
    """
    支持两种写法：
    - 逗号列表: "6,8,10"
    - 区间步长: "6:20:2" => [6,8,10,12,14,16,18,20]
    """
    s = spec.strip()
    if "," in s:
        out = [int(x.strip()) for x in s.split(",") if x.strip()]
        if not out:
            raise ValueError(f"empty grid: {spec!r}")
        return out
    if ":" in s:
        parts = [p.strip() for p in s.split(":")]
        if len(parts) != 3:
            raise ValueError(f"bad range grid: {spec!r}")
        start, end, step = (int(parts[0]), int(parts[1]), int(parts[2]))
        if step == 0:
            raise ValueError("step cannot be 0")
        if (end - start) * step < 0:
            raise ValueError("range direction mismatch")
        # inclusive end
        return list(range(start, end + (1 if step > 0 else -1), step))
    return [int(s)]


def _load_close_and_time(cfg: MacdStrategy6Config) -> tuple[np.ndarray, np.ndarray]:
    import hdf5plugin  # noqa: F401  # 注册 HDF5 压缩插件
    import h5py

    path = cfg.data_path
    if not path.exists():
        raise FileNotFoundError(f"H5 not found: {path}")

    with h5py.File(path, "r") as f:
        if cfg.h5_dataset not in f:
            raise KeyError(f"Dataset '{cfg.h5_dataset}' not found in H5: {path}")
        dset = f[cfg.h5_dataset]
        close = dset["close"][:].astype(np.float64, copy=False)
        t = dset[cfg.time_col][:].astype(np.int64, copy=False)
    return close, t


@nb.njit(cache=True)
def _eval_macd_kelly(
    close: np.ndarray,
    fast: int,
    slow: int,
    signal: int,
    fee_rate: float,
    slippage_rate: float,
    qty_step: float,
    min_order_notional: float,
    initial_capital: float,
    kelly_window_trades: int,
    kelly_min_trades: int,
    leverage_init: float,
    leverage_min: float,
    leverage_max: float,
) -> tuple[float, float, int, float, float, int, float]:
    """
    单标的分钟线 MACD(快/慢/信号) 金叉做多、死叉做空 + 凯利仓位管理，返回：
    - final_equity
    - max_drawdown (0~-1)
    - turnover_events (发生调仓/换向次数)
    - total_turnover
    - total_cost (手续费+滑点)
    - completed_trades (实际完成的交易笔数)
    - avg_leverage (仅在开仓/换向时统计)
    """
    n = len(close)
    if n == 0:
        return 0.0, 0.0, 0, 0.0, 0.0, 0, 0.0

    alpha_fast = 2.0 / (fast + 1.0)
    alpha_slow = 2.0 / (slow + 1.0)
    alpha_sig = 2.0 / (signal + 1.0)
    cost_rate = fee_rate + slippage_rate

    ema_f = close[0]
    ema_s = close[0]
    dea = 0.0
    prev_hist = 0.0

    equity = float(initial_capital)
    peak = float(initial_capital)
    max_dd = 0.0

    cur_qty = 0.0
    last_mark = close[0]

    cur_dir = 0  # -1/0/1，表示“实际持仓方向”，与 cur_qty 一致
    entry_price = 0.0

    # kelly 交易收益历史（单位名义收益率），环形缓冲区
    if kelly_window_trades <= 0:
        kelly_window_trades = 1
    buf = np.zeros(kelly_window_trades, dtype=np.float64)
    buf_len = 0
    buf_pos = 0
    completed_trades = 0

    sum_lev = 0.0
    lev_entries = 0

    def _round_qty(raw_qty: float) -> float:
        lots = np.floor(np.abs(raw_qty) / qty_step)
        return np.sign(raw_qty) * lots * qty_step

    def _kelly_fraction() -> float:
        if completed_trades < kelly_min_trades:
            return leverage_init

        m = buf_len
        wins = 0
        losses = 0
        sum_win = 0.0
        sum_loss = 0.0
        for j in range(m):
            r = buf[j]
            if r > 0.0:
                wins += 1
                sum_win += r
            else:
                losses += 1
                sum_loss += -r

        if wins == 0 or losses == 0:
            return leverage_min

        p = wins / (wins + losses)
        avg_win = sum_win / wins
        avg_loss = sum_loss / losses
        if avg_win <= 0.0 or avg_loss <= 0.0:
            return leverage_min
        b = avg_win / avg_loss
        f = p - (1.0 - p) / b

        if not np.isfinite(f) or f <= 0.0:
            f = leverage_min
        if f < leverage_min:
            f = leverage_min
        elif f > leverage_max:
            f = leverage_max
        return f

    turnover_events = 0
    total_turnover = 0.0
    total_cost = 0.0

    for i in range(n):
        m = close[i]
        if not np.isfinite(m) or m <= 0.0:
            continue

        # 1) 先按 mark-to-market 结算持仓盈亏
        equity += (m - last_mark) * cur_qty
        last_mark = m

        if equity > peak:
            peak = equity
        dd = equity / peak - 1.0
        if dd < max_dd:
            max_dd = dd

        # 2) MACD 更新（EMA 递推，等价于 pandas ewm(adjust=False)）
        ema_f = ema_f + alpha_fast * (m - ema_f)
        ema_s = ema_s + alpha_slow * (m - ema_s)
        dif = ema_f - ema_s
        dea = dea + alpha_sig * (dif - dea)
        hist = dif - dea

        cross_up = hist > 0.0 and prev_hist <= 0.0
        cross_down = hist < 0.0 and prev_hist >= 0.0
        prev_hist = hist

        desired_dir = cur_dir
        if cross_up:
            desired_dir = 1
        elif cross_down:
            desired_dir = -1

        if desired_dir == cur_dir:
            continue

        # 3) 若原来有仓位，先记录本笔交易的“单位名义收益率”用于更新凯利
        if cur_dir != 0:
            ratio = m / entry_price
            unit_ret = cur_dir * (ratio - 1.0) - cost_rate * (1.0 + ratio)
            if buf_len < kelly_window_trades:
                buf[buf_len] = unit_ret
                buf_len += 1
            else:
                buf[buf_pos] = unit_ret
                buf_pos = (buf_pos + 1) % kelly_window_trades
            completed_trades += 1

        # 4) 计算新一笔的凯利仓位（仅在换向时更新）
        lev = _kelly_fraction()
        sum_lev += lev
        lev_entries += 1

        # 5) 执行调仓（执行价=close，手续费+滑点按单边成交额计）
        target_qty = 0.0
        if desired_dir != 0:
            target_notional = equity * lev
            raw_qty = desired_dir * (target_notional / m)
            target_qty = _round_qty(raw_qty)
            if abs(target_qty) * m < min_order_notional:
                target_qty = 0.0
                desired_dir = 0

        delta_qty = target_qty - cur_qty
        if delta_qty != 0.0:
            t = abs(delta_qty) * m
            tc = t * cost_rate
            equity -= tc
            total_turnover += t
            total_cost += tc
            turnover_events += 1
            cur_qty = target_qty

        cur_dir = desired_dir
        if cur_dir != 0:
            entry_price = m

        if equity > peak:
            peak = equity
        dd = equity / peak - 1.0
        if dd < max_dd:
            max_dd = dd
        if equity <= 0.0:
            equity = 0.0
            break

    avg_lev = (sum_lev / lev_entries) if lev_entries > 0 else 0.0
    return equity, max_dd, turnover_events, total_turnover, total_cost, completed_trades, avg_lev


def main() -> None:
    cfg = MacdStrategy6Config()
    close, t = _load_close_and_time(cfg)

    days = float((t[-1] - t[0]) / 1_000_000_000 / 86400)
    print(f"[MACD6-Search] data={cfg.data_path} bars={len(close):,} span_days={days:.2f}")
    print(f"[MACD6-Search] cfg={asdict(cfg)}")

    # 默认搜索网格：可用环境变量覆盖
    fast_grid = _parse_grid(sys.argv[1]) if len(sys.argv) > 1 else [12, 26, 60, 120, 240, 480, 720, 960]
    slow_grid = (
        _parse_grid(sys.argv[2])
        if len(sys.argv) > 2
        else [26, 60, 120, 240, 480, 960, 2400, 4800, 7200, 9600, 10800, 12000, 14400]
    )
    sig_grid = _parse_grid(sys.argv[3]) if len(sys.argv) > 3 else [9, 26, 60, 120, 240, 480]

    results: list[dict] = []
    total = 0
    for fast in fast_grid:
        for slow in slow_grid:
            if slow <= fast:
                continue
            for sig in sig_grid:
                total += 1
                equity, max_dd, n_turn, turnover, cost, trades, avg_lev = _eval_macd_kelly(
                    close=close,
                    fast=int(fast),
                    slow=int(slow),
                    signal=int(sig),
                    fee_rate=float(cfg.fee_rate),
                    slippage_rate=float(cfg.slippage_rate),
                    qty_step=float(cfg.qty_step),
                    min_order_notional=float(cfg.min_order_notional),
                    initial_capital=float(cfg.initial_capital),
                    kelly_window_trades=int(cfg.kelly_window_trades),
                    kelly_min_trades=int(cfg.kelly_min_trades),
                    leverage_init=float(cfg.leverage_init),
                    leverage_min=float(cfg.leverage_min),
                    leverage_max=float(cfg.leverage_max),
                )
                net = float(equity / cfg.initial_capital) if cfg.initial_capital > 0 else float("nan")
                annual = float(net ** (365.0 / days) - 1.0) if net > 0 and days > 0 else float("nan")
                results.append(
                    {
                        "fast": int(fast),
                        "slow": int(slow),
                        "signal": int(sig),
                        "net": net,
                        "return_pct": (net - 1.0) * 100.0,
                        "annual_pct": annual * 100.0,
                        "max_dd_pct": max_dd * 100.0,
                        "turnover_events": int(n_turn),
                        "trades": int(trades),
                        "cost": float(cost),
                        "avg_lev": float(avg_lev),
                    }
                )

    results.sort(key=lambda x: (x["net"], x["max_dd_pct"]), reverse=True)
    best = results[0] if results else None

    top_n = 20 if len(results) >= 20 else len(results)
    print(f"\n[MACD6-Search] evaluated={len(results):,}/{total:,} combos, TOP{top_n} by net:")
    for i in range(top_n):
        r = results[i]
        print(
            f"{i+1:>2d}) fast={r['fast']:>2d} slow={r['slow']:>2d} sig={r['signal']:>2d} "
            f"net={r['net']:.4f} rtn={r['return_pct']:+.2f}% ann={r['annual_pct']:+.2f}% "
            f"dd={r['max_dd_pct']:+.2f}% trades={r['trades']:,} cost={r['cost']:.2f} lev~{r['avg_lev']:.3f}"
        )

    if best:
        print("\n[MACD6-Search] BEST:", best)


if __name__ == "__main__":
    main()
