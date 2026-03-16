# -*- coding: utf-8 -*-
"""
十号隐马尔可夫策略 - 推断（输出未来 8 小时上涨/震荡/下跌概率）

推断流程（用人话）：
    1) 读取某个币的小时K线
    2) 做特征工程 -> 得到特征矩阵 X
    3) 用标准化器把 X 统一尺度
    4) 用 HMM 的“前向算法”估计当前状态分布（对最后一根K线来说，后验=过滤值，不会用到未来信息）
    5) 用转移矩阵 A 推 8 步（8 小时）得到未来状态分布
    6) 把状态分布映射成：上涨/震荡/下跌 三个概率
"""

from __future__ import annotations

from dataclasses import dataclass

import math
import numpy as np
import pandas as pd

from .模型产物 import 十号HMM训练产物
from .特征工程 import 计算HMM特征


@dataclass(frozen=True)
class 单币预测结果:
    symbol: str
    截止时间: pd.Timestamp
    最新价格: float
    上涨概率: float
    震荡概率: float
    下跌概率: float


def _取最新一根有效K线(df: pd.DataFrame, 截止时间: pd.Timestamp) -> pd.DataFrame:
    df = df[df["candle_begin_time"] <= 截止时间].copy()
    if df.empty:
        return df
    return df


def 推断单币(
    *,
    df: pd.DataFrame,
    产物: 十号HMM训练产物,
    截止时间: pd.Timestamp,
    推断回看小时数: int,
    预测步长小时: int,
    震荡阈值_8小时对数收益: float = 0.0,
) -> 单币预测结果 | None:
    if df is None or df.empty:
        return None

    df = _取最新一根有效K线(df, 截止时间)
    if df.empty:
        return None

    # 只取最近 N 小时作为输入窗口
    if 推断回看小时数 > 0 and len(df) > 推断回看小时数:
        df = df.tail(int(推断回看小时数)).copy()

    feat = 计算HMM特征(df)
    X = 产物.标准化器.transform(feat.特征矩阵)

    # 当前状态分布：取“窗口最后一根K线”的状态后验
    # 重要点：
    #   HMM 的后验一般会用到“未来信息”（前向-后向算法）。
    #   但我们只取最后一个时刻 t=T 的后验：
    #       beta[T] = 1（没有未来）
    #   所以 posterior[T] 等价于过滤值 alpha[T]（不会泄露未来）。
    post = np.asarray(产物.模型.predict_proba(X), dtype=np.float64)
    if post.size == 0:
        return None
    p_now = post[-1]

    # =========================
    # 把“未来8小时市场状态概率”定义成：未来8小时累计收益落在哪个区间
    #
    # 上涨：R_8h > +theta
    # 下跌：R_8h < -theta
    # 震荡：|R_8h| <= theta
    #
    # 其中 R_8h 用“对数收益”的累加近似（更稳定）：
    #   R_8h ≈ sum_{u=1..8} log_ret_1h(t+u)
    #
    # 我们用 HMM 的转移矩阵 A 预测未来每小时的状态分布，再用“混合高斯”的二阶矩估计均值/方差，
    # 最后把累计收益近似为正态分布 N(μ, σ²) 来算概率。
    # =========================
    scaler = 产物.标准化器
    scale0 = float(scaler.scale_[0])
    mean0 = float(scaler.mean_[0])

    mu_z = np.asarray(产物.模型.means_, dtype=np.float64)[:, 0]
    var_z = np.asarray(产物.模型.covars_, dtype=np.float64)[:, 0, 0]

    # 标准化空间 -> 原始空间（对数收益）
    mu_ret = mu_z * scale0 + mean0
    var_ret = var_z * (scale0 * scale0)
    second_moment = var_ret + mu_ret * mu_ret

    A = np.asarray(产物.模型.transmat_, dtype=np.float64)
    H = int(预测步长小时)
    theta = float(震荡阈值_8小时对数收益)

    mu_sum = 0.0
    var_sum = 0.0
    p = np.asarray(p_now, dtype=np.float64)
    for _ in range(H):
        p = p @ A
        mu_u = float(p @ mu_ret)
        second_u = float(p @ second_moment)
        var_u = max(0.0, second_u - mu_u * mu_u)
        mu_sum += mu_u
        var_sum += var_u

    sigma = math.sqrt(max(var_sum, 0.0))
    if sigma <= 1e-12:
        p_up = 1.0 if mu_sum > theta else 0.0
        p_down = 1.0 if mu_sum < -theta else 0.0
        p_range = max(0.0, 1.0 - p_up - p_down)
    else:
        # 标准正态 CDF：Φ(x)
        def _phi(x: float) -> float:
            return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

        z_up = (theta - mu_sum) / sigma
        z_down = (-theta - mu_sum) / sigma
        p_up = 1.0 - _phi(z_up)
        p_down = _phi(z_down)
        p_range = max(0.0, 1.0 - p_up - p_down)

    latest_row = df.iloc[-1]
    return 单币预测结果(
        symbol=str(latest_row.get("symbol") or ""),
        截止时间=pd.to_datetime(latest_row["candle_begin_time"]),
        最新价格=float(latest_row["close"]),
        上涨概率=float(p_up),
        震荡概率=float(p_range),
        下跌概率=float(p_down),
    )
