# -*- coding: utf-8 -*-
"""
6号 MACD 策略 - 策略接口版回测（脑子 + 调仓执行器）

这个文件是干嘛的？
    这是把 6 号策略接入“统一架构”的回测入口：
        - 策略脑子：program/strategy_brain.py（只输出目标仓位）
        - 执行器：common_core.strategy.K线调仓执行器（负责成交、成本、爆仓）

运行方法：
    cd /Users/chuan/Desktop/xiangmu/客户端/Quant_Unified
    python3 -X utf8 策略仓库/六号MACD策略/backtest_interface.py --no-chart
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ====== 将 Quant_Unified 加入 sys.path，保证中文模块导入正常 ======
QUANT_ROOT = Path(__file__).resolve().parents[2]
if str(QUANT_ROOT) not in sys.path:
    sys.path.append(str(QUANT_ROOT))

for folder in ["基础库", "服务", "策略仓库", "应用"]:
    p = QUANT_ROOT / folder
    if p.exists() and str(p) not in sys.path:
        sys.path.append(str(p))

from 基础库.common_core.backtest.metrics import 回测指标计算器  # noqa: E402
from 基础库.common_core.backtest.可视化 import 回测可视化  # noqa: E402
from 基础库.common_core.backtest.进度条 import 回测进度条  # noqa: E402
from 基础库.common_core.strategy import K线, K线调仓执行器  # noqa: E402

from 策略仓库.六号MACD策略.config_backtest import MacdStrategy6Config  # noqa: E402
from 策略仓库.六号MACD策略.program.strategy_brain import 六号MACD策略脑子  # noqa: E402


def _加载分钟K线_从H5(path: Path, dataset: str, time_col: str) -> pd.DataFrame:
    import hdf5plugin  # noqa: F401  # 注册压缩插件（BLOSC/ZSTD/...）
    import h5py

    if not path.exists():
        raise FileNotFoundError(f"❌ 找不到真实数据文件: {path}")

    with h5py.File(path, "r") as f:
        if dataset not in f:
            raise KeyError(f"❌ 数据集不存在: {dataset} in {path}")
        arr = f[dataset][:]

    df = pd.DataFrame.from_records(arr)
    if time_col not in df.columns:
        raise KeyError(f"❌ 时间列不存在: {time_col}, 实际列={list(df.columns)}")

    df["candle_begin_time"] = pd.to_datetime(df[time_col], unit="ns")
    df.sort_values("candle_begin_time", inplace=True)
    df.drop_duplicates("candle_begin_time", keep="last", inplace=True)
    df.reset_index(drop=True, inplace=True)

    for c in ["open", "high", "low", "close", "volume"]:
        if c in df.columns:
            df[c] = df[c].astype(float)

    return df


def _构造K线(df: pd.DataFrame, idx: int) -> K线:
    t = pd.Timestamp(df["candle_begin_time"].iloc[idx])
    开始时间_ms = int(t.value // 10**6)
    return K线(
        开始时间_ms=开始时间_ms,
        收盘时间_ms=开始时间_ms + 60_000,
        开=float(df["open"].iloc[idx]),
        高=float(df["high"].iloc[idx]),
        低=float(df["low"].iloc[idx]),
        收=float(df["close"].iloc[idx]),
        成交量=float(df.get("volume", 0.0).iloc[idx] if "volume" in df.columns else 0.0),
    )


def 运行回测(*, 显示图表: bool = True, 限制条数: int | None = None) -> None:
    cfg = MacdStrategy6Config()

    df = _加载分钟K线_从H5(cfg.data_path, cfg.h5_dataset, cfg.time_col)
    df = df.loc[:, ["candle_begin_time", "open", "high", "low", "close", "volume"]].copy()

    if 限制条数 is not None:
        限制条数 = int(限制条数)
        if 限制条数 <= 0:
            raise ValueError("❌ --limit 必须是正整数")
        df = df.iloc[:限制条数].copy().reset_index(drop=True)

    if len(df) < 10:
        raise ValueError("❌ 数据量太少，无法回测")

    策略 = 六号MACD策略脑子(cfg)
    执行器 = K线调仓执行器(
        交易对=str(cfg.symbol),
        初始资金=float(cfg.initial_capital),
        数量步进=float(cfg.qty_step),
        手续费率=float(cfg.fee_rate),
        滑点率=float(cfg.slippage_rate),
        最小下单名义=float(cfg.min_order_notional),
        最小维持保证金率=float(getattr(cfg, "min_margin_rate", 0.005)),
    )

    权益曲线: list[float] = []
    时间序列: list[pd.Timestamp] = []
    价格序列: list[float] = []

    with 回测进度条(总数=len(df), 描述="MACD6 回测") as 进度:
        for i in range(len(df)):
            k线 = _构造K线(df, i)

            # 1) 先用收盘价结算盈亏
            执行器.推进K线结算(k线)

            if 执行器.是否爆仓:
                # 爆仓后权益归零，剩余全部补 0
                for j in range(i, len(df)):
                    时间序列.append(pd.Timestamp(df["candle_begin_time"].iloc[j]))
                    价格序列.append(float(df["close"].iloc[j]))
                    权益曲线.append(0.0)
                    进度.更新(1)
                break

            # 2) 让脑子出目标仓位
            账户 = 执行器.获取账户状态()
            输出 = 策略.在K线收盘(k线, 账户)

            # 3) 执行调仓（在本根收盘价附近成交）
            执行器.执行策略输出(输出)

            账户2 = 执行器.获取账户状态()
            权益曲线.append(float(账户2.账户权益))
            时间序列.append(pd.Timestamp(df["candle_begin_time"].iloc[i]))
            价格序列.append(float(df["close"].iloc[i]))
            进度.更新(1)

    计算器 = 回测指标计算器(
        权益曲线=np.asarray(权益曲线, dtype=np.float64),
        初始资金=float(cfg.initial_capital),
        时间戳=np.asarray(时间序列),
        周期每年数量=525600,
    )
    计算器.打印报告(策略名称="6号MACD策略（接口回测）")

    可视化器 = 回测可视化(
        权益曲线=np.asarray(权益曲线, dtype=np.float64),
        时间序列=np.asarray(时间序列),
        初始资金=float(cfg.initial_capital),
        价格序列=np.asarray(价格序列, dtype=np.float64),
        显示图表=显示图表,
        保存路径=Path(__file__).resolve().parent,
        报告参数={
            "symbol": cfg.symbol,
            "fee_rate": cfg.fee_rate,
            "slippage_rate": cfg.slippage_rate,
            "qty_step": cfg.qty_step,
            "min_order_notional": cfg.min_order_notional,
            "min_margin_rate": float(getattr(cfg, "min_margin_rate", 0.005)),
            "macd_fast": cfg.macd_fast,
            "macd_slow": cfg.macd_slow,
            "macd_signal": cfg.macd_signal,
            "execution_model": "K线调仓执行器（收盘结算+收盘附近成交）",
        },
    )
    可视化器.生成报告(策略名称="6号MACD策略（接口回测）")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="6号MACD策略 - 策略接口版回测")
    parser.add_argument("--no-chart", action="store_true", help="不自动打开浏览器（仍会保存 HTML）")
    parser.add_argument("--limit", type=int, default=None, help="只取前 N 条数据做快速自检")
    args = parser.parse_args()

    运行回测(显示图表=not args.no_chart, 限制条数=args.limit)

