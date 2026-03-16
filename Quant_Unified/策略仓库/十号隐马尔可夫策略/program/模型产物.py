# -*- coding: utf-8 -*-
"""
十号隐马尔可夫策略 - 训练产物（模型文件保存/加载）

说明：
    训练会输出一份“产物”，里面包含：
        - 特征标准化器（把特征统一到均值0/方差1）
        - HMM 模型（hmmlearn.GaussianHMM，支持 full 协方差）
        - 状态 -> 标签（上涨/震荡/下跌）的映射
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler


状态标签 = Literal["下跌", "震荡", "上涨"]


@dataclass(frozen=True)
class 十号HMM训练产物:
    特征名: list[str]
    标准化器: StandardScaler
    模型: GaussianHMM
    状态到标签: dict[int, 状态标签]


def 保存产物(产物: 十号HMM训练产物, 路径: Path) -> None:
    import joblib

    路径 = Path(路径)
    路径.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(产物, 路径)


def 加载产物(路径: Path) -> 十号HMM训练产物:
    import joblib

    return joblib.load(路径)
