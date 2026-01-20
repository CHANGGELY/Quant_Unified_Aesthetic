# -*- coding: utf-8 -*-
"""
七号 VWAP 策略（V7.5 量价背离：VWAP vs TWAP 高阶博弈）- 启动回测 + 参数遍历

你给的核心点（用人话讲清楚）：
    - VWAP（Volume Weighted Average Price：成交量加权平均价）
      类比：谁买得多（成交量大），谁的话语权大。
    - TWAP（Time Weighted Average Price：时间加权平均价）
      类比：每一分钟都算同样一票，不看成交量大小。
    - 如果 VWAP > TWAP：说明“成交量主要发生在更高的价格”，更像是资金在高位也愿意成交 → 偏多
    - 如果 VWAP < TWAP：说明“价格涨上去了但没量”，更像是深夜小资金虚拉 → 偏空/假突破

因子（Signal）：
    Signal = (VWAP - TWAP) / TWAP
    - Signal > 0：VWAP 高于 TWAP（带量更强）
    - Signal < 0：VWAP 低于 TWAP（缩量/虚拉）

策略规则（按你描述落地，并补齐最小可回测的出场规则）：
    做多（趋势健康）：
        - Uptrend（上涨趋势）：Price > TWAP 且 TWAP 斜率向上（TWAP[i] > TWAP[i-1]）
        - Signal > threshold（比如 0.05% = 0.0005）
    做空（反转：假突破）：
        - Price 创新高（相对过去 lookback 根的最高 close）
        - 且 Signal < 0（VWAP < TWAP）
        - 且处于 Uptrend（避免在下跌趋势里“追着做空”）
    出场（为了避免策略“扛单到死”，必须有硬规则）：
        - 多单：跌破 TWAP 或 Signal <= 0 离场；另外加一个“跌破 VWAP 一定比例”止损
        - 空单：回落到 TWAP（price <= TWAP）或 Signal >= 0 离场；另外加一个“涨破 VWAP 一定比例”止损
        - 可选：移动止盈（trailing_stop_pct > 0 时开启）

性能：
    - 核心回测循环用 Numba（即时编译：把 Python 循环编译成机器码运行）
    - 参数遍历按夏普比（Sharpe Ratio：收益/波动）排序，快速判断方向是否值得深挖
"""

from __future__ import annotations

import math
import sys
import time
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ====== 自动计算项目根目录 ======
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[3]  # Quant_Unified
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from 基础库.common_core.backtest.metrics import 回测指标计算器
from 基础库.common_core.backtest.可视化 import 回测可视化
from 基础库.common_core.data_center import 生成分钟K线文件名, 获取分钟K线H5文件

try:
    from numba import njit

    NUMBA可用 = True
except Exception:
    NUMBA可用 = False

    def njit(*_args, **_kwargs):  # type: ignore
        def 装饰器(fn):
            return fn

        return 装饰器


# ======================= [核心配置区域] =======================
策略版本 = "V7.5量价背离策略"

开始日期 = "2021-01-01"
结束日期 = "2025-06-15"

初始资金 = 10000
杠杆 = 1.0
手续费率 = 0.0000  # 模拟 Maker
滑点 = 0.0001
每年周期数 = 525600  # 1 分钟线：365*24*60

# 默认参数（先给一个“能跑通”的直觉组合，最终以遍历结果为准）
默认VWAP_N = 600
默认TWAP窗口 = 60
默认阈值 = 0.0005  # 0.05%
默认新高窗口 = 240  # 4 小时（分钟线）
默认止损比例 = 0.006  # 0.6%
默认移动止盈比例 = 0.0  # 0 表示关闭

数据路径 = 获取分钟K线H5文件(
    生成分钟K线文件名("ETHUSDT", 开始日期="2019-11-01", 结束日期="2025-06-15", 带table后缀=True)
)


