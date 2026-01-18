# -*- coding: utf-8 -*-
"""
测试：8号香农策略“执行级回测”两套指标口径必须一致

为什么要有这个测试？
    你要求执行级回测支持两种写法：
      A) 增量口径：撮合循环里边跑边更新波动率/中心价（更像实盘）
      B) 预计算口径：先用同一套递推公式把指标预跑成数组，再喂给撮合（更省时间，适合参数遍历）

    但 B 有一个风险：如果预计算公式和增量更新的公式哪怕有一点点不一样，
    回测就会“悄悄变成两套策略”，从而导致你拿回测结果去指导实盘时踩坑。

这个测试做什么？
    - 用真实历史数据文件（HDF5）读取一段分钟线（不是 Mock Data）
    - 同一段数据、同一套参数：
        - 跑 A（增量口径）
        - 跑 B（预计算口径）
    - 断言两者输出完全一致：
        - 权益曲线
        - 网格宽度曲线
        - 市场状态曲线
        - 成交次数

运行方法：
    cd /Users/chuan/Desktop/xiangmu/客户端
    python3 -X utf8 Quant_Unified/测试用例/test_八号香农_指标预计算一致性.py
"""

from __future__ import annotations

import time
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

from 策略仓库.八号香农策略 import backtest as 香农回测
from 策略仓库.八号香农策略 import config_backtest as cfg
from 策略仓库.八号香农策略.program.leverage_model import resolve_leverage_spec


class Test八号香农指标一致性(unittest.TestCase):
    def test_预计算与增量输出一致(self):
        数据文件 = Path(getattr(cfg, "data_file", ""))
        self.assertTrue(数据文件.exists(), f"❌ 找不到真实数据文件: {数据文件}")

        # 取一小段真实数据（仍然是“真实数据”，不是模拟数据）
        vol_short = int(getattr(cfg, "vol_short_window", 60))
        vol_long = int(getattr(cfg, "vol_long_window", 1440))
        交易起始索引 = int(max(2, max(vol_short, vol_long) + 10))
        交易段条数 = 2000
        总条数 = 交易起始索引 + 交易段条数

        import h5py
        import hdf5plugin  # noqa: F401  # 自动注册 BLOSC 等压缩插件

        with h5py.File(str(数据文件), "r") as f:
            table = f["klines"]["table"]
            data = table[:总条数]

        开 = np.ascontiguousarray(data["open"].astype(np.float64))
        高 = np.ascontiguousarray(data["high"].astype(np.float64))
        低 = np.ascontiguousarray(data["low"].astype(np.float64))
        收 = np.ascontiguousarray(data["close"].astype(np.float64))

        杠杆信息 = resolve_leverage_spec(
            cfg,
            target_ratio=float(getattr(cfg, "target_ratio", 0.5)),
            max_position_leverage=getattr(cfg, "max_position_leverage", None),
        )

        初始资金 = float(getattr(cfg, "initial_capital", 1000.0))
        target_ratio = float(getattr(cfg, "target_ratio", 0.5))
        vol_ewma_alpha = float(getattr(cfg, "vol_ewma_alpha", 0.05))
        regime_spike_threshold = float(getattr(cfg, "regime_spike_threshold", 1.5))
        regime_crush_threshold = float(getattr(cfg, "regime_crush_threshold", 0.5))
        vol_k_factor = float(getattr(cfg, "vol_k_factor", 1.0))
        width_multiplier_spike = float(getattr(cfg, "width_multiplier_spike", 1.5))
        width_multiplier_crush = float(getattr(cfg, "width_multiplier_crush", 0.8))
        min_grid_width_bps = float(getattr(cfg, "min_grid_width_bps", 1.0))
        grid_layers = int(getattr(cfg, "grid_layers", 3))
        min_qty = float(getattr(cfg, "min_qty", 0.007))
        force_order_band = float(getattr(cfg, "force_order_band", 0.1))
        update_threshold_ratio = float(getattr(cfg, "update_threshold_ratio", 0.05))

        # 方案 A：增量口径
        t0 = time.perf_counter()
        权益A, 宽度A, 状态A, 成交A = 香农回测._执行级回测_核心循环_增量指标(
            开,
            高,
            低,
            收,
            交易起始索引,
            初始资金,
            target_ratio,
            vol_short,
            vol_long,
            vol_ewma_alpha,
            regime_spike_threshold,
            regime_crush_threshold,
            vol_k_factor,
            width_multiplier_spike,
            width_multiplier_crush,
            min_grid_width_bps,
            grid_layers,
            min_qty,
            force_order_band,
            float(杠杆信息.position_leverage),
            update_threshold_ratio,
        )
        t1 = time.perf_counter()

        # 方案 B：预计算口径
        ewma_vol_in, ewma_price_in, regime_in = 香农回测._预计算_波动率状态序列(
            收,
            交易起始索引,
            vol_short,
            vol_long,
            vol_ewma_alpha,
            regime_spike_threshold,
            regime_crush_threshold,
        )
        权益B, 宽度B, 状态B, 成交B = 香农回测._执行级回测_核心循环_预计算指标(
            开,
            高,
            低,
            收,
            交易起始索引,
            初始资金,
            target_ratio,
            ewma_vol_in,
            ewma_price_in,
            regime_in,
            vol_k_factor,
            width_multiplier_spike,
            width_multiplier_crush,
            min_grid_width_bps,
            grid_layers,
            min_qty,
            force_order_band,
            float(杠杆信息.position_leverage),
            update_threshold_ratio,
        )
        t2 = time.perf_counter()

        # 输出耗时（不做严格性能断言，避免不同机器波动）
        print(f"\n⏱️ 增量口径耗时: {t1 - t0:.3f}s | 预计算口径耗时: {t2 - t1:.3f}s")

        # 断言：策略输出完全一致（允许极小的浮点误差）
        self.assertEqual(成交A, 成交B, "成交次数不一致：说明两种口径已变成两套策略")
        self.assertTrue(np.array_equal(状态A, 状态B), "市场状态曲线不一致：说明 regime 口径不一致")

        self.assertTrue(
            np.allclose(宽度A, 宽度B, rtol=0.0, atol=1e-12),
            "网格宽度曲线不一致：说明指标递推/阈值口径不一致",
        )
        self.assertTrue(
            np.allclose(权益A, 权益B, rtol=0.0, atol=1e-10),
            "权益曲线不一致：说明撮合输入指标不同，或撮合逻辑在两条路径里不一致",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

