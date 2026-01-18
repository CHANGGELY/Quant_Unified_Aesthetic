# -*- coding: utf-8 -*-
"""
4号做市策略 - 策略接口版回测（策略脑子 + 通用执行器）

这个文件是干嘛的？
    用“统一策略接口 + 通用对冲撮合执行器”的方式跑 4 号做市策略回测：
        - 策略脑子：四号做市策略脑子（输出对冲模式挂单：开多/开空/平多/平空）
        - 回测执行器：K线对冲撮合执行器（按 OHLC 路径撮合 + 爆仓检测）

运行方法：
    cd /Users/chuan/Desktop/xiangmu/客户端/Quant_Unified
    python3 -X utf8 \"策略仓库/4 号做市策略/backtest_interface.py\" --no-chart --limit 20000
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ====== 路径准备 ======
CURRENT_FILE = Path(__file__).resolve()
THIS_DIR = CURRENT_FILE.parent  # 4 号做市策略
QUANT_ROOT = CURRENT_FILE.parents[2]  # Quant_Unified

for p in (str(THIS_DIR), str(QUANT_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

# ====== 配置 & 策略脑子 ======
from config_backtest_interface import backtest_strategies
from program.strategy_brain import 四号做市策略脑子

# ====== 数据定位（历史行情中心） ======
from 基础库.common_core.data_center.h5_klines import 获取分钟K线H5文件, 生成分钟K线文件名

# ====== 执行器 & 回测工具 ======
from 基础库.common_core.strategy import K线, K线对冲撮合执行器
from 基础库.common_core.backtest.metrics import 回测指标计算器
from 基础库.common_core.backtest.进度条 import 回测进度条
from 基础库.common_core.backtest.可视化 import 回测可视化

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("MM4_Backtest_Interface")


def _加载分钟线H5到DataFrame(*, symbol: str, start_date: str, end_date: str, limit: int | None) -> pd.DataFrame:
    """
    从统一“历史行情中心”读取分钟K线。
    """
    文件名 = 生成分钟K线文件名(symbol, 周期="1m", 开始日期="2019-11-01", 结束日期="2025-06-15", 带table后缀=True)
    h5_path = 获取分钟K线H5文件(文件名)

    import h5py
    import hdf5plugin  # noqa: F401

    with h5py.File(str(h5_path), "r") as f:
        table = f["klines"]["table"]
        times_ns = table["candle_begin_time_GMT8"][:].astype(np.int64)

        start_ts = pd.Timestamp(str(start_date)).value
        end_ts = pd.Timestamp(str(end_date)).value

        # 时间是升序，可以二分查找
        left = int(np.searchsorted(times_ns, start_ts, side="left"))
        right = int(np.searchsorted(times_ns, end_ts, side="right"))
        if right <= left:
            raise ValueError(f"❌ 选择的时间范围没有数据：{start_date} ~ {end_date}")

        if limit is not None:
            limit = int(limit)
            if limit <= 0:
                raise ValueError("❌ --limit 必须为正整数")
            right = min(right, left + limit)

        data = table[left:right]

    df = pd.DataFrame(
        {
            "candle_begin_time": pd.to_datetime(data["candle_begin_time_GMT8"].astype(np.int64), unit="ns"),
            "open": data["open"].astype(float),
            "high": data["high"].astype(float),
            "low": data["low"].astype(float),
            "close": data["close"].astype(float),
            "volume": data["volume"].astype(float),
        }
    )
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    return df


def _构造K线(df: pd.DataFrame, idx: int) -> K线:
    t = df["candle_begin_time"].iloc[idx]
    开始时间_ms = int(pd.Timestamp(t).value // 10**6)
    收盘时间_ms = 开始时间_ms + 60_000
    return K线(
        开始时间_ms=开始时间_ms,
        收盘时间_ms=收盘时间_ms,
        开=float(df["open"].iloc[idx]),
        高=float(df["high"].iloc[idx]),
        低=float(df["low"].iloc[idx]),
        收=float(df["close"].iloc[idx]),
        成交量=float(df.get("volume", 0.0).iloc[idx] if "volume" in df.columns else 0.0),
    )


def 运行单策略回测(conf, *, 显示图表: bool, limit: int | None) -> dict:
    symbol = str(getattr(conf, "symbol", "ETHUSDT") or "ETHUSDT").upper()
    df = _加载分钟线H5到DataFrame(
        symbol=symbol,
        start_date=str(getattr(conf, "start_date", "2021-01-01")),
        end_date=str(getattr(conf, "end_date", "2021-12-31")),
        limit=limit,
    )
    if df.empty or len(df) < 3:
        raise RuntimeError("❌ 数据太少，无法回测")

    初始资金 = float(getattr(conf, "initial_capital", 0.0) or 0.0)
    if 初始资金 <= 0:
        raise ValueError(f"❌ initial_capital 必须 > 0，当前={初始资金}")

    策略 = 四号做市策略脑子(conf)
    执行器 = K线对冲撮合执行器(
        交易对=symbol,
        初始资金=float(初始资金),
        maker_fee=0.0,
        最小维持保证金率=float(getattr(conf, "min_margin_rate", 0.005) or 0.005),
        启用迟滞更新=False,
    )

    # 第 0 根收盘先挂单
    k0 = _构造K线(df, 0)
    执行器.设置最新价(float(k0.收))
    输出0 = 策略.在K线收盘(k0, 执行器.获取账户状态())
    执行器.执行策略输出(输出0)

    权益曲线: list[float] = []
    时间序列: list[pd.Timestamp] = []
    价格序列: list[float] = []
    成交次数 = 0

    总条数 = max(0, len(df) - 1)
    with 回测进度条(总数=总条数, 描述=f"4号做市接口回测[{symbol}]") as 进度:
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
    计算器.打印报告(策略名称=f"4号做市策略 (接口回测) | {symbol}")
    print(f"🔄 总成交次数: {成交次数}")

    if 显示图表 and 权益曲线:
        报告参数 = {
            "symbol": symbol,
            "initial_capital": 初始资金,
            "leverage": getattr(conf, "leverage", None),
            "bid_spread": getattr(conf, "bid_spread", None),
            "ask_spread": getattr(conf, "ask_spread", None),
            "min_order_amount": getattr(conf, "min_order_amount", None),
            "max_position_value_ratio": getattr(conf, "max_position_value_ratio", None),
            "execution_model": "策略接口 + K线对冲撮合执行器（OHLC路径）",
        }
        可视化器 = 回测可视化(
            权益曲线=权益曲线,
            时间序列=时间序列,
            初始资金=float(初始资金),
            价格序列=价格序列,
            显示图表=True,
            保存路径=str(THIS_DIR),
            报告参数=报告参数,
        )
        可视化器.生成报告(策略名称=f"4号做市策略 (接口回测) | {symbol}")

    return {"symbol": symbol, "trades": 成交次数, "final_equity": float(权益曲线[-1]) if 权益曲线 else 0.0}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="4号做市策略回测（策略接口版）")
    parser.add_argument("--no-chart", action="store_true", help="不生成可视化报告")
    parser.add_argument("--limit", type=int, default=None, help="只回测前 N 条分钟线（快速自检用）")
    args = parser.parse_args()

    logger.info("========================================")
    logger.info("     4号做市策略 - 策略接口版回测       ")
    logger.info("========================================")

    results: list[dict] = []
    for conf in backtest_strategies:
        logger.info(f"\n=== 开始回测: {getattr(conf, 'symbol', 'UNKNOWN')} ===")
        results.append(运行单策略回测(conf, 显示图表=not args.no_chart, limit=args.limit))

    if results:
        print(pd.DataFrame(results))


if __name__ == "__main__":
    main()

