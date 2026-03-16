# -*- coding: utf-8 -*-
"""
十号隐马尔可夫策略 - 回测入口（中性选币：多空对冲）

你要的“最基本的策略三件套”是什么？
1) 训练：用历史数据把模型学出来（train.py）
2) 推断/选币：每期输出要做多/做空的币（select_coins.py）
3) 回测：把“选币结果”变成资金曲线，再出报告（本文件）

本回测的核心口径（用人话）：
    - 每 8 小时做一次“横截面选币”
    - 多头：上涨概率 Top 10%
    - 空头：下跌概率 Top 10%
    - 资金分配：多头 50% + 空头 50%（中性：不赌大盘方向）
    - 收益计算：持有 8 小时后平仓，计算收益，扣除手续费/滑点

注意：
    - 这是“研究版回测”，先把流程跑顺、口径一致、结果可复现。
    - 后续你要上实盘，还得补：资金费率、维持保证金、滑点模型、更真实的换仓撮合等。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import ndtr  # type: ignore

# ====== 自动把 Quant_Unified 加入 sys.path（保证能 import 到“基础库/策略仓库”） ======
CURRENT_FILE = Path(__file__).resolve()
QUANT_UNIFIED_ROOT = CURRENT_FILE.parents[2]
if str(QUANT_UNIFIED_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_UNIFIED_ROOT))

from 基础库.common_core.backtest.metrics import 回测指标计算器
from 基础库.common_core.backtest.可视化 import 回测可视化

from 策略仓库.十号隐马尔可夫策略.config import Config
from 策略仓库.十号隐马尔可夫策略.program.数据读取 import 列出zip内csv文件, 读取单币小时K线
from 策略仓库.十号隐马尔可夫策略.program.特征工程 import 计算HMM特征
from 策略仓库.十号隐马尔可夫策略.program.模型产物 import 加载产物


def _清洗并补全小时序列(df: pd.DataFrame) -> pd.DataFrame:
    """
    把单币 1h K 线补齐成“连续的小时序列”。

    用人话：
        有些币会出现：
            - 某些小时缺K线
            - 刚上线/下线导致时间不连续
        我们把时间补齐后：
            - close 用前值填充（保持价格连续）
            - volume/quote_volume 缺失填 0（表示那小时不可交易）
    """
    if df is None or df.empty:
        return df

    df = df.copy()
    df["candle_begin_time"] = pd.to_datetime(df["candle_begin_time"])
    df.drop_duplicates(subset=["candle_begin_time"], inplace=True, keep="last")
    df.sort_values("candle_begin_time", inplace=True)

    first = df["candle_begin_time"].min()
    last = df["candle_begin_time"].max()
    hourly = pd.DataFrame(pd.date_range(start=first, end=last, freq="1h"), columns=["candle_begin_time"])
    df = hourly.merge(df, on="candle_begin_time", how="left", sort=True)

    df["close"] = df["close"].ffill()
    df["open"] = df["open"].fillna(df["close"])
    df["high"] = df["high"].fillna(df["close"])
    df["low"] = df["low"].fillna(df["close"])
    df["volume"] = df["volume"].fillna(0.0)
    df["quote_volume"] = df["quote_volume"].fillna(0.0)
    df["symbol"] = df["symbol"].ffill()
    return df


def _logpdf_full(X: np.ndarray, mean: np.ndarray, cov: np.ndarray, var_floor: float) -> np.ndarray:
    """
    计算多元高斯 logpdf（full 协方差）

    数值稳定性要点：
        - cov 可能接近奇异矩阵（不好求逆）
        - 所以我们给协方差对角线加一个 very small 的“地板”（var_floor）
        - 再用 Cholesky 分解（比直接求逆更稳）
    """
    X = np.asarray(X, dtype=np.float64)
    mean = np.asarray(mean, dtype=np.float64)
    cov = np.asarray(cov, dtype=np.float64)

    d = int(X.shape[1])
    cov = cov + np.eye(d, dtype=np.float64) * float(max(var_floor, 0.0))

    # Cholesky: cov = L L^T
    try:
        L = np.linalg.cholesky(cov)
    except np.linalg.LinAlgError:
        # 兜底：再加一层更强的对角线正则
        cov = cov + np.eye(d, dtype=np.float64) * 1e-3
        L = np.linalg.cholesky(cov)

    diff = X - mean  # (T,D)
    # 解 L * y = diff^T
    y = np.linalg.solve(L, diff.T)  # (D,T)
    quad = np.sum(y * y, axis=0)  # (T,)
    log_det = 2.0 * float(np.sum(np.log(np.diag(L))))
    return -0.5 * (quad + float(d) * np.log(2.0 * np.pi) + log_det)


def _计算发射对数概率矩阵(X: np.ndarray, means: np.ndarray, covars: np.ndarray, var_floor: float) -> np.ndarray:
    """
    返回 log p(x_t | state=i) 的矩阵，shape=(T, N)
    """
    X = np.asarray(X, dtype=np.float64)
    means = np.asarray(means, dtype=np.float64)
    covars = np.asarray(covars, dtype=np.float64)

    T = int(X.shape[0])
    N = int(means.shape[0])
    out = np.empty((T, N), dtype=np.float64)
    for i in range(N):
        out[:, i] = _logpdf_full(X, means[i], covars[i], var_floor=float(var_floor))
    return out


def _过滤状态分布序列(
    *,
    logp: np.ndarray,
    startprob: np.ndarray,
    transmat: np.ndarray,
) -> np.ndarray:
    """
    只做“前向过滤”（只用到过去，不用未来）。

    返回：
        alpha: shape=(T,N) ，每个时刻的状态分布
    """
    logp = np.asarray(logp, dtype=np.float64)
    startprob = np.asarray(startprob, dtype=np.float64)
    transmat = np.asarray(transmat, dtype=np.float64)

    T, N = logp.shape
    m = np.max(logp, axis=1, keepdims=True)
    B = np.exp(logp - m)  # (T,N)；做了平移，避免 exp 下溢
    B = np.maximum(B, 1e-300)

    alpha = np.zeros((T, N), dtype=np.float64)
    alpha[0] = startprob * B[0]
    s0 = alpha[0].sum()
    if s0 <= 0:
        s0 = 1e-300
    alpha[0] /= s0

    for t in range(1, T):
        alpha[t] = (alpha[t - 1] @ transmat) * B[t]
        st = alpha[t].sum()
        if st <= 0:
            st = 1e-300
        alpha[t] /= st

    return alpha


def _构造回测时间轴(cfg: Config, 文件列表: list[str]) -> tuple[pd.Timestamp, pd.Timestamp, pd.DatetimeIndex]:
    """
    生成：
        - 回测开始时间
        - 回测结束时间（如果配置没填，就用数据的“共同截止时间”估计）
        - 再平衡时间序列（每 8 小时）
    """
    start = pd.Timestamp(cfg.回测开始时间).floor("h")
    hold_h = int(cfg.预测步长小时)
    rebalance_h = int(cfg.回测再平衡小时)

    if cfg.回测结束时间:
        end = pd.Timestamp(cfg.回测结束时间).floor("h")
    else:
        # 用“分位数共同截止时间”，避免少数币数据特别短把 end 拉到很早
        sample_n = max(1, min(len(文件列表), int(cfg.截止时间抽样币种数 or 80)))
        last_times = []
        for fname in 文件列表[:sample_n]:
            df = 读取单币小时K线(zip路径=cfg.数据zip路径, 文件名=fname)
            df = _清洗并补全小时序列(df)
            last_times.append(pd.to_datetime(df["candle_begin_time"].iloc[-1]))

        q = min(max(float(cfg.截止时间分位数), 0.0), 1.0)
        ns = np.array([t.value for t in last_times], dtype=np.int64)
        end = pd.Timestamp(int(np.quantile(ns, q))).floor("h")

    # 需要确保 end 至少还能往后看 8 小时（否则最后一根没法计算收益）
    latest_entry = end - pd.Timedelta(hours=hold_h)
    times = pd.date_range(start=start, end=latest_entry, freq=f"{rebalance_h}h", inclusive="both")
    if len(times) <= 0:
        raise ValueError(f"回测时间轴为空：start={start}, end={end}, hold={hold_h}h")
    return start, end, times


def _选币并计算单期收益(
    *,
    t: pd.Timestamp,
    up_prob: pd.Series,
    down_prob: pd.Series,
    ret_h: pd.Series,
    long_ratio: float,
    short_ratio: float,
    fee_rate: float,
    slippage_rate: float,
    prev_long: set[str],
    prev_short: set[str],
) -> tuple[float, set[str], set[str]]:
    """
    返回：
        - 本期组合收益率（已扣成本）
        - 本期多头集合
        - 本期空头集合
    """
    # 过滤缺失
    df = pd.DataFrame({"up": up_prob, "down": down_prob, "ret": ret_h}).dropna()
    if df.empty:
        return 0.0, set(), set()

    n_universe = len(df)
    long_n = max(1, int(np.ceil(n_universe * float(long_ratio))))
    short_n = max(1, int(np.ceil(n_universe * float(short_ratio))))

    long_list = df.sort_values("up", ascending=False).head(long_n).index.tolist()
    short_list = df.sort_values("down", ascending=False).head(short_n).index.tolist()

    long_set = set(map(str, long_list))
    short_set = set(map(str, short_list))

    # 避免同一币同时多空（会互相抵消 + 浪费手续费）
    overlap = long_set & short_set
    if overlap:
        short_set -= overlap
        # 不够则向后补齐
        if len(short_set) < short_n:
            extra = [s for s in df.sort_values("down", ascending=False).index.tolist() if str(s) not in long_set]
            for s in extra:
                short_set.add(str(s))
                if len(short_set) >= short_n:
                    break

    if not long_set or not short_set:
        return 0.0, long_set, short_set

    long_ret = float(df.loc[list(long_set), "ret"].mean())
    short_ret = float(df.loc[list(short_set), "ret"].mean())

    # 中性组合：多头 50% + 空头 50%
    gross_ret = 0.5 * long_ret - 0.5 * short_ret

    # 成本：用“换仓比例”近似（越频繁换，手续费越高）
    # turnover=1 表示全换仓（开平全来一遍），turnover=0 表示完全不换仓
    turnover_long = 1.0
    if prev_long:
        turnover_long = 1.0 - (len(prev_long & long_set) / max(1, len(prev_long)))
    turnover_short = 1.0
    if prev_short:
        turnover_short = 1.0 - (len(prev_short & short_set) / max(1, len(prev_short)))

    # 每次换仓我们近似认为会发生“开仓+平仓”各一次，所以成本 ~ 2 * fee
    cost = 0.5 * (2.0 * fee_rate * turnover_long + 2.0 * fee_rate * turnover_short)
    cost += 0.5 * (2.0 * slippage_rate * turnover_long + 2.0 * slippage_rate * turnover_short)

    return gross_ret - cost, long_set, short_set


def main(显示图表: bool = True) -> None:
    cfg = Config()
    模型路径 = cfg.模型目录 / "hmm10_gaussian.pkl"
    if not 模型路径.exists():
        raise FileNotFoundError(f"未找到模型文件: {模型路径}，请先运行 train.py")

    art = 加载产物(模型路径)
    print("🧪 十号隐马尔可夫策略 - 开始回测")
    print(f"📦 数据zip: {cfg.数据zip路径}")
    print(f"📦 模型文件: {模型路径}")

    文件列表 = 列出zip内csv文件(cfg.数据zip路径)
    文件列表 = [n for n in 文件列表 if n.endswith("-USDT.csv")]
    文件列表.sort()

    if cfg.回测币种上限 and int(cfg.回测币种上限) > 0:
        文件列表 = 文件列表[: int(cfg.回测币种上限)]
    print(f"✅ 回测币种数（上限后）: {len(文件列表)}")

    start, end, rebalance_times = _构造回测时间轴(cfg, 文件列表)
    warmup_start = start - pd.Timedelta(hours=int(cfg.回测预热小时))
    hold_h = int(cfg.预测步长小时)

    print(f"🕒 回测区间: {start} ~ {end} | 再平衡次数: {len(rebalance_times):,} | 持仓: {hold_h}h")

    # 预先准备一些模型参数（加速）
    means = np.asarray(art.模型.means_, dtype=np.float64)
    covars = np.asarray(art.模型.covars_, dtype=np.float64)
    transmat = np.asarray(art.模型.transmat_, dtype=np.float64)
    startprob = np.asarray(art.模型.startprob_, dtype=np.float64)

    # 把“收益率维度(特征0：log_ret_1h)”从标准化空间还原回真实空间
    scaler = art.标准化器
    scale0 = float(scaler.scale_[0])
    mean0 = float(scaler.mean_[0])
    mu_ret = means[:, 0] * scale0 + mean0
    var_ret = covars[:, 0, 0] * (scale0 * scale0)
    second_moment = var_ret + mu_ret * mu_ret

    # 预计算 A^1..A^H
    A_pows: list[np.ndarray] = []
    cur = transmat.copy()
    for _ in range(hold_h):
        A_pows.append(cur.copy())
        cur = cur @ transmat

    # 每个币：在每个 rebalance_time 上的预测与未来收益
    up_prob_map: dict[str, np.ndarray] = {}
    down_prob_map: dict[str, np.ndarray] = {}
    ret_map: dict[str, np.ndarray] = {}

    for i, fname in enumerate(文件列表, 1):
        symbol = Path(fname).stem
        if i % 50 == 0 or i == 1 or i == len(文件列表):
            print(f"⏳ 处理进度: {i}/{len(文件列表)} | {symbol}")

        df = 读取单币小时K线(zip路径=cfg.数据zip路径, 文件名=fname)
        df = _清洗并补全小时序列(df)

        # 裁剪到“预热开始~回测结束+持仓”
        df = df[(df["candle_begin_time"] >= warmup_start) & (df["candle_begin_time"] <= end)].copy()
        if len(df) < (hold_h + 50):
            continue

        # 特征 -> 标准化
        feat = 计算HMM特征(df)
        Xz = art.标准化器.transform(feat.特征矩阵)

        # 发射概率 + 前向过滤
        logp = _计算发射对数概率矩阵(Xz, means, covars, var_floor=float(cfg.方差下限))
        alpha = _过滤状态分布序列(logp=logp, startprob=startprob, transmat=transmat)

        # =========================
        # 用 HMM 预测“未来 8 小时累计对数收益”的分布，然后转成：
        #   上涨概率 / 下跌概率 / 震荡概率
        #
        # 关键点：
        #   我们不是只看“第8小时那一刻是什么状态”，而是把未来 8 小时每一小时的状态分布都考虑进去，
        #   得到累计收益的均值/方差，再用正态近似计算概率。
        # =========================
        mu_sum = np.zeros(alpha.shape[0], dtype=np.float64)
        var_sum = np.zeros(alpha.shape[0], dtype=np.float64)
        for Ak in A_pows:
            p_u = alpha @ Ak  # (T,N)
            mean_u = p_u @ mu_ret  # (T,)
            second_u = p_u @ second_moment  # (T,)
            var_u = second_u - mean_u * mean_u
            mu_sum += mean_u
            var_sum += np.maximum(var_u, 0.0)

        sigma = np.sqrt(np.maximum(var_sum, 0.0))
        sigma_safe = np.where(sigma < 1e-12, 1e-12, sigma)
        theta = float(cfg.震荡阈值_8小时对数收益)

        up_series = 1.0 - ndtr((theta - mu_sum) / sigma_safe)
        down_series = ndtr((-theta - mu_sum) / sigma_safe)

        # 未来 8h 实现收益：close[t+8]/close[t]-1
        close = df["close"].to_numpy(dtype=np.float64)
        vol = df["volume"].to_numpy(dtype=np.float64)
        ret8 = np.full(len(close), np.nan, dtype=np.float64)
        if len(close) > hold_h:
            ret8[:-hold_h] = close[hold_h:] / np.maximum(close[:-hold_h], 1e-12) - 1.0

        # 不交易：当前或未来那根 volume=0
        tradable = (vol > 0).astype(bool)
        tradable_future = np.zeros_like(tradable)
        tradable_future[:-hold_h] = (vol[hold_h:] > 0)
        tradable = tradable & tradable_future

        # 对齐到 rebalance_times（可能某些币刚上线，前面没有数据）
        idx = pd.Index(df["candle_begin_time"]).get_indexer(rebalance_times)
        valid = idx >= 0
        out_up = np.full(len(rebalance_times), np.nan, dtype=np.float64)
        out_down = np.full(len(rebalance_times), np.nan, dtype=np.float64)
        out_ret = np.full(len(rebalance_times), np.nan, dtype=np.float64)

        for j, pos in enumerate(idx):
            if not valid[j]:
                continue
            if not tradable[pos]:
                continue
            if not np.isfinite(ret8[pos]):
                continue
            out_up[j] = float(up_series[pos])
            out_down[j] = float(down_series[pos])
            out_ret[j] = float(ret8[pos])

        if np.isfinite(out_up).sum() <= 0:
            continue

        up_prob_map[symbol] = out_up
        down_prob_map[symbol] = out_down
        ret_map[symbol] = out_ret

    if not up_prob_map:
        raise RuntimeError("没有可用币种进入回测（可能回测区间太早/币种上限太小/数据缺失）")

    up_df = pd.DataFrame(up_prob_map, index=rebalance_times).sort_index(axis=1)
    down_df = pd.DataFrame(down_prob_map, index=rebalance_times).sort_index(axis=1)
    ret_df = pd.DataFrame(ret_map, index=rebalance_times).sort_index(axis=1)

    print(f"✅ 可用币种数: {up_df.shape[1]}")

    # ====== 逐期回测（生成资金曲线） ======
    equity_times = [rebalance_times[0]]
    equity_values = [float(cfg.回测初始资金)]
    prev_long: set[str] = set()
    prev_short: set[str] = set()

    for t in rebalance_times:
        up = up_df.loc[t]
        down = down_df.loc[t]
        ret8 = ret_df.loc[t]

        r, long_set, short_set = _选币并计算单期收益(
            t=t,
            up_prob=up,
            down_prob=down,
            ret_h=ret8,
            long_ratio=float(cfg.多头选币比例),
            short_ratio=float(cfg.空头选币比例),
            fee_rate=float(cfg.回测手续费率),
            slippage_rate=float(cfg.回测滑点率),
            prev_long=prev_long,
            prev_short=prev_short,
        )

        prev_long = long_set
        prev_short = short_set

        # 本期收益落在 t+8h（持仓结束时刻）
        next_time = pd.Timestamp(t) + pd.Timedelta(hours=hold_h)
        equity_times.append(next_time)
        equity_values.append(equity_values[-1] * (1.0 + float(r)))

    equity = np.asarray(equity_values, dtype=np.float64)
    ts = np.asarray(equity_times, dtype="datetime64[ns]")

    # ====== 指标 + 报告 ======
    计算器 = 回测指标计算器(
        权益曲线=equity,
        初始资金=float(cfg.回测初始资金),
        时间戳=ts,
        周期每年数量=365 * (24 // max(1, int(cfg.回测再平衡小时))),  # 8小时一次 -> 1095
    )
    计算器.打印报告(策略名称="十号隐马尔可夫策略（HMM，全协方差）")

    # ====== 图表（带参数区块） ======
    报告参数 = {
        "data_zip": str(cfg.数据zip路径),
        "train_max_symbols": cfg.最大训练币种数,
        "train_max_bars_per_symbol": cfg.每币最多使用K线数,
        "hmm_n_states": cfg.隐状态数,
        "hmm_covariance": "full",
        "hmm_iter": cfg.最大迭代次数,
        "hmm_tol": cfg.收敛阈值,
        "hmm_var_floor": cfg.方差下限,
        "state_to_label": art.状态到标签,
        "ret_mean_logret_1h_per_state": mu_ret.tolist(),
        "ret_var_logret_1h_per_state": var_ret.tolist(),
        "lookback_hours": cfg.推断回看小时数,
        "horizon_hours": cfg.预测步长小时,
        "range_theta_logret_8h": cfg.震荡阈值_8小时对数收益,
        "bt_start": str(start),
        "bt_end": str(end),
        "bt_rebalance_hours": cfg.回测再平衡小时,
        "bt_warmup_hours": cfg.回测预热小时,
        "bt_fee_rate": cfg.回测手续费率,
        "bt_slippage_rate": cfg.回测滑点率,
        "bt_universe_symbols": int(up_df.shape[1]),
        "long_ratio": cfg.多头选币比例,
        "short_ratio": cfg.空头选币比例,
    }

    可视化器 = 回测可视化(
        权益曲线=equity,
        时间序列=ts,
        初始资金=float(cfg.回测初始资金),
        价格序列=None,
        显示图表=显示图表,
        保存路径=Path(__file__).resolve().parent,
        报告参数=报告参数,
    )
    可视化器.生成报告(策略名称="十号隐马尔可夫策略（HMM，全协方差）", 显示价格=False)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="十号隐马尔可夫策略回测")
    parser.add_argument("--no-chart", action="store_true", help="不自动打开浏览器（仍会保存 HTML）")
    args = parser.parse_args()

    main(显示图表=not args.no_chart)
