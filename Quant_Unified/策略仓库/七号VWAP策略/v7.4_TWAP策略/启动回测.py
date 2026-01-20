# -*- coding: utf-8 -*-
"""
七号 VWAP 策略（V7.4 TWAP 突破 / 趋势跟随）- 启动回测 + 参数遍历

你给的核心想法（用人话翻译一下）：
    - VWAP 就像“大资金的平均持仓成本线”。价格强势站上去，说明多头赢了，可能继续推。
    - 但“站上去”要是真的强：要有放量（成交量变大），而不是一根针扎上去又掉下来。
    - TWAP 是“时间平均价”（每分钟都算一票，不看成交量大小），用来过滤“瞬间插针”。

V7.4 策略规则（严格按你描述）：
过滤条件：
    1) 当前 Price > TWAP
    2) VWAP 斜率向上（用最简单的定义：VWAP[i] > VWAP[i-1]）
开仓（只做多）：
    1) 价格从下方上穿 VWAP（close[i-1] <= vwap[i-1] 且 close[i] > vwap[i]）
    2) 成交量显著放大：volume[i] > 过去 vol_window 根均量 * vol_multiplier
止损：
    - 价格跌破 VWAP 下方 stop_loss_pct（默认 0.5%）则离场
止盈/离场：
    - 价格跌破 TWAP 则离场
    - 可选：移动止盈（trailing_stop_pct > 0 时开启）

性能说明（为什么能快速遍历参数）：
    - 核心回测循环用 Numba 做“即时编译”（把 Python 循环编译成机器码运行）
    - 遍历时每个 N 只计算一次 VWAP，TWAP/均量预先算好，然后快速扫参数

运行示例：
    - 单次回测（不画图）：
      python3 -X utf8 Quant_Unified/策略仓库/七号VWAP策略/v7.4_TWAP策略/启动回测.py --no-chart
    - 参数遍历（按夏普排序，输出前 20）：
      python3 -X utf8 Quant_Unified/策略仓库/七号VWAP策略/v7.4_TWAP策略/启动回测.py --grid-search --top 20
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
策略版本 = "V7.4TWAP策略"

开始日期 = "2021-01-01"
结束日期 = "2025-06-15"

初始资金 = 10000
杠杆 = 1.0
手续费率 = 0.0000  # 模拟 Maker
滑点 = 0.0001
每年周期数 = 525600  # 1 分钟线：365*24*60

# 默认参数（先按你给的“直觉值”落地，然后再用遍历找更好组合）
默认VWAP_N = 300
默认TWAP窗口 = 60
默认均量窗口 = 20
默认放量倍数 = 2.0
默认止损比例 = 0.005  # 0.5%
默认移动止盈比例 = 0.0  # 0 表示关闭移动止盈（只用“跌破 TWAP 离场”）

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
    计算 VWAP（成交量加权平均价）。

    这里加权方式只提供 EMA/SMA 两种：
        - EMA：越近的数据权重越大，反应更快
        - SMA：窗口内平均，反应更平滑
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
    TWAP（Time Weighted Average Price：时间加权平均价）

    用人话：
        每一分钟都算同样一票，不看这一分钟成交量多不多。
        在分钟 K 线里，最自然的实现就是：close 的“简单移动平均”（SMA）。
    """

    if 窗口 <= 1:
        raise ValueError("TWAP窗口 必须 > 1。")

    twap = df["close"].rolling(窗口, min_periods=窗口).mean()
    return twap.to_numpy(dtype=np.float64)


def 计算均量(df: pd.DataFrame, 窗口: int) -> np.ndarray:
    """
    计算“过去窗口根的平均成交量”（不包含当前这一根，避免偷看未来）。
    """

    if 窗口 <= 1:
        raise ValueError("均量窗口 必须 > 1。")

    vol_ma = df["volume"].rolling(窗口, min_periods=窗口).mean().shift(1)
    return vol_ma.to_numpy(dtype=np.float64)


