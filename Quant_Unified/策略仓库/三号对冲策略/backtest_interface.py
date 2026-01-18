# -*- coding: utf-8 -*-
"""
3号对冲策略 - 策略接口版回测（策略脑子 + 通用执行器）

这个文件是干嘛的？
    用“统一策略接口 + 通用回测执行器”的方式跑 3 号对冲策略回测：
        - 策略脑子：三号对冲策略脑子（输出对冲模式挂单：LONG/SHORT）
        - 回测执行器：K线对冲撮合执行器（按 OHLC 路径模拟成交，并做爆仓检测）

运行方法：
    cd /Users/chuan/Desktop/xiangmu/客户端/Quant_Unified
    python3 -X utf8 策略仓库/三号对冲策略/backtest_interface.py --no-chart
"""

from __future__ import annotations

import copy
import logging
import math
import sys
from pathlib import Path

import pandas as pd

# ====== 自动计算项目根目录 ======
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]  # Quant_Unified
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ====== 策略与数据 ======
from 策略仓库.三号对冲策略.config_backtest import backtest_strategies
from 策略仓库.三号对冲策略.program.strategy_brain import 三号对冲策略脑子

# 复用二号策略的数据准备模块（已经对齐到“历史行情中心”）
from 策略仓库.二号网格策略.program.step1_prepare_data import prepare_data

# ====== 执行器与回测工具 ======
from 基础库.common_core.strategy import K线, K线对冲撮合执行器
from 基础库.common_core.backtest.metrics import 回测指标计算器
from 基础库.common_core.backtest.进度条 import 回测进度条
from 基础库.common_core.backtest.可视化 import 回测可视化

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("Hedge_Backtest_Interface")


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


def 运行单策略回测(conf, *, 显示图表: bool, 限制条数: int | None) -> dict:
    # limit 模式：缩短数据下载窗口（避免为了快速自检还去拉超长数据）
    if 限制条数 is not None and hasattr(conf, "num_hours"):
        try:
            conf = copy.copy(conf)
            需要小时 = max(1, int(math.ceil(float(限制条数) / 60.0)))
            conf.num_hours = 需要小时
        except Exception:
            pass

    df = prepare_data(conf)
    if df.empty:
        raise RuntimeError(f"❌ 数据为空：{getattr(conf, 'symbol', 'UNKNOWN')}")

    df = df.copy().reset_index(drop=True)
    if 限制条数 is not None:
        限制条数 = int(限制条数)
        if 限制条数 <= 2:
            raise ValueError("❌ --limit 至少为 3")
        df = df.iloc[:限制条数].copy().reset_index(drop=True)
        logger.info(f"🧪 LIMIT 模式：只回测前 {len(df):,} 条 K 线（用于快速自检）")

    symbol = str(getattr(conf, "symbol", "") or "UNKNOWN").upper()
    初始资金 = float(getattr(conf, "money", 0.0) or 0.0)
    if 初始资金 <= 0:
        raise ValueError(f"❌ 初始资金 money 必须 > 0，当前={初始资金}")

    策略 = 三号对冲策略脑子(conf)
    执行器 = K线对冲撮合执行器(
        交易对=symbol,
        初始资金=float(初始资金),
        maker_fee=float(getattr(conf, "maker_fee", 0.0) or 0.0),
        启用迟滞更新=False,
    )

    # ====== 第 0 根 K 线收盘先挂第一轮单 ======
    k0 = _构造K线(df, 0)
    执行器.设置最新价(float(k0.收))
    输出0 = 策略.在K线收盘(k0, 执行器.获取账户状态())
    执行器.执行策略输出(输出0)

    权益曲线: list[float] = []
    时间序列: list[pd.Timestamp] = []
    价格序列: list[float] = []
    成交次数 = 0

    总条数 = max(0, len(df) - 1)
    with 回测进度条(总数=总条数, 描述=f"3号对冲接口回测[{symbol}]") as 进度:
        for idx in range(1, len(df)):
            k线 = _构造K线(df, idx)

            成交列表 = 执行器.推进K线(k线)
            成交次数 += len(成交列表)
            for 成交 in 成交列表:
                策略.在成交回报(成交)

            if 执行器.是否爆仓:
                logger.error(
                    f"💀 触发爆仓 | time_ms={执行器.爆仓时间_ms} | price={执行器.爆仓价格} | index={idx}"
                )
                for j in range(idx, len(df)):
                    时间序列.append(df["candle_begin_time"].iloc[j])
                    价格序列.append(float(df["close"].iloc[j]))
                    权益曲线.append(0.0)
                    进度.更新(1)
                break

            账户 = 执行器.获取账户状态()
            输出 = 策略.在K线收盘(k线, 账户)
            执行器.执行策略输出(输出)

            权益曲线.append(float(账户.账户权益))
            时间序列.append(df["candle_begin_time"].iloc[idx])
            价格序列.append(float(k线.收))

            进度.更新(1)

    计算器 = 回测指标计算器(
        权益曲线=权益曲线,
        初始资金=float(初始资金),
        时间戳=时间序列,
        周期每年数量=525600,
    )
    计算器.打印报告(策略名称=f"3号对冲策略 (接口回测) | {symbol}")
    print(f"🔄 总成交次数: {成交次数}")

    if 显示图表 and 权益曲线:
        报告参数 = {
            "symbol": symbol,
            "money": float(初始资金),
            "leverage": getattr(conf, "leverage", None),
            "grid_percent": getattr(conf, "grid_percent", None),
            "grid_levels": getattr(conf, "grid_levels", None),
            "initial_long_size": getattr(conf, "initial_long_size", None),
            "initial_short_size": getattr(conf, "initial_short_size", None),
            "max_individual_position_size": getattr(conf, "max_individual_position_size", None),
            "execution_model": "策略接口 + K线对冲撮合执行器（OHLC路径）",
        }
        可视化器 = 回测可视化(
            权益曲线=权益曲线,
            时间序列=时间序列,
            初始资金=float(初始资金),
            价格序列=价格序列,
            显示图表=True,
            保存路径=str(getattr(conf, "result_dir", PROJECT_ROOT / "策略仓库/三号对冲策略")),
            报告参数=报告参数,
        )
        可视化器.生成报告(策略名称=f"3号对冲策略 (接口回测) | {symbol}")

    return {
        "symbol": symbol,
        "trades": 成交次数,
        "final_equity": float(权益曲线[-1]) if 权益曲线 else 0.0,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="3号对冲策略回测（策略接口版）")
    parser.add_argument("--no-chart", action="store_true", help="不生成可视化报告（CI 建议开）")
    parser.add_argument("--limit", type=int, default=None, help="只回测前 N 条分钟线（快速自检用）")
    args = parser.parse_args()

    logger.info("========================================")
    logger.info("     3号对冲策略 - 策略接口版回测       ")
    logger.info("========================================")

    results: list[dict] = []
    for conf in backtest_strategies:
        logger.info(f"\n=== 开始回测: {getattr(conf, 'symbol', 'UNKNOWN')} ===")
        r = 运行单策略回测(conf, 显示图表=not args.no_chart, 限制条数=args.limit)
        results.append(r)

    if results:
        print(pd.DataFrame(results))


if __name__ == "__main__":
    main()

