# -*- coding: utf-8 -*-
"""
七号 VWAP 策略（V7.3.1 布林带回归 + 止损）- 启动回测 + 参数遍历

你关心的点（先用人话说清楚）：
1) 这是“新增”的 V7.3.1 专属脚本，不会覆盖/修改 `启动回测.py`（V7.3 原版保留）。
2) 策略规则很“硬”（简单清晰），但“简单 ≠ 一定赚钱”：
   - 市场如果一直单边上涨/下跌，回归策略会反复在错误方向开仓/止损，回测就会很差。
   - 所以最重要的是：把 `N（周期）` 和 `k（轨道倍数）` 找到更合适的组合，并且要做样本外验证（防止过拟合）。

V7.3.1 规则（严格按你描述）：
    - 开仓：
        * Price > Upper  -> 做空
        * Price < Lower  -> 做多
    - 止盈：价格回归并“触碰 VWAP（中轨）”就平仓
    - 止损：价格继续突破到 (k+1)×标准差 时止损
        * 做空止损线：VWAP + (k+1)×σ
        * 做多止损线：VWAP - (k+1)×σ

性能（为什么这份脚本更快）：
    - 用 Numba（即时编译：把 Python 循环“翻译成机器码”运行）加速核心回测循环；
    - 参数遍历时：每个 N 只算一次 VWAP/标准差，然后快速遍历多个 k。

运行示例：
    - 单次回测（不画图）：
        python3 -X utf8 Quant_Unified/策略仓库/七号VWAP策略/v7.3_布林带/启动回测_v7.3.1.py --no-chart
    - 参数遍历（按夏普比排序，输出前 20 个）：
        python3 -X utf8 Quant_Unified/策略仓库/七号VWAP策略/v7.3_布林带/启动回测_v7.3.1.py --grid-search --top 20
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
import time
import warnings

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
策略版本 = "V7.3.1"

# 默认参数：你明确说了 v7.3.1 初始 k=2
默认N = 1391
默认k = 2.0
默认加权方式 = "EMA"  # EMA / SMA

开始日期 = "2021-01-01"
结束日期 = "2025-06-15"

手续费率 = 0.0000  # 模拟 Maker (0 费率)
滑点 = 0.0001
初始资金 = 10000
杠杆 = 1.0
每年周期数 = 525600  # 1 分钟线：一年大约 365*24*60

数据路径 = 获取分钟K线H5文件(
    生成分钟K线文件名("ETHUSDT", 开始日期="2019-11-01", 结束日期="2025-06-15", 带table后缀=True)
)


def 加载数据(file_path: str | Path, start: str | None, end: str | None) -> pd.DataFrame:
    print(f"📂 [{策略版本}] 正在加载 ETH 历史分钟数据…")
    import h5py  # 依赖在项目里已用到
    import hdf5plugin  # noqa: F401  # 让 h5py 能读压缩数据

    file_path = str(file_path)
    with h5py.File(file_path, "r") as f:
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


def 计算vwap与标准差(df: pd.DataFrame, n: int, 加权方式: str) -> tuple[np.ndarray, np.ndarray]:
    """
    计算 VWAP（中轨）和标准差 σ（用于上下轨）。

    为什么 σ 用 close 的标准差？
        类比：我们要的是“价格本身”最近波动有多大，而不是 VWAP 的波动。
        这在很多交易系统里是常见做法，速度也更快。
    """

    if n <= 1:
        raise ValueError("n 必须 > 1（否则标准差没有意义）。")

    加权方式 = 加权方式.upper().strip()
    if 加权方式 not in {"EMA", "SMA"}:
        raise ValueError("加权方式只支持 EMA 或 SMA。")

    if 加权方式 == "EMA":
        vwap = (
            df["quote_volume"].ewm(span=n, min_periods=n).mean()
            / df["volume"].ewm(span=n, min_periods=n).mean()
        )
        std = df["close"].ewm(span=n, min_periods=n).std()
    else:
        vwap = df["quote_volume"].rolling(n, min_periods=n).sum() / df["volume"].rolling(n, min_periods=n).sum()
        std = df["close"].rolling(n, min_periods=n).std()

    return vwap.to_numpy(dtype=np.float64), std.to_numpy(dtype=np.float64)


@njit(cache=True)
def _计算夏普_v731_回归止损(
    close: np.ndarray,
    vwap: np.ndarray,
    std: np.ndarray,
    k: float,
    fee: float,
    slippage: float,
    leverage: float,
    periods_per_year: int,
) -> float:
    """
    只算“夏普比”（Sharpe Ratio：用波动率归一化后的收益表现），用于参数遍历加速。
    说明：这里不扣无风险利率（当作 0）。
    """

    cost = fee + slippage
    curr_pos = 0  # 0 空仓，1 多，-1 空

    mean = 0.0
    m2 = 0.0
    count = 0

    for i in range(1, close.shape[0]):
        price = close[i]
        m = vwap[i]
        s = std[i]

        pos_prev = curr_pos

        if not np.isnan(m) and not np.isnan(s):
            upper = m + k * s
            lower = m - k * s
            upper_stop = m + (k + 1.0) * s
            lower_stop = m - (k + 1.0) * s

            if curr_pos == 0:
                if price > upper:
                    curr_pos = -1
                elif price < lower:
                    curr_pos = 1
            elif curr_pos == 1:
                if price <= lower_stop:
                    curr_pos = 0
                elif price >= m:
                    curr_pos = 0
            else:  # curr_pos == -1
                if price >= upper_stop:
                    curr_pos = 0
                elif price <= m:
                    curr_pos = 0

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
def _回测_v731_回归止损_生成持仓与收益(
    close: np.ndarray,
    vwap: np.ndarray,
    std: np.ndarray,
    k: float,
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

    for i in range(1, n):
        price = close[i]
        m = vwap[i]
        s = std[i]

        pos_prev = curr_pos

        if not np.isnan(m) and not np.isnan(s):
            upper = m + k * s
            lower = m - k * s
            upper_stop = m + (k + 1.0) * s
            lower_stop = m - (k + 1.0) * s

            if curr_pos == 0:
                if price > upper:
                    curr_pos = -1
                elif price < lower:
                    curr_pos = 1
            elif curr_pos == 1:
                if price <= lower_stop:
                    curr_pos = 0
                elif price >= m:
                    curr_pos = 0
            else:  # curr_pos == -1
                if price >= upper_stop:
                    curr_pos = 0
                elif price <= m:
                    curr_pos = 0

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
    n_min: int = 200
    n_max: int = 2000
    n_step: int = 100
    k_min: float = 1.0
    k_max: float = 4.0
    k_step: float = 0.1
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

    # 用整数刻度避免浮点累积误差（比如 0.1 + 0.2 变成 0.30000000004）
    scale = 1000
    min_i = int(round(min_v * scale))
    max_i = int(round(max_v * scale))
    step_i = int(round(step * scale))
    if step_i <= 0:
        raise ValueError("k_step 太小，导致步长为 0。")

    values = []
    for x in range(min_i, max_i + 1, step_i):
        values.append(x / scale)
    return values


def 遍历参数_按夏普排序(
    df: pd.DataFrame,
    加权方式: str,
    cfg: 参数遍历配置,
) -> pd.DataFrame:
    print("🚀 开始参数遍历（按夏普比排序）…")
    print(f"   N: {cfg.n_min}..{cfg.n_max} step={cfg.n_step}")
    print(f"   k: {cfg.k_min}..{cfg.k_max} step={cfg.k_step}")
    print(f"   加权方式: {加权方式}")

    close = df["close"].to_numpy(dtype=np.float64)
    n_list = _生成整数网格(cfg.n_min, cfg.n_max, cfg.n_step)
    k_list = _生成浮点网格(cfg.k_min, cfg.k_max, cfg.k_step)
    total = len(n_list) * len(k_list)
    print(f"   组合数: {total:,}")

    # 预热编译（避免第一次调用把“编译时间”算进遍历）
    if NUMBA可用 and len(close) >= 10:
        _ = _计算夏普_v731_回归止损(close[:10], close[:10], close[:10], 2.0, 0.0, 0.0, 1.0, 10)

    results: list[tuple[float, int, float]] = []
    t0 = time.time()

    for idx, n in enumerate(n_list, start=1):
        vwap, std = 计算vwap与标准差(df, n=n, 加权方式=加权方式)

        for k in k_list:
            sharpe = _计算夏普_v731_回归止损(
                close=close,
                vwap=vwap,
                std=std,
                k=float(k),
                fee=float(手续费率),
                slippage=float(滑点),
                leverage=float(杠杆),
                periods_per_year=int(每年周期数),
            )
            results.append((float(sharpe), int(n), float(k)))

        spent = time.time() - t0
        avg = spent / idx
        eta = avg * (len(n_list) - idx)
        print(f"   进度: {idx}/{len(n_list)} (n={n}) | 用时 {spent:.1f}s | 预计剩余 {eta:.1f}s")

    out = pd.DataFrame(results, columns=["sharpe", "n", "k"])
    out.sort_values(["sharpe"], ascending=False, inplace=True, ignore_index=True)

    print("\n🏁 参数遍历完成：Top 结果（夏普越高越好）")
    print(out.head(cfg.top).to_string(index=False))
    return out


def 单次回测并输出报告(df: pd.DataFrame, n: int, k: float, 加权方式: str, 不画图: bool) -> None:
    print(f"⚙️  单次回测：{策略版本} | N={n} k={k} {加权方式}")

    vwap, std = 计算vwap与标准差(df, n=n, 加权方式=加权方式)
    close = df["close"].to_numpy(dtype=np.float64)

    # 预热编译
    if NUMBA可用 and len(close) >= 10:
        _ = _回测_v731_回归止损_生成持仓与收益(close[:10], close[:10], close[:10], 2.0, 0.0, 0.0, 1.0)

    pos, ret = _回测_v731_回归止损_生成持仓与收益(
        close=close,
        vwap=vwap,
        std=std,
        k=float(k),
        fee=float(手续费率),
        slippage=float(滑点),
        leverage=float(杠杆),
    )

    equity = (1.0 + pd.Series(ret, index=df.index)).cumprod()
    equity_val = equity.values * 初始资金

    策略名称 = f"VWAP {策略版本} (Reversion_Stop) N={n} K={k} {加权方式}"
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
            保存路径=PROJECT_ROOT / "策略仓库/七号VWAP策略/v7.3_布林带",
        )
        可视化.生成报告(策略名称=策略名称)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--no-chart", action="store_true", help="不显示图表")
    parser.add_argument("--grid-search", action="store_true", help="遍历 N/K 参数并按夏普排序")
    parser.add_argument("--n", type=int, default=默认N, help="单次回测：周期 N")
    parser.add_argument("--k", type=float, default=默认k, help="单次回测：轨道倍数 k（默认 2）")
    parser.add_argument("--weighting", type=str, default=默认加权方式, help="EMA / SMA")

    # 参数遍历范围
    parser.add_argument("--n-min", type=int, default=参数遍历配置.n_min)
    parser.add_argument("--n-max", type=int, default=参数遍历配置.n_max)
    parser.add_argument("--n-step", type=int, default=参数遍历配置.n_step)
    parser.add_argument("--k-min", type=float, default=参数遍历配置.k_min)
    parser.add_argument("--k-max", type=float, default=参数遍历配置.k_max)
    parser.add_argument("--k-step", type=float, default=参数遍历配置.k_step)
    parser.add_argument("--top", type=int, default=参数遍历配置.top)
    args = parser.parse_args()

    if not NUMBA可用:
        print("⚠️  提醒：Numba 不可用，参数遍历会慢很多（但仍然能跑）。")

    df = 加载数据(数据路径, 开始日期, 结束日期)

    if args.grid_search:
        cfg = 参数遍历配置(
            n_min=int(args.n_min),
            n_max=int(args.n_max),
            n_step=int(args.n_step),
            k_min=float(args.k_min),
            k_max=float(args.k_max),
            k_step=float(args.k_step),
            top=int(args.top),
        )
        out = 遍历参数_按夏普排序(df=df, 加权方式=args.weighting, cfg=cfg)

        保存路径 = PROJECT_ROOT / "策略仓库/七号VWAP策略/v7.3_布林带" / "v7.3.1_参数遍历结果.csv"
        out.to_csv(保存路径, index=False)
        print(f"\n💾 已保存参数遍历结果：{保存路径}")
        return

    单次回测并输出报告(
        df=df,
        n=int(args.n),
        k=float(args.k),
        加权方式=args.weighting,
        不画图=bool(args.no_chart),
    )


if __name__ == "__main__":
    main()