@njit(cache=True)
def _计算夏普_v74_TWAP突破(
    close: np.ndarray,
    volume: np.ndarray,
    vwap: np.ndarray,
    twap: np.ndarray,
    vol_ma: np.ndarray,
    vol_multiplier: float,
    stop_loss_pct: float,
    trailing_stop_pct: float,
    fee: float,
    slippage: float,
    leverage: float,
    periods_per_year: int,
) -> float:
    """
    只计算夏普比（Sharpe Ratio：用波动率归一化后的收益表现），用于参数遍历加速。
    """

    cost = fee + slippage
    curr_pos = 0  # 0 空仓，1 多
    trail_high = 0.0

    mean = 0.0
    m2 = 0.0
    count = 0

    for i in range(1, close.shape[0]):
        price = close[i]
        v = vwap[i]
        t = twap[i]
        vm = vol_ma[i]

        pos_prev = curr_pos

        # 信号判断（用 close 作为“当前价格”）
        if not np.isnan(v) and not np.isnan(t) and not np.isnan(vm):
            v_prev = vwap[i - 1]
            p_prev = close[i - 1]

            if curr_pos == 0:
                # 过滤：Price > TWAP && VWAP 斜率向上
                # 开仓：从下方上穿 VWAP + 放量
                if (
                    price > t
                    and v_prev == v_prev
                    and v > v_prev
                    and p_prev <= v_prev
                    and price > v
                    and volume[i] > vol_multiplier * vm
                ):
                    curr_pos = 1
                    trail_high = price
            else:
                # 更新移动止盈最高价
                if price > trail_high:
                    trail_high = price

                # 止损：跌破 VWAP 下方一定比例
                if price <= v * (1.0 - stop_loss_pct):
                    curr_pos = 0
                # 可选：移动止盈
                elif trailing_stop_pct > 0.0 and price <= trail_high * (1.0 - trailing_stop_pct):
                    curr_pos = 0
                # 离场：跌破 TWAP
                elif price < t:
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
def _回测_v74_TWAP突破_生成持仓与收益(
    close: np.ndarray,
    volume: np.ndarray,
    vwap: np.ndarray,
    twap: np.ndarray,
    vol_ma: np.ndarray,
    vol_multiplier: float,
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

    for i in range(1, n):
        price = close[i]
        v = vwap[i]
        t = twap[i]
        vm = vol_ma[i]

        pos_prev = curr_pos

        if not np.isnan(v) and not np.isnan(t) and not np.isnan(vm):
            v_prev = vwap[i - 1]
            p_prev = close[i - 1]

            if curr_pos == 0:
                if (
                    price > t
                    and v_prev == v_prev
                    and v > v_prev
                    and p_prev <= v_prev
                    and price > v
                    and volume[i] > vol_multiplier * vm
                ):
                    curr_pos = 1
                    trail_high = price
            else:
                if price > trail_high:
                    trail_high = price

                if price <= v * (1.0 - stop_loss_pct):
                    curr_pos = 0
                elif trailing_stop_pct > 0.0 and price <= trail_high * (1.0 - trailing_stop_pct):
                    curr_pos = 0
                elif price < t:
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
    # VWAP N
    n_min: int = 200
    n_max: int = 2000
    n_step: int = 100

    # 放量倍数
    vol_mult_min: float = 1.5
    vol_mult_max: float = 3.5
    vol_mult_step: float = 0.2

    # 止损比例
    stop_pct_min: float = 0.002
    stop_pct_max: float = 0.012
    stop_pct_step: float = 0.002

    # 其它固定项（默认不遍历，但可通过命令行改）
    twap_window: int = 默认TWAP窗口
    vol_window: int = 默认均量窗口
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

    scale = 1000  # 解决浮点累积误差
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
    print(f"   放量倍数: {cfg.vol_mult_min}..{cfg.vol_mult_max} step={cfg.vol_mult_step}")
    print(f"   止损比例: {cfg.stop_pct_min}..{cfg.stop_pct_max} step={cfg.stop_pct_step}")
    print(f"   TWAP窗口(固定): {cfg.twap_window}")
    print(f"   均量窗口(固定): {cfg.vol_window}")
    print(f"   移动止盈(固定): {cfg.trailing_stop_pct}")

    close = df["close"].to_numpy(dtype=np.float64)
    volume = df["volume"].to_numpy(dtype=np.float64)
    twap = 计算TWAP(df, cfg.twap_window)
    vol_ma = 计算均量(df, cfg.vol_window)

    n_list = _生成整数网格(cfg.n_min, cfg.n_max, cfg.n_step)
    vol_mult_list = _生成浮点网格(cfg.vol_mult_min, cfg.vol_mult_max, cfg.vol_mult_step)
    stop_list = _生成浮点网格(cfg.stop_pct_min, cfg.stop_pct_max, cfg.stop_pct_step)
    total = len(n_list) * len(vol_mult_list) * len(stop_list)
    print(f"   组合数: {total:,}")

    # 预热编译
    if NUMBA可用 and len(close) >= 20:
        _ = _计算夏普_v74_TWAP突破(
            close[:20],
            volume[:20],
            close[:20],
            close[:20],
            close[:20],
            2.0,
            0.005,
            0.0,
            0.0,
            0.0,
            1.0,
            10,
        )

    results: list[tuple[float, int, float, float]] = []
    t0 = time.time()

    for idx, n in enumerate(n_list, start=1):
        vwap = 计算VWAP(df, n=n, 加权方式=vwap_weighting)

        for vol_mult in vol_mult_list:
            for stop_pct in stop_list:
                sharpe = _计算夏普_v74_TWAP突破(
                    close=close,
                    volume=volume,
                    vwap=vwap,
                    twap=twap,
                    vol_ma=vol_ma,
                    vol_multiplier=float(vol_mult),
                    stop_loss_pct=float(stop_pct),
                    trailing_stop_pct=float(cfg.trailing_stop_pct),
                    fee=float(手续费率),
                    slippage=float(滑点),
                    leverage=float(杠杆),
                    periods_per_year=int(每年周期数),
                )
                results.append((float(sharpe), int(n), float(vol_mult), float(stop_pct)))

        spent = time.time() - t0
        avg = spent / idx
        eta = avg * (len(n_list) - idx)
        print(f"   进度: {idx}/{len(n_list)} (n={n}) | 用时 {spent:.1f}s | 预计剩余 {eta:.1f}s")

    out = pd.DataFrame(results, columns=["sharpe", "vwap_n", "vol_multiplier", "stop_loss_pct"])
    out.sort_values(["sharpe"], ascending=False, inplace=True, ignore_index=True)

    print("\n🏁 参数遍历完成：Top 结果（夏普越高越好）")
    print(out.head(cfg.top).to_string(index=False))
    return out


def 单次回测并输出报告(
    df: pd.DataFrame,
    vwap_n: int,
    twap_window: int,
    vol_window: int,
    vol_multiplier: float,
    stop_loss_pct: float,
    trailing_stop_pct: float,
    vwap_weighting: str,
    不画图: bool,
) -> None:
    print(
        f"⚙️  单次回测：{策略版本} | VWAP_N={vwap_n} TWAP={twap_window} "
        f"VOLWIN={vol_window} VOLx={vol_multiplier} STOP={stop_loss_pct} TRAIL={trailing_stop_pct}"
    )

    close = df["close"].to_numpy(dtype=np.float64)
    volume = df["volume"].to_numpy(dtype=np.float64)
    vwap = 计算VWAP(df, n=vwap_n, 加权方式=vwap_weighting)
    twap = 计算TWAP(df, twap_window)
    vol_ma = 计算均量(df, vol_window)

    # 预热编译
    if NUMBA可用 and len(close) >= 20:
        _ = _回测_v74_TWAP突破_生成持仓与收益(
            close[:20],
            volume[:20],
            close[:20],
            close[:20],
            close[:20],
            2.0,
            0.005,
            0.0,
            0.0,
            0.0,
            1.0,
        )

    pos, ret = _回测_v74_TWAP突破_生成持仓与收益(
        close=close,
        volume=volume,
        vwap=vwap,
        twap=twap,
        vol_ma=vol_ma,
        vol_multiplier=float(vol_multiplier),
        stop_loss_pct=float(stop_loss_pct),
        trailing_stop_pct=float(trailing_stop_pct),
        fee=float(手续费率),
        slippage=float(滑点),
        leverage=float(杠杆),
    )

    equity = (1.0 + pd.Series(ret, index=df.index)).cumprod()
    equity_val = equity.values * 初始资金

    策略名称 = (
        f"VWAP {策略版本} (Breakout) VWAP_N={vwap_n} TWAP={twap_window} "
        f"VOLx={vol_multiplier} STOP={stop_loss_pct} TRAIL={trailing_stop_pct} {vwap_weighting}"
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
            保存路径=PROJECT_ROOT / "策略仓库/七号VWAP策略/v7.4_TWAP策略",
        )
        可视化.生成报告(策略名称=策略名称)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--no-chart", action="store_true", help="不显示图表")
    parser.add_argument("--grid-search", action="store_true", help="遍历参数并按夏普排序")

    # 单次回测参数
    parser.add_argument("--vwap-n", type=int, default=默认VWAP_N, help="VWAP 计算周期 N")
    parser.add_argument("--twap-window", type=int, default=默认TWAP窗口, help="TWAP 窗口（分钟数）")
    parser.add_argument("--vol-window", type=int, default=默认均量窗口, help="均量窗口（默认 20）")
    parser.add_argument("--vol-mult", type=float, default=默认放量倍数, help="放量倍数（默认 2）")
    # 注意：argparse 的 help 字符串内部会做 % 格式化，占位符用的也是 %，所以要写成 %% 才能显示出一个 %
    parser.add_argument("--stop-loss-pct", type=float, default=默认止损比例, help="止损比例（默认 0.005=0.5%%）")
    parser.add_argument("--trailing-stop-pct", type=float, default=默认移动止盈比例, help="移动止盈比例（0 关闭）")
    parser.add_argument("--vwap-weighting", type=str, default="EMA", help="VWAP 加权方式：EMA / SMA")

    # 参数遍历范围（默认是“温和范围”，跑得快；你想更细/更广可以再改）
    parser.add_argument("--n-min", type=int, default=参数遍历配置.n_min)
    parser.add_argument("--n-max", type=int, default=参数遍历配置.n_max)
    parser.add_argument("--n-step", type=int, default=参数遍历配置.n_step)
    parser.add_argument("--vol-mult-min", type=float, default=参数遍历配置.vol_mult_min)
    parser.add_argument("--vol-mult-max", type=float, default=参数遍历配置.vol_mult_max)
    parser.add_argument("--vol-mult-step", type=float, default=参数遍历配置.vol_mult_step)
    parser.add_argument("--stop-pct-min", type=float, default=参数遍历配置.stop_pct_min)
    parser.add_argument("--stop-pct-max", type=float, default=参数遍历配置.stop_pct_max)
    parser.add_argument("--stop-pct-step", type=float, default=参数遍历配置.stop_pct_step)
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
            vol_mult_min=float(args.vol_mult_min),
            vol_mult_max=float(args.vol_mult_max),
            vol_mult_step=float(args.vol_mult_step),
            stop_pct_min=float(args.stop_pct_min),
            stop_pct_max=float(args.stop_pct_max),
            stop_pct_step=float(args.stop_pct_step),
            twap_window=int(args.twap_window),
            vol_window=int(args.vol_window),
            trailing_stop_pct=float(args.trailing_stop_pct),
            top=int(args.top),
        )

        out = 遍历参数_按夏普排序(df=df, cfg=cfg, vwap_weighting=str(args.vwap_weighting))

        保存路径 = PROJECT_ROOT / "策略仓库/七号VWAP策略/v7.4_TWAP策略" / "v7.4_TWAP突破_参数遍历结果.csv"
        out.to_csv(保存路径, index=False)
        print(f"\n💾 已保存参数遍历结果：{保存路径}")
        return

    单次回测并输出报告(
        df=df,
        vwap_n=int(args.vwap_n),
        twap_window=int(args.twap_window),
        vol_window=int(args.vol_window),
        vol_multiplier=float(args.vol_mult),
        stop_loss_pct=float(args.stop_loss_pct),
        trailing_stop_pct=float(args.trailing_stop_pct),
        vwap_weighting=str(args.vwap_weighting),
        不画图=bool(args.no_chart),
    )


if __name__ == "__main__":
    main()
