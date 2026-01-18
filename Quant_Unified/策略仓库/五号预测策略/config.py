#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
五号预测策略全局配置文件 (升级版)
整合了原有的回测配置，并新增了对 Tardis 高频数据的支持。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# === 核心配置常量 ===
DATA_SOURCE_TYPE = Literal['kaggle', 'tardis']


def _定位仓库根目录() -> Path:
    """
    通过当前文件位置，向上找到仓库根目录（Quant_Unified 的上一层）。

    这样做的好处：
        - 不依赖运行时的工作目录（cwd）
        - 不依赖你是否设置了 PYTHONPATH
    """
    p = Path(__file__).resolve()
    for parent in p.parents:
        if parent.name == "Quant_Unified":
            return parent.parent
    return p.parents[3]


def _default_symbol() -> str:
    return os.environ.get("PREDICT5_SYMBOL", "BTCUSDT")

def _default_data_source() -> DATA_SOURCE_TYPE:
    return os.environ.get("PREDICT5_DATA_SOURCE", "tardis")

def _default_data_root() -> Path:
    v = os.environ.get("PREDICT5_DATA_ROOT")
    if v:
        return Path(v)
    
    # 默认从“统一历史行情中心”找（仓库根目录下的数据/历史行情中心）
    # 兜底再退回到策略目录，避免你本地旧结构直接跑不起来。
    仓库根 = _定位仓库根目录()
    历史行情中心 = 仓库根 / "数据" / "历史行情中心"

    if _default_data_source() == "tardis":
        候选 = [
            # 1) 高频增量盘口（我们现在主要用这个：*_incremental.parquet）
            历史行情中心 / "外部数据" / "Tardis" / "final_parquet",
            # 2) 处理后的 depth/trade（未来如果要做更复杂的特征可用）
            历史行情中心 / "外部数据" / "Tardis" / "processed",
            仓库根 / "Quant_Unified" / "data" / "外部数据" / "Tardis" / "processed",
            Path(__file__).parent / "final_parquet",  # 兼容旧位置
        ]
    else:
        候选 = [
            历史行情中心 / "外部数据" / "Kaggle_L2_1m",
            仓库根 / "Quant_Unified" / "data" / "外部数据" / "Kaggle_L2_1m",
        ]

    for p in 候选:
        if p.exists():
            return p
    return 候选[-1]


def _default_depth_levels() -> int:
    """
    深度档位（支持 5/10/20/50/100）

    优先级：
        1) 环境变量 DEPTH_LEVEL
        2) Quant_Unified/config.py 的 DEPTH_LEVEL
        3) 默认 20
    """
    v = os.environ.get("DEPTH_LEVEL", "").strip()
    if v:
        try:
            return max(1, int(v))
        except ValueError:
            pass

    try:
        from Quant_Unified.config import DEPTH_LEVEL as _DEPTH_LEVEL  # type: ignore

        return max(1, int(_DEPTH_LEVEL))
    except Exception:
        return 20



@dataclass(frozen=True)
class Config:
    # --- 基础配置 ---
    symbol: str = field(default_factory=_default_symbol)
    data_source: DATA_SOURCE_TYPE = field(default_factory=_default_data_source)
    data_root: Path = field(default_factory=_default_data_root)

    # --- Tardis 高频特有配置 ---
    # 采样间隔 (毫秒)
    sample_interval_ms: int = 100
    # 价格/数量还原倍数 (必须与 ETL 脚本一致)
    price_mult: float = 100.0
    amount_mult: float = 1000.0
    
    # --- 预测目标 ---
    # 预测未来 N 个时间单位 (单位取决于 sample_interval_ms)
    # 对于 100ms 采样: 
    # h=50 -> 5秒
    # h=100 -> 10秒
    # h=300 -> 30秒
    horizons: tuple[int, ...] = (50, 100, 200, 300, 600) 
    
    label_threshold: float = 0.0002  # 阈值调低，适应高频微观波动
    label_modes: tuple[str, ...] = ("executable", "wmp")

    # --- 推理/信号参数（实盘与接口回测会用到）---
    # 多分类模型的迟滞阈值（hysteresis：迟滞，意思是“进场/出场用不同阈值”，避免来回打脸）
    p_enter: float = 0.55
    p_exit: float = 0.55
    diff_enter: float = 0.0
    diff_exit: float = 0.0

    # 默认使用“1s 口径”的模型：{symbol}_{mode}_h{horizon_s}.pkl
    # - horizon_s：预测未来多少个“数据点”（当我们按 1s 采样时，它也就是多少秒）
    # - mode：wmp（加权中间价）或 executable（跨点差可成交口径）
    model_horizon_s: int = 10
    model_mode: str = "executable"
    inference_interval_ms: int = 1000

    # --- 交易参数 ---
    fee_rate: float = 0.0002   # 0.02% taker fee
    slippage_rate: float = 0.0001 # 0.01% 滑点预估

    # --- 执行/风控参数（高频信号 -> 仓位调仓执行器 会用到）---
    initial_capital: float = 10_000.0
    leverage: float = 1.0
    qty_step: float = 0.001
    min_order_notional: float = 5.0
    min_margin_rate: float = 0.005

    # --- 模型训练 ---
    train_frac: float = 0.7
    random_state: int = 42
    
    # --- 数据加载 ---
    depth_levels: int = field(default_factory=_default_depth_levels)
    start_date: str | None = None
    end_date: str | None = None
    # 是否只加载特定日期 (None表示加载目录下所有)
    target_date: str | None = None 
