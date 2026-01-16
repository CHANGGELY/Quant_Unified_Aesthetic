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

def _default_symbol() -> str:
    return os.environ.get("PREDICT5_SYMBOL", "BTCUSDT")

def _default_data_source() -> DATA_SOURCE_TYPE:
    return os.environ.get("PREDICT5_DATA_SOURCE", "tardis")

def _default_data_root() -> Path:
    v = os.environ.get("PREDICT5_DATA_ROOT")
    if v:
        return Path(v)
    
    # 智能判定：如果是 tardis 模式，指向 final_parquet
    # 否则保持原有 Kaggle 路径
    if _default_data_source() == 'tardis':
        return Path(__file__).parent / "final_parquet"
    else:
        return Path(__file__).resolve().parents[2] / "data" / "外部数据" / "Kaggle_L2_1m"

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

    # --- 交易参数 ---
    fee_rate: float = 0.0002   # 0.02% taker fee
    slippage_rate: float = 0.0001 # 0.01% 滑点预估

    # --- 模型训练 ---
    train_frac: float = 0.7
    random_state: int = 42
    
    # --- 数据加载 ---
    depth_levels: int = GLOBAL_DEPTH_LEVEL
    start_date: str | None = None
    end_date: str | None = None
    # 是否只加载特定日期 (None表示加载目录下所有)
    target_date: str | None = None 
