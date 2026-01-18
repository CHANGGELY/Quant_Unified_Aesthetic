# -*- coding: utf-8 -*-
"""
五号预测策略 - 策略接口版回测（盘口快照 + 通用执行器）

这个文件是干嘛的？
    用“策略脑子 + 执行器”的统一架构跑五号预测策略：
        - 策略脑子：五号预测策略脑子（L2 盘口 + 机器学习输出目标仓位）
        - 回测执行器：盘口调仓执行器（用 bid/ask 成交 + 成本扣减 + 爆仓检测）

为什么这比旧版更靠谱？
    旧版高频回测（backtest_hft_tardis.py）里有“每 100ms 瞬移到 mid/wap 调仓”的假设，
    这在实盘几乎做不到（点差 + 手续费 + 滑点都会让结果偏乐观）。
    这里我们用 bid/ask 撮合成交，更贴近真实执行成本。

运行方法（一定要在终端看日志）：
    cd /Users/chuan/Desktop/xiangmu/客户端/Quant_Unified
    python3 -X utf8 策略仓库/五号预测策略/backtest_interface.py --date 2019-12-01 --sample-interval-ms 1000 --limit 50000
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ====== 自动把 Quant_Unified 加入 sys.path ======
CURRENT_FILE = Path(__file__).resolve()
QUANT_UNIFIED_ROOT = CURRENT_FILE.parents[2]
if str(QUANT_UNIFIED_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_UNIFIED_ROOT))

from 策略仓库.五号预测策略.config import Config
from 策略仓库.五号预测策略.data_loader_tardis import TardisDataLoader
from 策略仓库.五号预测策略.program.strategy_brain import 五号预测策略脑子

from 基础库.common_core.strategy import 盘口快照, 盘口调仓执行器
from 基础库.common_core.backtest.metrics import 回测指标计算器
from 基础库.common_core.backtest.进度条 import 回测进度条

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("5号预测策略_接口回测")


def _扫描_tardis_可用日期(data_root: Path, symbol: str) -> list[str]:
    """
    扫描 data_root 下有哪些 {symbol}_YYYY-MM-DD_incremental.parquet 文件。
    """
    symbol = str(symbol).upper().strip()
    pat = re.compile(rf"^{re.escape(symbol)}_(\d{{4}}-\d{{2}}-\d{{2}})_incremental\.parquet$")
    dates: list[str] = []
    for p in data_root.glob(f"{symbol}_*_incremental.parquet"):
        m = pat.match(p.name)
        if m:
            dates.append(m.group(1))
    dates.sort()
    return dates


def _构造盘口快照(symbol: str, depth_levels: int, snap: dict) -> 盘口快照:
    ts = snap.get("timestamp", 0)
    # Tardis 增量数据里 timestamp 是微秒（us），我们统一转成毫秒（ms）
    时间_ms = int(ts // 1000) if isinstance(ts, (int, float)) else 0
    return 盘口快照.从扁平字典(
        交易对=str(symbol).upper().strip(),
        时间_ms=时间_ms,
        depth_levels=int(depth_levels),
        数据=snap,
    )


def 运行回测(cfg: Config, *, date_str: str, limit: int | None = None) -> None:
    symbol = str(cfg.symbol).upper().strip()

    # ====== 1) 初始化策略脑子 + 执行器 ======
    策略 = 五号预测策略脑子(cfg)
    执行器 = 盘口调仓执行器(
        交易对=symbol,
        初始资金=float(cfg.initial_capital),
        数量步进=float(cfg.qty_step),
        手续费率=float(cfg.fee_rate),
        滑点率=float(cfg.slippage_rate),
        最小下单名义=float(cfg.min_order_notional),
        最小维持保证金率=float(cfg.min_margin_rate),
        结算价模式="wmp",
    )

    # ====== 2) 读取数据（真实 Parquet） ======
    loader = TardisDataLoader(cfg)

    预估总数 = int((24 * 60 * 60 * 1000) // max(int(cfg.sample_interval_ms), 1))
    if limit is not None:
        预估总数 = int(min(预估总数, int(limit)))

    权益曲线: list[float] = []
    时间序列_ms: list[int] = []

    logger.info(f"🚀 开始回测 | symbol={symbol} | date={date_str} | sample={cfg.sample_interval_ms}ms")

    done = 0
    with 回测进度条(总数=预估总数, 描述="五号策略接口回测", 单位=" tick") as 进度:
        for snap in loader.load_day(date_str):
            快照 = _构造盘口快照(symbol, int(cfg.depth_levels), snap)
            执行器.推进盘口快照结算(快照)

            if 执行器.是否爆仓:
                logger.error(f"💀 触发爆仓 | time_ms={执行器.爆仓时间_ms} | price={执行器.爆仓价格}")
                break

            账户 = 执行器.获取账户状态()
            输出 = 策略.在盘口快照(快照, 账户)
            if 输出 is not None:
                执行器.执行策略输出(输出)

            # 记录权益（执行后）
            账户2 = 执行器.获取账户状态()
            权益曲线.append(float(账户2.账户权益))
            时间序列_ms.append(int(快照.时间_ms))

            done += 1
            进度.更新(1)
            if limit is not None and done >= int(limit):
                break

    if not 权益曲线:
        raise RuntimeError("❌ 没有生成任何权益数据（请检查数据文件/采样间隔/模型是否可用）")

    # ====== 3) 输出指标 ======
    初始资金 = float(cfg.initial_capital)
    周期每年数量 = int(round((365.25 * 24 * 60 * 60 * 1000) / max(int(cfg.sample_interval_ms), 1)))

    计算器 = 回测指标计算器(
        权益曲线=权益曲线,
        初始资金=初始资金,
        时间戳=pd.to_datetime(np.asarray(时间序列_ms, dtype=np.int64), unit="ms", utc=True),
        周期每年数量=周期每年数量,
    )
    计算器.打印报告(策略名称="五号预测策略（接口回测）")

    统计 = 执行器.获取调仓统计()
    logger.info(f"🔄 调仓次数: {统计.调仓次数} | 成交额: {统计.成交额:.2f} | 交易成本: {统计.交易成本:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="五号预测策略（接口版回测，Tardis L2）")
    parser.add_argument("--symbol", type=str, default=None, help="交易对，例如 BTCUSDT（默认取环境变量/配置默认）")
    parser.add_argument("--date", type=str, default=None, help="日期 YYYY-MM-DD（默认取 data_root 下最新可用日期）")
    parser.add_argument("--sample-interval-ms", type=int, default=None, help="生成快照的采样间隔（毫秒）")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 个快照用于自检")
    parser.add_argument("--data-root", type=str, default=None, help="强制指定 Tardis final_parquet 目录")
    args = parser.parse_args()

    symbol = (args.symbol or "").strip() or None

    cfg_kwargs = {}
    if symbol:
        cfg_kwargs["symbol"] = str(symbol).upper().strip()
    if args.data_root:
        cfg_kwargs["data_root"] = Path(args.data_root).expanduser().resolve()

    # 默认用 Tardis（高频增量盘口）
    cfg_kwargs["data_source"] = "tardis"

    cfg = Config(**cfg_kwargs)  # type: ignore[arg-type]

    # 默认采样间隔：跟推理间隔对齐（更快、更省内存）
    sample_interval_ms = int(args.sample_interval_ms) if args.sample_interval_ms else int(cfg.inference_interval_ms)
    cfg = Config(
        **{
            **cfg.__dict__,
            "sample_interval_ms": int(sample_interval_ms),
        }
    )

    if cfg.data_root is None:
        raise RuntimeError("❌ data_root 为空，请检查配置/环境变量")

    dates = _扫描_tardis_可用日期(Path(cfg.data_root), str(cfg.symbol))
    if not dates:
        raise FileNotFoundError(f"❌ 在 data_root 下找不到 {cfg.symbol}_YYYY-MM-DD_incremental.parquet: {cfg.data_root}")

    date_str = str(args.date).strip() if args.date else dates[-1]
    if date_str not in dates:
        logger.warning(f"⚠️ 你指定的 date={date_str} 不在 data_root 可用列表里，仍尝试直接读取")

    运行回测(cfg, date_str=date_str, limit=args.limit)


if __name__ == "__main__":
    main()
