# -*- coding: utf-8 -*-
"""
测试：8号香农策略的 CPRP 多层挂单公式必须“同口径”

为什么要做这个测试？
    我们正在把策略改造成：
        - 策略脑子：只输出“我想挂哪些单”
        - 执行器：回测里撮合 / 实盘里下单

    其中最容易“悄悄跑偏”的，就是 CPRP 多层挂单的公式：
        - 旧实现：program/cprp.py 的 CPRPEngine.calculate_rebalance()
        - 新统一口径：program/shannon_math.py 的 _计算_cprp_多层挂单()

    如果这两者不一致，就会出现：
        - 回测挂单一套
        - 实盘挂单另一套
    结果就是“回测看起来很美，实盘完全不是那回事”。

本测试怎么保证“不用假数据”？
    - 价格使用真实历史分钟线 HDF5 文件里的一段行情（不是 Mock Data）
    - 账户权益/持仓来自配置与公式推导（真实策略运行时也是这样初始化的）

运行方法：
    cd /Users/chuan/Desktop/xiangmu/客户端
    python3 -X utf8 Quant_Unified/测试用例/test_八号香农_CPRP挂单一致性.py
"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np


def _插入项目根目录到sys_path() -> None:
    import sys

    当前文件 = Path(__file__).resolve()
    项目根目录 = 当前文件.parents[1]  # Quant_Unified
    if str(项目根目录) not in sys.path:
        sys.path.insert(0, str(项目根目录))


_插入项目根目录到sys_path()

from 策略仓库.八号香农策略 import config_backtest as cfg
from 策略仓库.八号香农策略.program.cprp import CPRPEngine
from 策略仓库.八号香农策略.program.leverage_model import resolve_leverage_spec, target_position_notional
from 策略仓库.八号香农策略.program.strategy_brain import 八号香农策略脑子

from 基础库.common_core.strategy import K线, 账户状态, 订单方向


def _读取真实OHLC样本(*, 总条数: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    优先读取本机完整 H5；若 CI 环境没有大文件，则回退到仓库内的“真实数据样本 .npz”。
    """
    数据文件 = Path(getattr(cfg, "data_file", "") or "")
    if 数据文件.exists():
        import h5py
        import hdf5plugin  # noqa: F401

        with h5py.File(str(数据文件), "r") as f:
            table = f["klines"]["table"]
            data = table[:总条数]

        开 = data["open"].astype(np.float64)
        高 = data["high"].astype(np.float64)
        低 = data["low"].astype(np.float64)
        收 = data["close"].astype(np.float64)
        return 开, 高, 低, 收

    样本文件 = Path(__file__).resolve().parent / "真实数据样本" / "ETHUSDT_1m_2021-05-17_to_2021-05-23.npz"
    if not 样本文件.exists():
        raise FileNotFoundError(f"❌ 找不到真实数据样本: {样本文件}")

    npz = np.load(str(样本文件))
    开 = npz["open"][:总条数].astype(np.float64)
    高 = npz["high"][:总条数].astype(np.float64)
    低 = npz["low"][:总条数].astype(np.float64)
    收 = npz["close"][:总条数].astype(np.float64)
    return 开, 高, 低, 收


class Test八号香农CPRP挂单一致性(unittest.TestCase):
    def test_CPRP挂单与数学内核一致(self):
        vol_short = int(getattr(cfg, "vol_short_window", 60))
        vol_long = int(getattr(cfg, "vol_long_window", 1440))
        预热条数 = int(max(vol_short, vol_long) + 10)
        测试额外条数 = 60
        总条数 = 预热条数 + 测试额外条数

        开, 高, 低, 收 = _读取真实OHLC样本(总条数=总条数)

        # ====== 初始化：策略脑子 + 旧 CPRP 引擎 ======
        策略 = 八号香农策略脑子(cfg)
        旧引擎 = CPRPEngine(cfg)

        # ====== 用真实行情预热策略脑子（喂收盘价）======
        for i in range(预热条数):
            策略.预热收盘价(float(收[i]))

        # ====== 构造一个“真实策略初始化口径”的账户状态 ======
        杠杆信息 = resolve_leverage_spec(
            cfg,
            target_ratio=float(getattr(cfg, "target_ratio", 0.5)),
            max_position_leverage=getattr(cfg, "max_position_leverage", None),
        )
        z = float(杠杆信息.position_leverage)

        账户权益 = float(getattr(cfg, "initial_capital", 1000.0))
        target_ratio = float(getattr(cfg, "target_ratio", 0.5))

        # 用预热结束时的价格推一个“目标 50/50”初始仓位（与 backtest.py 初始化一致）
        price0 = float(收[预热条数 - 1])
        x0 = target_position_notional(账户权益, z, target_ratio)
        position_qty = float(x0 / price0) if price0 > 0 else 0.0

        账户 = 账户状态(
            交易对="ETHUSDT",
            账户权益=账户权益,
            可用余额=账户权益,  # 策略脑子不依赖该字段，这里填充为方便
            持仓数量=position_qty,
            持仓均价=price0,
            未实现盈亏=0.0,
        )

        # ====== 取几根真实 K 线，逐根比对“挂单结果” ======
        # 说明：这里不做随机抽样，避免测试不稳定；固定取 3 个点足够覆盖不同波动率状态
        取样索引 = [
            预热条数,
            预热条数 + 10,
            预热条数 + 30,
        ]

        for idx in 取样索引:
            k线 = K线(
                开始时间_ms=int(idx) * 60_000,
                收盘时间_ms=int(idx + 1) * 60_000,
                开=float(开[idx]),
                高=float(高[idx]),
                低=float(低[idx]),
                收=float(收[idx]),
                成交量=0.0,
            )

            输出 = 策略.在K线收盘(k线, 账户)
            备注 = 输出.备注 or {}
            width = float(备注.get("grid_width", 0.0) or 0.0)
            center = float(备注.get("center_price", float(k线.收)) or float(k线.收))

            # 策略输出（新口径）
            新买单: list[dict] = []
            新卖单: list[dict] = []
            for 挂单 in 输出.目标挂单:
                if 挂单.方向 == 订单方向.买:
                    新买单.append({"price": float(挂单.价格), "qty": float(挂单.数量)})
                else:
                    新卖单.append({"price": float(挂单.价格), "qty": float(挂单.数量)})

            # 旧 CPRP 引擎输出（旧口径）
            旧买单, 旧卖单 = 旧引擎.calculate_rebalance(center, position_qty, 账户权益, width)

            self.assertEqual(len(新买单), len(旧买单), f"买单层数不一致 idx={idx}")
            self.assertEqual(len(新卖单), len(旧卖单), f"卖单层数不一致 idx={idx}")

            for i in range(len(新买单)):
                self.assertTrue(
                    np.isclose(新买单[i]["price"], float(旧买单[i]["price"]), rtol=0.0, atol=1e-12),
                    f"买单价格不一致 idx={idx} layer={i}",
                )
                self.assertTrue(
                    np.isclose(新买单[i]["qty"], float(旧买单[i]["qty"]), rtol=0.0, atol=1e-12),
                    f"买单数量不一致 idx={idx} layer={i}",
                )

            for i in range(len(新卖单)):
                self.assertTrue(
                    np.isclose(新卖单[i]["price"], float(旧卖单[i]["price"]), rtol=0.0, atol=1e-12),
                    f"卖单价格不一致 idx={idx} layer={i}",
                )
                self.assertTrue(
                    np.isclose(新卖单[i]["qty"], float(旧卖单[i]["qty"]), rtol=0.0, atol=1e-12),
                    f"卖单数量不一致 idx={idx} layer={i}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
