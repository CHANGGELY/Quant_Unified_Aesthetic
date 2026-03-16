# -*- coding: utf-8 -*-
"""
十号隐马尔可夫策略 - 高斯隐马尔可夫模型（Gaussian HMM）

你在需求里提到：
    “HMM 的其他参数通过 鲍姆-威尔奇算法 推断”

鲍姆-威尔奇算法（Baum–Welch）本质上就是 EM（Expectation-Maximization）：
    - E 步：用前向-后向算法算出“每个时刻属于每个状态的概率”（后验）
    - M 步：用这些概率去更新：
        - 初始分布 π
        - 转移矩阵 A
        - 每个状态的高斯分布参数（均值 μ、方差 σ²）

这里实现的是“对角协方差”的高斯 HMM：
    - 每个特征维度独立（方差是一个向量）
    - 好处：训练更稳定、计算更快
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class 高斯HMM参数:
    初始分布: np.ndarray   # shape=(N,)
    转移矩阵: np.ndarray   # shape=(N,N)
    均值: np.ndarray       # shape=(N,D)
    方差: np.ndarray       # shape=(N,D)  对角协方差


def _行归一化(a: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    s = a.sum(axis=1, keepdims=True)
    s = np.where(s < eps, 1.0, s)
    return a / s


class 高斯隐马尔可夫模型:
    def __init__(self, *, 隐状态数: int, 方差下限: float = 1e-6, 随机种子: int = 42) -> None:
        if 隐状态数 <= 1:
            raise ValueError("隐状态数 必须 >= 2")
        self.N = int(隐状态数)
        self.var_floor = float(方差下限)
        self.rng = np.random.default_rng(int(随机种子))
        self.参数: 高斯HMM参数 | None = None

    def _初始化参数(self, X: np.ndarray) -> 高斯HMM参数:
        X = np.asarray(X, dtype=np.float64)
        n, d = X.shape

        # 初始分布：先均匀
        pi = np.full(self.N, 1.0 / self.N, dtype=np.float64)

        # 转移矩阵：先偏向“保持原状态”
        A = np.full((self.N, self.N), 1.0 / self.N, dtype=np.float64)
        np.fill_diagonal(A, 0.90)
        A = _行归一化(A)

        # 均值/方差：从数据里随机挑 N 个点当初始中心
        idx = self.rng.choice(n, size=self.N, replace=False) if n >= self.N else np.arange(n)
        mu = X[idx].astype(np.float64, copy=True)
        var = np.var(X, axis=0, keepdims=True)
        var = np.repeat(var, self.N, axis=0)
        var = np.maximum(var, self.var_floor)
        return 高斯HMM参数(初始分布=pi, 转移矩阵=A, 均值=mu, 方差=var)

    @staticmethod
    def _计算发射对数概率(X: np.ndarray, mu: np.ndarray, var: np.ndarray) -> np.ndarray:
        """
        返回 log p(x_t | state=i) 的矩阵，shape=(T, N)
        """
        X = np.asarray(X, dtype=np.float64)
        mu = np.asarray(mu, dtype=np.float64)
        var = np.asarray(var, dtype=np.float64)

        T, D = X.shape
        N = mu.shape[0]

        # diff: (T,N,D)
        diff = X[:, None, :] - mu[None, :, :]
        inv_var = 1.0 / var[None, :, :]
        quad = np.sum((diff * diff) * inv_var, axis=2)  # (T,N)
        log_det = np.sum(np.log(2.0 * np.pi * var), axis=1)  # (N,)
        return -0.5 * (quad + log_det[None, :])

    def _发射概率矩阵(self, X: np.ndarray, mu: np.ndarray, var: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        返回：
            B: shape=(T,N)  （做了数值稳定缩放）
            m: shape=(T,)   每个时刻减掉的最大 log_prob（用于还原 loglik）
        """
        logp = self._计算发射对数概率(X, mu, var)  # (T,N)
        m = np.max(logp, axis=1)  # (T,)
        B = np.exp(logp - m[:, None])  # (T,N)
        B = np.maximum(B, 1e-300)  # 防止出现0
        return B, m

    def _前向(self, X: np.ndarray, params: 高斯HMM参数) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        前向算法（带缩放），返回：
            alpha: (T,N)  每个时刻的过滤概率（归一化后）
            scale: (T,)   缩放因子
            m: (T,)       发射概率的 log 缩放（见 _发射概率矩阵）
        """
        B, m = self._发射概率矩阵(X, params.均值, params.方差)
        T = B.shape[0]
        N = self.N

        alpha = np.zeros((T, N), dtype=np.float64)
        scale = np.zeros(T, dtype=np.float64)

        alpha[0] = params.初始分布 * B[0]
        scale[0] = alpha[0].sum()
        if scale[0] <= 0:
            scale[0] = 1e-300
        alpha[0] /= scale[0]

        A = params.转移矩阵
        for t in range(1, T):
            alpha[t] = (alpha[t - 1] @ A) * B[t]
            scale[t] = alpha[t].sum()
            if scale[t] <= 0:
                scale[t] = 1e-300
            alpha[t] /= scale[t]

        return alpha, scale, m

    def _后向(self, B: np.ndarray, scale: np.ndarray, A: np.ndarray) -> np.ndarray:
        T, N = B.shape
        beta = np.zeros((T, N), dtype=np.float64)
        beta[-1] = 1.0
        for t in range(T - 2, -1, -1):
            beta[t] = (A * (B[t + 1] * beta[t + 1])[None, :]).sum(axis=1)
            beta[t] /= scale[t + 1]
        return beta

    def fit(
        self,
        X: np.ndarray,
        lengths: Iterable[int],
        *,
        最大迭代次数: int = 30,
        收敛阈值: float = 1e-4,
        verbose: bool = True,
    ) -> 高斯HMM参数:
        X = np.asarray(X, dtype=np.float64)
        lengths = [int(x) for x in lengths]
        if X.ndim != 2:
            raise ValueError("X 必须是二维矩阵 (T,D)")
        if any(l <= 1 for l in lengths):
            raise ValueError("lengths 中每段长度必须 >= 2")
        if sum(lengths) != len(X):
            raise ValueError("lengths 之和必须等于 X 的行数")

        params = self._初始化参数(X)
        prev_ll = -np.inf

        for it in range(1, int(最大迭代次数) + 1):
            pi_num = np.zeros(self.N, dtype=np.float64)
            A_num = np.zeros((self.N, self.N), dtype=np.float64)
            A_den = np.zeros(self.N, dtype=np.float64)
            sum_gamma = np.zeros(self.N, dtype=np.float64)
            sum_x = np.zeros((self.N, X.shape[1]), dtype=np.float64)
            sum_x2 = np.zeros((self.N, X.shape[1]), dtype=np.float64)

            ll = 0.0
            start = 0
            for L in lengths:
                end = start + L
                Xi = X[start:end]

                alpha, scale, m = self._前向(Xi, params)
                B, _m2 = self._发射概率矩阵(Xi, params.均值, params.方差)
                beta = self._后向(B, scale, params.转移矩阵)

                gamma = alpha * beta
                gamma_sum_t = gamma.sum(axis=1, keepdims=True)
                gamma_sum_t = np.where(gamma_sum_t <= 0, 1e-300, gamma_sum_t)
                gamma = gamma / gamma_sum_t

                pi_num += gamma[0]
                sum_gamma += gamma.sum(axis=0)
                sum_x += gamma.T @ Xi
                sum_x2 += gamma.T @ (Xi * Xi)
                A_den += gamma[:-1].sum(axis=0)

                # xi 累加
                A = params.转移矩阵
                for t in range(L - 1):
                    tmp = (alpha[t][:, None] * A) * (B[t + 1][None, :] * beta[t + 1][None, :])
                    denom = tmp.sum()
                    if denom <= 0:
                        continue
                    A_num += tmp / denom

                # 还原 log-likelihood：log(scale_t) + m_t
                ll += float(np.sum(np.log(scale) + m))
                start = end

            # M-step
            pi = pi_num / max(pi_num.sum(), 1e-12)
            A = A_num.copy()
            # 分母按行广播
            denom = A_den[:, None]
            denom = np.where(denom <= 0, 1.0, denom)
            A = A / denom
            A = _行归一化(np.maximum(A, 1e-12))

            mu = sum_x / np.maximum(sum_gamma[:, None], 1e-12)
            var = sum_x2 / np.maximum(sum_gamma[:, None], 1e-12) - mu * mu
            var = np.maximum(var, self.var_floor)

            params = 高斯HMM参数(初始分布=pi, 转移矩阵=A, 均值=mu, 方差=var)

            if verbose:
                print(f"[HMM] iter={it:02d} loglik={ll:.2f} delta={ll - prev_ll:.4f}")

            if np.isfinite(prev_ll) and (ll - prev_ll) < float(收敛阈值) * max(1.0, abs(prev_ll)):
                if verbose:
                    print(f"[HMM] ✅ 收敛：iter={it}, delta={ll - prev_ll:.6f}")
                break
            prev_ll = ll

        self.参数 = params
        return params

    def 过滤当前状态分布(self, X: np.ndarray) -> np.ndarray:
        if self.参数 is None:
            raise RuntimeError("模型未训练")
        X = np.asarray(X, dtype=np.float64)
        alpha, _scale, _m = self._前向(X, self.参数)
        return alpha[-1].copy()

    def 预测未来状态分布(self, X: np.ndarray, *, 未来步数: int) -> np.ndarray:
        if self.参数 is None:
            raise RuntimeError("模型未训练")
        if 未来步数 < 0:
            raise ValueError("未来步数 必须 >= 0")

        p_now = self.过滤当前状态分布(X)
        A_k = np.linalg.matrix_power(self.参数.转移矩阵, int(未来步数))
        return p_now @ A_k

