# -*- coding: utf-8 -*-
"""
十号隐马尔可夫策略 - 配置文件

用人话解释这个文件：
    你可以把它当成“策略的旋钮面板”：
    - 数据从哪里来
    - 训练用多少数据、训练多久
    - 模型有几个隐状态（上涨/下跌/震荡）
    - 推断未来 8 小时概率时，用过去多少小时作为输入
    - 最终多空各选前 10% 的币
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _定位仓库根目录() -> Path:
    """
    定位仓库根目录（Quant_Unified 的上一层）。

    这样做的好处：
        - 不依赖你从哪个目录运行脚本（cwd）
        - 也不依赖你手工配置 PYTHONPATH
    """
    p = Path(__file__).resolve()
    for parent in p.parents:
        if parent.name == "Quant_Unified":
            return parent.parent
    return p.parents[3]


@dataclass(frozen=True)
class Config:
    # ====== 数据入口 ======
    数据zip路径: Path = field(
        default_factory=lambda: (
            Path(os.getenv("HMM10_ZIP_PATH", "")).expanduser().resolve()
            if os.getenv("HMM10_ZIP_PATH")
            else _定位仓库根目录()
            / "数据"
            / "历史行情中心"
            / "币对分类全量小时 K 数据"
            / "coin-binance-swap-candle-csv-1h-2025-12-19.zip"
        )
    )

    # ====== 训练范围（None 表示用全量；建议先从短一些开始跑通）======
    训练开始时间: str | None = os.getenv("HMM10_TRAIN_START") or None  # 例如 "2022-01-01"
    训练结束时间: str | None = os.getenv("HMM10_TRAIN_END") or None    # 例如 "2025-06-01"

    # ====== 训练规模控制 ======
    最大训练币种数: int = int(os.getenv("HMM10_MAX_TRAIN_SYMBOLS", "200"))
    每币最多使用K线数: int = int(os.getenv("HMM10_MAX_BARS_PER_SYMBOL", "6000"))

    # ====== HMM 模型参数 ======
    隐状态数: int = 3  # 3 个状态：上涨/震荡/下跌（最终会用“收益均值”自动映射）
    最大迭代次数: int = int(os.getenv("HMM10_MAX_ITER", "30"))
    收敛阈值: float = float(os.getenv("HMM10_TOL", "1e-4"))
    随机种子: int = int(os.getenv("HMM10_SEED", "42"))
    方差下限: float = float(os.getenv("HMM10_VAR_FLOOR", "1e-6"))

    # ====== 推断参数 ======
    推断回看小时数: int = int(os.getenv("HMM10_LOOKBACK_HOURS", "96"))  # 用过去多少小时来估计“当前状态概率”
    预测步长小时: int = 8
    震荡阈值_8小时对数收益: float = float(os.getenv("HMM10_RANGE_TH", "0.005"))

    # 推断规模控制（0/None 表示全量）
    最大推断币种数: int = int(os.getenv("HMM10_MAX_PRED_SYMBOLS", "0"))
    截止时间抽样币种数: int = int(os.getenv("HMM10_CUTOFF_SAMPLE", "80"))
    截止时间分位数: float = float(os.getenv("HMM10_CUTOFF_QUANTILE", "0.2"))

    # ====== 选币参数 ======
    多头选币比例: float = 0.10
    空头选币比例: float = 0.10

    # ====== 回测参数（中性多空：多头/空头各占 50% 资金） ======
    回测开始时间: str = os.getenv("HMM10_BT_START", "2021-01-01")  # 建议 >= 2021-01-01
    回测结束时间: str | None = os.getenv("HMM10_BT_END") or None  # None 表示用数据能跑到的最晚时间
    回测初始资金: float = float(os.getenv("HMM10_BT_CAPITAL", "10000"))
    回测手续费率: float = float(os.getenv("HMM10_BT_FEE", str(6 / 10000)))  # 交易成本（合约 taker + 滑点近似）
    回测滑点率: float = float(os.getenv("HMM10_BT_SLIPPAGE", "0.0"))  # 额外滑点（可先设 0）
    回测币种上限: int = int(os.getenv("HMM10_BT_MAX_SYMBOLS", "300"))  # 0 表示全量
    回测预热小时: int = int(os.getenv("HMM10_BT_WARMUP_HOURS", "240"))  # 用于稳定状态分布（默认 10 天）

    # 再平衡周期：默认和预测步长一致（8小时一调仓）
    回测再平衡小时: int = int(os.getenv("HMM10_BT_REBAL_HOURS", "8"))

    # ====== 输出与缓存 ======
    模型目录: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "models")
    缓存目录: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "cache")


# 稳定币信息（用于过滤，避免把稳定币当成“可交易币”参与选币）
stable_symbol = [
    'BKRW', 'USDC', 'USDP', 'TUSD', 'BUSD', 'FDUSD', 'DAI', 'EUR', 'GBP', 'USBP', 'SUSD', 'PAXG', 'AEUR'
]
