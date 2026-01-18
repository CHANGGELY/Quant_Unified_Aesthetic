# -*- coding: utf-8 -*-
"""
8号香农策略 - 策略接口版回测（策略脑子 + 通用执行器）

这个文件是干嘛的？
    用“策略接口 + 执行器”的架构跑回测：
        - 策略脑子：八号香农策略脑子（输出目标挂单）
        - 回测执行器：K线撮合执行器（按 OHLC 路径模拟成交）

这样做的意义：
    回测与实盘走同一份策略逻辑，避免“回测一套、实盘一套”。

运行方法：
    cd /Users/chuan/Desktop/xiangmu/客户端/Quant_Unified
    python3 -X utf8 策略仓库/八号香农策略/backtest_interface.py --no-chart
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

# ====== 自动计算项目根目录 ======
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ====== 策略与配置 ======
from 策略仓库.八号香农策略 import config_backtest as cfg
from 策略仓库.八号香农策略.backtest import 加载数据
from 策略仓库.八号香农策略.program.leverage_model import (
    resolve_leverage_spec,
    target_position_notional,
)
from 策略仓库.八号香农策略.program.strategy_brain import 八号香农策略脑子

# ====== 执行器与回测工具 ======
from 基础库.common_core.strategy import K线, K线撮合执行器
from 基础库.common_core.backtest.metrics import 回测指标计算器
from 基础库.common_core.backtest.进度条 import 回测进度条
from 基础库.common_core.backtest.可视化 import 回测可视化

# ====== 日志 ======
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("Backtest_Interface")


def _构造K线(df: pd.DataFrame, idx: int) -> K线:
    row = df.iloc[idx]
    开始时间 = row["candle_begin_time"]
    if isinstance(开始时间, pd.Timestamp):
        开始时间_ms = int(开始时间.value // 10**6)
    else:
        开始时间_ms = int(pd.Timestamp(开始时间).value // 10**6)
    收盘时间_ms = 开始时间_ms + 60_000
    return K线(
        开始时间_ms=开始时间_ms,
        收盘时间_ms=收盘时间_ms,
        开=float(row["open"]),
        高=float(row["high"]),
        低=float(row["low"]),
        收=float(row["close"]),
        成交量=float(row.get("volume", 0.0) or 0.0),
    )


def 运行回测(显示图表: bool = True, 限制条数: int | None = None) -> None:
    # ====== 1) 读取配置 & 数据 ======
    df, 交易起始索引 = 加载数据(getattr(cfg, "data_file", None))

    if 限制条数 is not None:
        限制条数 = int(限制条数)
        if 限制条数 <= 0:
            raise ValueError("❌ --limit 必须是正整数（表示：交易开始后取多少条分钟线做自检）")
        结束索引 = int(min(len(df), int(交易起始索引) + 限制条数))
        df = df.iloc[:结束索引].copy().reset_index(drop=True)
        交易段条数 = max(0, len(df) - int(交易起始索引))
        logger.info(
            f"🧪 LIMIT 模式：预热+交易 共 {len(df):,} 条 | 交易段 {交易段条数:,} 条 | 交易起始索引={交易起始索引}"
        )

    交易起始索引 = int(max(2, int(交易起始索引)))
    if len(df) - 交易起始索引 < 10:
        raise ValueError("❌ 交易起始点之后的数据太少，无法回测（请检查 start_date / limit）")

    # ====== 2) 初始化策略脑子 ======
    策略 = 八号香农策略脑子(cfg)

    # 预热：只喂到 交易起始索引-2，避免和首根交易 K 线重复
    for i in range(0, 交易起始索引 - 1):
        策略.预热收盘价(float(df["close"].iloc[i]))

    # ====== 3) 初始化执行器（保证金口径）======
    杠杆信息 = resolve_leverage_spec(
        cfg,
        target_ratio=float(getattr(cfg, "target_ratio", 0.5)),
        max_position_leverage=getattr(cfg, "max_position_leverage", None),
    )

    初始资金 = float(getattr(cfg, "initial_capital", 1000.0))
    target_ratio = float(getattr(cfg, "target_ratio", 0.5))
    初始价格 = float(df["close"].iloc[交易起始索引 - 1])
    初始名义 = target_position_notional(初始资金, float(杠杆信息.position_leverage), target_ratio)
    初始持仓数量 = 初始名义 / 初始价格 if 初始价格 > 0 else 0.0

    symbol = str(getattr(cfg, "symbol", "") or "ETHUSDT").upper().strip()

    执行器 = K线撮合执行器(
        交易对=symbol,
        初始资金=初始资金,
        初始持仓数量=初始持仓数量,
        初始持仓均价=初始价格 if 初始持仓数量 > 0 else 0.0,
        maker_fee=float(getattr(cfg, "maker_fee", 0.0) or 0.0),
        update_threshold_ratio=float(getattr(cfg, "update_threshold_ratio", 0.05)),
        价格偏离阈值=0.5,
    )
    执行器.设置最新价(初始价格)

    # ====== 4) 在“交易起点前一根K线收盘”先挂单 ======
    起始前K线 = _构造K线(df, 交易起始索引 - 1)
    账户 = 执行器.获取账户状态()
    输出 = 策略.在K线收盘(起始前K线, 账户)
    执行器.执行策略输出(输出)

    # ====== 5) 主循环：撮合 + 决策 ======
    权益曲线: list[float] = []
    宽度曲线: list[float] = []
    状态曲线: list[str] = []
    时间序列: list[pd.Timestamp] = []
    价格序列: list[float] = []
    成交次数 = 0

    总条数 = len(df) - 交易起始索引
    with 回测进度条(总数=总条数, 描述="策略接口回测") as 进度:
        for idx in range(交易起始索引, len(df)):
            k线 = _构造K线(df, idx)

            # 1) 用本根 K 线撮合上一分钟挂单
            成交列表 = 执行器.推进K线(k线)
            成交次数 += len(成交列表)
            for 成交 in 成交列表:
                策略.在成交回报(成交)

            # 2) 收盘后更新策略
            账户 = 执行器.获取账户状态()
            输出 = 策略.在K线收盘(k线, 账户)
            执行器.执行策略输出(输出)

            # 3) 记录曲线
            权益曲线.append(float(账户.账户权益))
            价格序列.append(float(k线.收))
            时间序列.append(df["candle_begin_time"].iloc[idx])

            备注 = 输出.备注 or {}
            宽度曲线.append(float(备注.get("grid_width", 0.0) or 0.0))
            状态曲线.append(str(备注.get("regime", "UNKNOWN") or "UNKNOWN"))

            进度.更新(1)

    # ====== 6) 输出指标 ======
    计算器 = 回测指标计算器(
        权益曲线=权益曲线,
        初始资金=初始资金,
        时间戳=时间序列,
        周期每年数量=525600,
    )
    计算器.打印报告(策略名称="8号香农策略 (策略接口回测)")
    print(f"🔄 总成交次数: {成交次数}")

    # ====== 7) 可视化 ======
    回测配置参数 = {
        "data_file": getattr(cfg, "data_file", None),
        "data_start_date": getattr(cfg, "data_start_date", None),
        "data_points_total": int(len(df)),
        "data_points_traded": int(len(权益曲线)),
        "initial_capital": float(初始资金),
        "target_ratio": float(target_ratio),
        "vol_short_window": int(getattr(cfg, "vol_short_window", 60)),
        "vol_long_window": int(getattr(cfg, "vol_long_window", 1440)),
        "vol_ewma_alpha": float(getattr(cfg, "vol_ewma_alpha", 0.05)),
        "vol_k_factor": float(getattr(cfg, "vol_k_factor", 1.0)),
        "min_grid_width_bps": float(getattr(cfg, "min_grid_width_bps", 1.0)),
        "regime_spike_threshold": float(getattr(cfg, "regime_spike_threshold", 1.5)),
        "regime_crush_threshold": float(getattr(cfg, "regime_crush_threshold", 0.5)),
        "width_multiplier_spike": float(getattr(cfg, "width_multiplier_spike", 1.5)),
        "width_multiplier_crush": float(getattr(cfg, "width_multiplier_crush", 0.8)),
        "grid_layers": int(getattr(cfg, "grid_layers", 3)),
        "force_order_band": float(getattr(cfg, "force_order_band", 0.1)),
        "min_qty": float(getattr(cfg, "min_qty", 0.007)),
        "update_threshold_ratio": float(getattr(cfg, "update_threshold_ratio", 0.05)),
        "position_leverage(Z)_resolved": float(杠杆信息.position_leverage),
        "nominal_leverage(W)_resolved": float(杠杆信息.nominal_leverage),
        "execution_model": "策略接口 + K线撮合执行器（OHLC路径）",
    }

    可视化器 = 回测可视化(
        权益曲线=权益曲线,
        时间序列=时间序列,
        初始资金=float(初始资金),
        价格序列=价格序列,
        显示图表=显示图表,
        保存路径=PROJECT_ROOT / "策略仓库/八号香农策略",
        报告参数=回测配置参数,
    )
    可视化器.生成报告(策略名称="8号香农策略 (策略接口回测)")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="8号香农策略回测（策略接口版）")
    parser.add_argument("--no-chart", action="store_true", help="不自动打开浏览器（仍会保存 HTML）")
    parser.add_argument("--limit", type=int, default=None, help="只取前 N 条数据做快速自检（正式回测不要用）")
    args = parser.parse_args()

    运行回测(显示图表=not args.no_chart, 限制条数=args.limit)