def 加载数据(file_path: str | Path, start: str | None, end: str | None) -> pd.DataFrame:
    print(f"📂 [{策略版本}] 正在加载 ETH 历史分钟数据…")
    import h5py
    import hdf5plugin  # noqa: F401

    with h5py.File(str(file_path), "r") as f:
        dset = f["klines/table"]
        data = dset[:]

    df = pd.DataFrame(data)

    if "candle_begin_time_GMT8" in df.columns:
        df["candle_begin_time"] = pd.to_datetime(df["candle_begin_time_GMT8"])
        df.set_index("candle_begin_time", inplace=True)
        df.drop(columns=["candle_begin_time_GMT8"], inplace=True)

    if "quote_volume" not in df.columns:
        df["quote_volume"] = df["close"] * df["volume"]

    if start:
        df = df[df.index >= pd.to_datetime(start)]
    if end:
        df = df[df.index <= pd.to_datetime(end)]

    if len(df) == 0:
        raise ValueError("数据为空：请检查开始/结束日期与数据文件是否匹配。")

    print(f"✅ 加载成功：{len(df):,} 根 1m K 线")
    return df


def 计算VWAP(df: pd.DataFrame, n: int, 加权方式: str = "EMA") -> np.ndarray:
    """
    VWAP（成交量加权平均价）。
    """

    if n <= 1:
        raise ValueError("VWAP_N 必须 > 1。")

    加权方式 = 加权方式.upper().strip()
    if 加权方式 not in {"EMA", "SMA"}:
        raise ValueError("加权方式只支持 EMA 或 SMA。")

    if 加权方式 == "EMA":
        vwap = (
            df["quote_volume"].ewm(span=n, min_periods=n).mean()
            / df["volume"].ewm(span=n, min_periods=n).mean()
        )
    else:
        vwap = df["quote_volume"].rolling(n, min_periods=n).sum() / df["volume"].rolling(n, min_periods=n).sum()

    return vwap.to_numpy(dtype=np.float64)


def 计算TWAP(df: pd.DataFrame, 窗口: int) -> np.ndarray:
    """
    TWAP（时间加权平均价）：最自然实现就是 close 的 SMA。
    """

    if 窗口 <= 1:
        raise ValueError("TWAP窗口 必须 > 1。")

    twap = df["close"].rolling(窗口, min_periods=窗口).mean()
    return twap.to_numpy(dtype=np.float64)


def 计算过去新高_不含当前(df: pd.DataFrame, lookback: int) -> np.ndarray:
    """
    过去 lookback 根的最高 close（不包含当前这一根），用于判断“创新高”。
    """

    if lookback <= 1:
        raise ValueError("新高窗口 lookback 必须 > 1。")

    prev_high = df["close"].rolling(lookback, min_periods=lookback).max().shift(1)
    return prev_high.to_numpy(dtype=np.float64)


