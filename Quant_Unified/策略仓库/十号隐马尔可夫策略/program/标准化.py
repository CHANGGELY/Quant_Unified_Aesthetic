# -*- coding: utf-8 -*-
"""
十号隐马尔可夫策略 - 简单标准化器

为什么需要标准化？
    同一份特征里，不同维度的数值尺度可能差很多：
    - 收益率可能在 0.001 附近
    - log 成交量变化可能在 0.1~1 之间

标准化（z-score）的作用就像“统一单位”：
    让每个维度都大概是：
        均值=0，标准差=1
    避免模型被某个数值更大的维度“抢戏”。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class 标准化器:
    均值: np.ndarray
    标准差: np.ndarray

    @classmethod
    def 拟合(cls, X: np.ndarray, eps: float = 1e-12) -> "标准化器":
        X = np.asarray(X, dtype=np.float64)
        mean = X.mean(axis=0)
        std = X.std(axis=0)
        std = np.where(std < eps, 1.0, std)
        return cls(均值=mean, 标准差=std)

    def 变换(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=np.float64)
        return (X - self.均值) / self.标准差

