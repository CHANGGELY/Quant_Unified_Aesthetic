from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import replace

import numpy as np
import pandas as pd

# 将 Quant_Unified 和关键目录加入搜索路径（与其他策略保持一致）
QUANT_ROOT = Path(__file__).resolve().parents[2]
if str(QUANT_ROOT) not in sys.path:
    sys.path.append(str(QUANT_ROOT))

for folder in ["基础库", "服务", "策略仓库", "应用"]:
    p = QUANT_ROOT / folder
    if p.exists() and str(p) not in sys.path:
        sys.path.append(str(p))

from common_core.backtest.evaluate import strategy_evaluate  # noqa: E402
from 策略仓库.五号预测策略.program.step4_simulate import simulate_always_in  # noqa: E402
from 策略仓库.六号MACD策略.config_backtest import MacdStrategy6Config  # noqa: E402


def load_klines_from_h5(path: Path, dataset: str, time_col: str) -> pd.DataFrame:
    import hdf5plugin  # noqa: F401  # 注册 HDF5 压缩插件（blosc/zstd/...）
    import h5py

    if not path.exists():
        raise FileNotFoundError(f"H5 not found: {path}")

    with h5py.File(path, "r") as f:
        if dataset not in f:
            raise KeyError(f"Dataset '{dataset}' not found in H5: {path}")
        arr = f[dataset][:]

    df = pd.DataFrame.from_records(arr)
    if time_col not in df.columns:
        raise KeyError(f"Time col '{time_col}' not found, got cols={list(df.columns)}")

    df["candle_begin_time"] = pd.to_datetime(df[time_col], unit="ns")
    df.sort_values("candle_begin_time", inplace=True)
    df.drop_duplicates("candle_begin_time", keep="last", inplace=True)
    df.set_index("candle_begin_time", inplace=True)

    for c in ["open", "high", "low", "close", "volume"]:
        if c in df.columns:
            df[c] = df[c].astype(float)

    return df


def macd_positions(df: pd.DataFrame, fast: int, slow: int, signal: int) -> np.ndarray:
    close = df["close"].astype(float)
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    diff = dif - dea

    cross_up = (diff > 0) & (diff.shift(1) <= 0)
    cross_down = (diff < 0) & (diff.shift(1) >= 0)

    sig = pd.Series(0, index=df.index, dtype=np.int8)
    sig[cross_up] = 1
    sig[cross_down] = -1

    # 金叉做多，死叉做空：信号出现当根K线收盘立刻换向
    pos = sig.replace(0, np.nan).ffill().fillna(0).astype(np.int8).to_numpy()
    return pos