@njit(cache=True)
def _计算夏普_v75_量价背离(
    close: np.ndarray,
    vwap: np.ndarray,
    twap: np.ndarray,
    prev_high: np.ndarray,
    threshold: float,
    stop_loss_pct: float,
    trailing_stop_pct: float,
    fee: float,
    slippage: float,
    leverage: float,
    periods_per_year: int,
) -> float:
    """
    只算夏普比（Sharpe Ratio），用于参数遍历提速。
    """

    cost = fee + slippage
    curr_pos = 0  # 0 空仓，1 多，-1 空
    trail_high = 0.0
    trail_low = 0.0

    mean = 0.0
    m2 = 0.0
    count = 0

    for i in range(1, close.shape[0]):
        price = close[i]
        v = vwap[i]
        t = twap[i]

        pos_prev = curr_pos

        # 只有在指标都有效时才交易
        if not np.isnan(v) and not np.isnan(t) and t != 0.0:
            t_prev = twap[i - 1]
            uptrend = (price > t) and (not np.isnan(t_prev)) and (t > t_prev)

            signal = (v - t) / t

            # ===== 先处理出场（更安全：先保命）=====
            if curr_pos == 1:
                if price <= v * (1.0 - stop_loss_pct):
                    curr_pos = 0
                elif trailing_stop_pct > 0.0 and price <= trail_high * (1.0 - trailing_stop_pct):
                    curr_pos = 0
                elif price < t or signal <= 0.0:
                    curr_pos = 0
            elif curr_pos == -1:
                if price >= v * (1.0 + stop_loss_pct):
                    curr_pos = 0
                elif trailing_stop_pct > 0.0 and price >= trail_low * (1.0 + trailing_stop_pct):
                    curr_pos = 0
                elif price <= t or signal >= 0.0:
                    curr_pos = 0

            # ===== 再处理入场（允许反手）=====
            if curr_pos == 0:
                # 做多：上涨趋势 + 强信号（带量上涨更健康）
                if uptrend and signal > threshold:
                    curr_pos = 1
                    trail_high = price
                else:
                    # 做空：创新高，但 Signal < 0（假突破），且仍在上涨趋势（更贴近你描述的“深夜虚拉”）
                    ph = prev_high[i]
                    if uptrend and (not np.isnan(ph)) and price > ph and signal < 0.0:
                        curr_pos = -1
                        trail_low = price

            # 更新 trailing
            if curr_pos == 1:
                if price > trail_high:
                    trail_high = price
            elif curr_pos == -1:
                if trail_low == 0.0 or price < trail_low:
                    trail_low = price

        prev_close = close[i - 1]
        if prev_close == 0.0:
            mkt_ret = 0.0
        else:
            mkt_ret = price / prev_close - 1.0

        change_pos = abs(curr_pos - pos_prev)
        strat_ret = pos_prev * mkt_ret * leverage - change_pos * cost

        count += 1
        delta = strat_ret - mean
        mean += delta / count
        m2 += delta * (strat_ret - mean)

    if count <= 1:
        return -1e18

    var = m2 / (count - 1)
    if var <= 0.0:
        return -1e18

    std_ret = math.sqrt(var)
    return (mean / std_ret) * math.sqrt(float(periods_per_year))


@njit(cache=True)
def _回测_v75_量价背离_生成持仓与收益(
    close: np.ndarray,
    vwap: np.ndarray,
    twap: np.ndarray,
    prev_high: np.ndarray,
    threshold: float,
    stop_loss_pct: float,
    trailing_stop_pct: float,
    fee: float,
    slippage: float,
    leverage: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    生成逐根持仓（pos）与策略收益（ret），用于单次回测输出报告/画图。
    """

    n = close.shape[0]
    pos = np.zeros(n, dtype=np.int8)
    ret = np.zeros(n, dtype=np.float64)

    cost = fee + slippage
    curr_pos = 0
    trail_high = 0.0
    trail_low = 0.0

    for i in range(1, n):
        price = close[i]
        v = vwap[i]
        t = twap[i]

        pos_prev = curr_pos

        if not np.isnan(v) and not np.isnan(t) and t != 0.0:
            t_prev = twap[i - 1]
            uptrend = (price > t) and (not np.isnan(t_prev)) and (t > t_prev)
            signal = (v - t) / t

            # 出场
            if curr_pos == 1:
                if price <= v * (1.0 - stop_loss_pct):
                    curr_pos = 0
                elif trailing_stop_pct > 0.0 and price <= trail_high * (1.0 - trailing_stop_pct):
                    curr_pos = 0
                elif price < t or signal <= 0.0:
                    curr_pos = 0
            elif curr_pos == -1:
                if price >= v * (1.0 + stop_loss_pct):
                    curr_pos = 0
                elif trailing_stop_pct > 0.0 and price >= trail_low * (1.0 + trailing_stop_pct):
                    curr_pos = 0
                elif price <= t or signal >= 0.0:
                    curr_pos = 0

            # 入场（允许反手）
            if curr_pos == 0:
                if uptrend and signal > threshold:
                    curr_pos = 1
                    trail_high = price
                else:
                    ph = prev_high[i]
                    if uptrend and (not np.isnan(ph)) and price > ph and signal < 0.0:
                        curr_pos = -1
                        trail_low = price

            # 更新 trailing
            if curr_pos == 1:
                if price > trail_high:
                    trail_high = price
            elif curr_pos == -1:
                if trail_low == 0.0 or price < trail_low:
                    trail_low = price

        prev_close = close[i - 1]
        if prev_close == 0.0:
            mkt_ret = 0.0
        else:
            mkt_ret = price / prev_close - 1.0

        change_pos = abs(curr_pos - pos_prev)
        ret[i] = pos_prev * mkt_ret * leverage - change_pos * cost
        pos[i] = curr_pos

    return pos, ret


@dataclass(frozen=True)
class 参数遍历配置:
    # VWAP N（默认更粗一点，保证“快速判断方向”）
    n_min: int = 200
    n_max: int = 2000
    n_step: int = 200

    # TWAP 窗口（用少量候选值，避免组合爆炸）
    twap_windows: tuple[int, ...] = (30, 60, 120)

    # 阈值 threshold（Signal > threshold 才做多）
    threshold_min: float = 0.0002
    threshold_max: float = 0.0012
    threshold_step: float = 0.0002

    # 创新高 lookback（少量候选值）
    lookbacks: tuple[int, ...] = (60, 120, 240)

    # 止损比例（相对 VWAP）
    stop_pcts: tuple[float, ...] = (0.003, 0.005, 0.008)

    trailing_stop_pct: float = 默认移动止盈比例
    top: int = 20


def _生成整数网格(min_v: int, max_v: int, step: int) -> list[int]:
    if step <= 0:
        raise ValueError("step 必须 > 0。")
    if max_v < min_v:
        raise ValueError("max 必须 >= min。")
    return list(range(min_v, max_v + 1, step))


def _生成浮点网格(min_v: float, max_v: float, step: float) -> list[float]:
    if step <= 0:
        raise ValueError("step 必须 > 0。")
    if max_v < min_v:
        raise ValueError("max 必须 >= min。")

    scale = 1_000_000  # 解决浮点累积误差（threshold 很小）
    min_i = int(round(min_v * scale))
    max_i = int(round(max_v * scale))
    step_i = int(round(step * scale))
    if step_i <= 0:
        raise ValueError("步长太小，导致 step=0。")

    values: list[float] = []
    for x in range(min_i, max_i + 1, step_i):
        values.append(x / scale)
    return values


def 遍历参数_按夏普排序(
    df: pd.DataFrame,
    cfg: 参数遍历配置,
    vwap_weighting: str = "EMA",
) -> pd.DataFrame:
    print("🚀 开始参数遍历（按夏普排序）…")
    print(f"   VWAP_N: {cfg.n_min}..{cfg.n_max} step={cfg.n_step}")
    print(f"   TWAP windows: {list(cfg.twap_windows)}")
    print(f"   threshold: {cfg.threshold_min}..{cfg.threshold_max} step={cfg.threshold_step}")
    print(f"   lookback: {list(cfg.lookbacks)}")
    print(f"   stop_pcts: {list(cfg.stop_pcts)}")
    print(f"   trailing_stop_pct: {cfg.trailing_stop_pct}")

    close = df["close"].to_numpy(dtype=np.float64)
    n_list = _生成整数网格(cfg.n_min, cfg.n_max, cfg.n_step)
    threshold_list = _生成浮点网格(cfg.threshold_min, cfg.threshold_max, cfg.threshold_step)

    # 预先计算 TWAP 与 prev_high（少量候选值，计算一次就复用）
    twap_map: dict[int, np.ndarray] = {w: 计算TWAP(df, w) for w in cfg.twap_windows}
    prev_high_map: dict[int, np.ndarray] = {lb: 计算过去新高_不含当前(df, lb) for lb in cfg.lookbacks}

    total = len(n_list) * len(cfg.twap_windows) * len(threshold_list) * len(cfg.lookbacks) * len(cfg.stop_pcts)
    print(f"   组合数: {total:,}")

    # 预热编译（避免第一次调用把编译时间算进遍历）
    if NUMBA可用 and len(close) >= 20:
        _ = _计算夏普_v75_量价背离(
            close[:20],
            close[:20],
            close[:20],
            close[:20],
            0.0005,
            0.005,
            0.0,
            0.0,
            0.0,
            1.0,
            10,
        )

    results: list[tuple[float, int, int, float, int, float, float]] = []
    t0 = time.time()

    done_n = 0
    for n in n_list:
        vwap = 计算VWAP(df, n=n, 加权方式=vwap_weighting)
        done_n += 1

        for twap_w, twap in twap_map.items():
            for lookback, prev_high in prev_high_map.items():
                for threshold in threshold_list:
                    for stop_pct in cfg.stop_pcts:
                        sharpe = _计算夏普_v75_量价背离(
                            close=close,
                            vwap=vwap,
                            twap=twap,
                            prev_high=prev_high,
                            threshold=float(threshold),
                            stop_loss_pct=float(stop_pct),
                            trailing_stop_pct=float(cfg.trailing_stop_pct),
                            fee=float(手续费率),
                            slippage=float(滑点),
                            leverage=float(杠杆),
                            periods_per_year=int(每年周期数),
                        )
                        results.append(
                            (
                                float(sharpe),
                                int(n),
                                int(twap_w),
                                float(threshold),
                                int(lookback),
                                float(stop_pct),
                                float(cfg.trailing_stop_pct),
                            )
                        )

        spent = time.time() - t0
        avg = spent / done_n
        eta = avg * (len(n_list) - done_n)
        print(f"   进度: {done_n}/{len(n_list)} (n={n}) | 用时 {spent:.1f}s | 预计剩余 {eta:.1f}s")

    out = pd.DataFrame(
        results,
        columns=[
            "sharpe",
            "vwap_n",
            "twap_window",
            "threshold",
            "lookback",
            "stop_loss_pct",
            "trailing_stop_pct",
        ],
    )
    out.sort_values(["sharpe"], ascending=False, inplace=True, ignore_index=True)

    print("\n🏁 参数遍历完成：Top 结果（夏普越高越好）")
    print(out.head(cfg.top).to_string(index=False))
    return out


def 单次回测并输出报告(
    df: pd.DataFrame,
    vwap_n: int,
    twap_window: int,
    threshold: float,
    lookback: int,
    stop_loss_pct: float,
    trailing_stop_pct: float,
    vwap_weighting: str,
    不画图: bool,
) -> None:
    print(
        f"⚙️  单次回测：{策略版本} | VWAP_N={vwap_n} TWAP={twap_window} "
        f"TH={threshold} LB={lookback} STOP={stop_loss_pct} TRAIL={trailing_stop_pct}"
    )

    close = df["close"].to_numpy(dtype=np.float64)
    vwap = 计算VWAP(df, n=vwap_n, 加权方式=vwap_weighting)
    twap = 计算TWAP(df, twap_window)
    prev_high = 计算过去新高_不含当前(df, lookback)

    # 预热编译
    if NUMBA可用 and len(close) >= 20:
        _ = _回测_v75_量价背离_生成持仓与收益(
            close[:20],
            close[:20],
            close[:20],
            close[:20],
            0.0005,
            0.005,
            0.0,
            0.0,
            0.0,
            1.0,
        )

    pos, ret = _回测_v75_量价背离_生成持仓与收益(
        close=close,
        vwap=vwap,
        twap=twap,
        prev_high=prev_high,
        threshold=float(threshold),
        stop_loss_pct=float(stop_loss_pct),
        trailing_stop_pct=float(trailing_stop_pct),
        fee=float(手续费率),
        slippage=float(滑点),
        leverage=float(杠杆),
    )

    equity = (1.0 + pd.Series(ret, index=df.index)).cumprod()
    equity_val = equity.values * 初始资金

    策略名称 = (
        f"VWAP {策略版本} (Divergence) VWAP_N={vwap_n} TWAP={twap_window} "
        f"TH={threshold} LB={lookback} STOP={stop_loss_pct} TRAIL={trailing_stop_pct} {vwap_weighting}"
    )
    计算器 = 回测指标计算器(
        权益曲线=equity_val,
        初始资金=初始资金,
        时间戳=equity.index,
        周期每年数量=每年周期数,
    )
    计算器.打印报告(策略名称=策略名称)

    if not 不画图:
        可视化 = 回测可视化(
            权益曲线=equity_val,
            时间序列=equity.index,
            初始资金=初始资金,
            价格序列=close,
            显示图表=True,
            保存路径=PROJECT_ROOT / "策略仓库/七号VWAP策略/v7.5_量价背离策略",
        )
        可视化.生成报告(策略名称=策略名称)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--no-chart", action="store_true", help="不显示图表")
    parser.add_argument("--grid-search", action="store_true", help="遍历参数并按夏普排序")

    # 单次回测参数
    parser.add_argument("--vwap-n", type=int, default=默认VWAP_N, help="VWAP 周期 N")
    parser.add_argument("--twap-window", type=int, default=默认TWAP窗口, help="TWAP 窗口（分钟数）")
    parser.add_argument("--threshold", type=float, default=默认阈值, help="Signal 阈值（例如 0.0005=0.05%%）")
    parser.add_argument("--lookback", type=int, default=默认新高窗口, help="创新高窗口 lookback（分钟数）")
    parser.add_argument("--stop-loss-pct", type=float, default=默认止损比例, help="止损比例（例如 0.006=0.6%%）")
    parser.add_argument("--trailing-stop-pct", type=float, default=默认移动止盈比例, help="移动止盈比例（0 关闭）")
    parser.add_argument("--vwap-weighting", type=str, default="EMA", help="VWAP 加权方式：EMA / SMA")

    # 参数遍历范围（默认就是“快速判断方向”的粗网格）
    parser.add_argument("--n-min", type=int, default=参数遍历配置.n_min)
    parser.add_argument("--n-max", type=int, default=参数遍历配置.n_max)
    parser.add_argument("--n-step", type=int, default=参数遍历配置.n_step)
    parser.add_argument("--threshold-min", type=float, default=参数遍历配置.threshold_min)
    parser.add_argument("--threshold-max", type=float, default=参数遍历配置.threshold_max)
    parser.add_argument("--threshold-step", type=float, default=参数遍历配置.threshold_step)
    parser.add_argument("--twap-windows", type=str, default="30,60,120", help="TWAP 窗口候选（逗号分隔）")
    parser.add_argument("--lookbacks", type=str, default="60,120,240", help="创新高窗口候选（逗号分隔）")
    parser.add_argument("--stop-pcts", type=str, default="0.003,0.005,0.008", help="止损比例候选（逗号分隔）")
    parser.add_argument("--top", type=int, default=参数遍历配置.top)
    args = parser.parse_args()

    if not NUMBA可用:
        print("⚠️  提醒：Numba 不可用，参数遍历会慢很多（但仍然能跑）。")

    df = 加载数据(数据路径, 开始日期, 结束日期)

    if args.grid_search:
        twap_windows = tuple(int(x.strip()) for x in str(args.twap_windows).split(",") if x.strip())
        lookbacks = tuple(int(x.strip()) for x in str(args.lookbacks).split(",") if x.strip())
        stop_pcts = tuple(float(x.strip()) for x in str(args.stop_pcts).split(",") if x.strip())

        cfg = 参数遍历配置(
            n_min=int(args.n_min),
            n_max=int(args.n_max),
            n_step=int(args.n_step),
            twap_windows=twap_windows,
            threshold_min=float(args.threshold_min),
            threshold_max=float(args.threshold_max),
            threshold_step=float(args.threshold_step),
            lookbacks=lookbacks,
            stop_pcts=stop_pcts,
            trailing_stop_pct=float(args.trailing_stop_pct),
            top=int(args.top),
        )

        out = 遍历参数_按夏普排序(df=df, cfg=cfg, vwap_weighting=str(args.vwap_weighting))

        保存路径 = PROJECT_ROOT / "策略仓库/七号VWAP策略/v7.5_量价背离策略" / "v7.5_量价背离_参数遍历结果.csv"
        out.to_csv(保存路径, index=False)
        print(f"\n💾 已保存参数遍历结果：{保存路径}")
        return

    单次回测并输出报告(
        df=df,
        vwap_n=int(args.vwap_n),
        twap_window=int(args.twap_window),
        threshold=float(args.threshold),
        lookback=int(args.lookback),
        stop_loss_pct=float(args.stop_loss_pct),
        trailing_stop_pct=float(args.trailing_stop_pct),
        vwap_weighting=str(args.vwap_weighting),
        不画图=bool(args.no_chart),
    )


if __name__ == "__main__":
    main()