def _trade_entries_exits(pos: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(pos)
    entries: list[int] = []
    exits: list[int] = []
    directions: list[int] = []

    for i in range(n):
        prev = int(pos[i - 1]) if i > 0 else 0
        cur = int(pos[i])
        if cur == prev:
            continue
        if prev != 0:
            exits.append(i)
        if cur != 0:
            entries.append(i)
            directions.append(cur)

    # 最后一笔未平仓：exit 用 -1 占位
    if len(exits) < len(entries):
        exits.append(-1)

    return (
        np.asarray(entries, dtype=np.int64),
        np.asarray(exits, dtype=np.int64),
        np.asarray(directions, dtype=np.int8),
    )


def _unit_trade_returns(
    close: np.ndarray,
    entries: np.ndarray,
    exits: np.ndarray,
    directions: np.ndarray,
    *,
    cost_rate: float,
) -> np.ndarray:
    r = np.full(len(entries), np.nan, dtype=float)
    for i, (s, e, d) in enumerate(zip(entries, exits, directions)):
        if e < 0:
            continue
        ratio = float(close[e] / close[s])  # exit/entry
        gross = float(d) * (ratio - 1.0)
        cost = cost_rate * (1.0 + ratio)  # entry+exit turnover（相对 entry 名义）
        r[i] = gross - cost
    return r


def _kelly_fraction_from_returns(ret: np.ndarray) -> float:
    ret = np.asarray(ret, dtype=float)
    ret = ret[np.isfinite(ret)]
    if len(ret) == 0:
        return 0.0
    wins = ret[ret > 0]
    losses = ret[ret <= 0]
    p = float(len(wins) / len(ret))
    if len(losses) == 0:
        return 1.0
    if len(wins) == 0:
        return 0.0
    avg_win = float(wins.mean())
    avg_loss = float((-losses).mean())
    if avg_win <= 0 or avg_loss <= 0:
        return 0.0
    b = avg_win / avg_loss
    return p - (1.0 - p) / b


def build_kelly_leverage_series(
    pos: np.ndarray,
    close: np.ndarray,
    *,
    fee_rate: float,
    slippage_rate: float,
    window_trades: int,
    min_trades: int,
    leverage_init: float,
    leverage_min: float,
    leverage_max: float,
) -> tuple[np.ndarray, dict]:
    entries, exits, directions = _trade_entries_exits(pos)
    unit_ret = _unit_trade_returns(
        close,
        entries,
        exits,
        directions,
        cost_rate=float(fee_rate + slippage_rate),
    )

    lev_by_trade = np.full(len(entries), float(leverage_init), dtype=float)
    history: list[float] = []
    for i in range(len(entries)):
        if len(history) >= min_trades:
            window = np.asarray(history[-window_trades:], dtype=float)
            f = _kelly_fraction_from_returns(window)
        else:
            f = float(leverage_init)

        if not np.isfinite(f) or f <= 0:
            f = float(leverage_min)
        f = float(np.clip(f, leverage_min, leverage_max))
        lev_by_trade[i] = f

        r = unit_ret[i]
        if np.isfinite(r):
            history.append(float(r))

    lev_series = np.full(len(pos), float(leverage_init), dtype=float)
    for s, f in zip(entries, lev_by_trade):
        lev_series[int(s)] = float(f)

    # 方便输出/排查的一些统计
    completed = unit_ret[np.isfinite(unit_ret)]
    stats = {
        "entries": int(len(entries)),
        "completed_trades": int(len(completed)),
        "win_rate": float((completed > 0).mean()) if len(completed) else float("nan"),
        "avg_unit_win": float(completed[completed > 0].mean()) if np.any(completed > 0) else float("nan"),
        "avg_unit_loss": float((-completed[completed <= 0]).mean()) if np.any(completed <= 0) else float("nan"),
        "avg_kelly_leverage": float(np.nanmean(lev_by_trade)) if len(lev_by_trade) else float("nan"),
    }
    return lev_series, stats


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MACD6 backtest (golden cross long, death cross short) + Kelly sizing")
    parser.add_argument("--fast", type=int, default=None, help="MACD fast span (minutes, default from config)")
    parser.add_argument("--slow", type=int, default=None, help="MACD slow span (minutes, default from config)")
    parser.add_argument("--signal", type=int, default=None, help="MACD signal span (minutes, default from config)")
    args = parser.parse_args()

    cfg = MacdStrategy6Config()
    if args.fast is not None or args.slow is not None or args.signal is not None:
        cfg = replace(
            cfg,
            macd_fast=cfg.macd_fast if args.fast is None else int(args.fast),
            macd_slow=cfg.macd_slow if args.slow is None else int(args.slow),
            macd_signal=cfg.macd_signal if args.signal is None else int(args.signal),
        )
    print(f"[MACD6] symbol={cfg.symbol} data={cfg.data_path}")

    df = load_klines_from_h5(cfg.data_path, cfg.h5_dataset, cfg.time_col)
    df = df.loc[:, ["open", "high", "low", "close", "volume"]].copy()
    print(f"[MACD6] bars={len(df):,} start={df.index[0]} end={df.index[-1]}")

    pos = macd_positions(df, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    close = df["close"].to_numpy(dtype=float)

    lev, kstats = build_kelly_leverage_series(
        pos,
        close,
        fee_rate=cfg.fee_rate,
        slippage_rate=cfg.slippage_rate,
        window_trades=cfg.kelly_window_trades,
        min_trades=cfg.kelly_min_trades,
        leverage_init=cfg.leverage_init,
        leverage_min=cfg.leverage_min,
        leverage_max=cfg.leverage_max,
    )
    print(
        "[MACD6] kelly:"
        f" entries={kstats['entries']}, completed={kstats['completed_trades']},"
        f" win_rate={kstats['win_rate']:.3f}, avg_lev={kstats['avg_kelly_leverage']:.3f}"
    )

    sim = simulate_always_in(
        df,
        pos,
        fee_rate=cfg.fee_rate,
        slippage_rate=cfg.slippage_rate,
        qty_step=cfg.qty_step,
        leverage=lev,
        initial_capital=cfg.initial_capital,
        min_order_notional=cfg.min_order_notional,
        mark_col="close",
        bid_col="close",
        ask_col="close",
    )

    net = sim.equity / cfg.initial_capital
    dd = net / net.cummax() - 1.0
    total_return = float(net.iloc[-1] - 1.0)
    max_dd = float(dd.min())
    n_turnover = int((sim.turnover > 0).sum())
    total_cost = float(sim.cost.sum())

    equity_df = pd.DataFrame(
        {
            "candle_begin_time": net.index,
            "多空资金曲线": net.to_numpy(),
        }
    )
    equity_df["本周期多空涨跌幅"] = equity_df["多空资金曲线"].astype(float).pct_change().fillna(0.0)
    equity_df["是否爆仓"] = 0
    rtn, _, _, _ = strategy_evaluate(equity_df, net_col="多空资金曲线", pct_col="本周期多空涨跌幅")

    print(
        f"[MACD6] return={total_return*100:.2f}% max_dd={max_dd*100:.2f}% "
        f"turnover_events={n_turnover} cost={total_cost:.2f}USDT"
    )
    print(rtn)


if __name__ == "__main__":
    main()
