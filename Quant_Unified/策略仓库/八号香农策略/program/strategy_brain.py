# -*- coding: utf-8 -*-
"""
strategy_brain.py - 8号香农策略的“脑子”（只负责输出目标挂单）

这个文件是干嘛的？
    你要的最终形态是：
        策略（脑子）只说：我想挂哪些单
        执行器（手脚）负责：回测里撮合、实盘里下真实订单

    所以这里实现 common_core.strategy 的「策略接口」：
        - 在K线收盘：输入一根已收盘 K 线 + 当前账户状态 -> 输出目标挂单列表
        - 在成交回报：可选，用成交来更新内部状态（这里先做最小实现）

关键点（保证“回测=实盘口径”）：
    - 波动率/状态递推：使用 shannon_math.py 的同一套递推公式
    - CPRP 挂单：使用 shannon_math.py 的同一套多层挂单计算
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from 基础库.common_core.strategy import (
    K线,
    订单方向,
    限价挂单,
    成交回报,
    账户状态,
    策略输出,
    策略接口,
)

from .leverage_model import resolve_leverage_spec
from .shannon_math import (
    _波动率引擎_更新一次,
    _计算_cprp_多层挂单,
)


@dataclass(slots=True)
class _波动率递推状态:
    """
    只存“递推需要的状态”，不依赖 pandas。

    为什么要自己存这些？
        你想要回测/实盘同口径，并且回测要快。
        pandas 适合做一次性统计，但不适合“每分钟更新一次还要很快”。
    """

    vol_short_window: int
    vol_long_window: int

    short_buf: np.ndarray
    long_buf: np.ndarray
    short_pos: int = 0
    long_pos: int = 0
    short_count: int = 0
    long_count: int = 0
    short_sum: float = 0.0
    short_sumsq: float = 0.0
    long_sum: float = 0.0
    long_sumsq: float = 0.0

    prev_price: float = 0.0
    total_returns: int = 0
    ewma_vol: float = 0.0
    ewma_price: float = 0.0
    regime: int = 0  # 0 NORMAL, 1 SPIKE, 2 CRUSH


class 八号香农策略脑子(策略接口):
    """
    8号香农策略（CPRP：固定比例再平衡）的“脑子”实现。
    """

    def __init__(self, config):
        self._config = config

        self._symbol = str(getattr(config, "symbol", "") or "").upper().strip()
        if not self._symbol:
            # 回测里可能没有 symbol，但实盘一定要有
            self._symbol = "UNKNOWN"

        self._target_ratio = float(getattr(config, "target_ratio", 0.5))
        if not (0.0 < self._target_ratio < 1.0):
            raise ValueError(f"target_ratio 必须在 (0,1) 内, 当前={self._target_ratio}")

        self._vol_short_window = int(getattr(config, "vol_short_window", 60))
        self._vol_long_window = int(getattr(config, "vol_long_window", 1440))
        self._vol_ewma_alpha = float(getattr(config, "vol_ewma_alpha", 0.05))
        self._regime_spike_threshold = float(getattr(config, "regime_spike_threshold", 1.5))
        self._regime_crush_threshold = float(getattr(config, "regime_crush_threshold", 0.5))

        self._vol_k_factor = float(getattr(config, "vol_k_factor", 1.0))
        self._width_multiplier_spike = float(getattr(config, "width_multiplier_spike", 1.5))
        self._width_multiplier_crush = float(getattr(config, "width_multiplier_crush", 0.8))
        self._min_grid_width_bps = float(getattr(config, "min_grid_width_bps", 1.0))
        if self._min_grid_width_bps <= 0:
            raise ValueError(f"min_grid_width_bps 必须 > 0, 当前={self._min_grid_width_bps}")

        self._grid_layers = int(getattr(config, "grid_layers", 3))
        self._min_qty = float(getattr(config, "min_qty", 0.007))
        self._force_order_band = float(getattr(config, "force_order_band", 0.1))

        # 杠杆解析：得到逐笔杠杆 Z（用于 CPRP 目标仓位名义）
        leverage_spec = resolve_leverage_spec(
            config,
            target_ratio=self._target_ratio,
            max_position_leverage=getattr(config, "max_position_leverage", None),
        )
        self._position_leverage_z = float(leverage_spec.position_leverage)

        # 波动率递推状态（实盘/回测同口径）
        self._状态 = _波动率递推状态(
            vol_short_window=self._vol_short_window,
            vol_long_window=self._vol_long_window,
            short_buf=np.zeros(self._vol_short_window, dtype=np.float64),
            long_buf=np.zeros(self._vol_long_window, dtype=np.float64),
        )

        # CPRP 目标挂单数组（复用，减少每分钟的内存抖动）
        self._buy_prices = np.zeros(self._grid_layers, dtype=np.float64)
        self._buy_qtys = np.zeros(self._grid_layers, dtype=np.float64)
        self._sell_prices = np.zeros(self._grid_layers, dtype=np.float64)
        self._sell_qtys = np.zeros(self._grid_layers, dtype=np.float64)

    # ====== 策略接口 ======

    @property
    def 策略名称(self) -> str:
        return "8号香农策略（CPRP）"

    def 预热收盘价(self, 收盘价: float) -> None:
        """
        用历史收盘价预热状态（实盘启动时很有用）。

        说明：
            预热的目的是让 EWMA/波动率在一开始就“有记忆”，避免刚启动时宽度乱跳。
        """
        price = float(收盘价)
        if price <= 0:
            return
        if self._状态.prev_price <= 0:
            self._状态.prev_price = price
            return

        self._推进波动率状态(price)

    def 在K线收盘(self, k线: K线, 账户: 账户状态) -> 策略输出:
        # Guard Clauses：先把不合理输入挡住（绝不吞错）
        if k线.收 <= 0:
            return 策略输出(目标挂单=[], 备注={"跳过原因": "收盘价<=0"})
        if 账户.账户权益 <= 0:
            return 策略输出(目标挂单=[], 备注={"跳过原因": "账户权益<=0"})

        # 1) 更新“波动率/状态机”（递推，同口径）
        if self._状态.prev_price <= 0:
            self._状态.prev_price = float(k线.收)
        else:
            self._推进波动率状态(float(k线.收))

        # 2) 用最新状态算宽度 + 中心价
        width = self._计算网格宽度()
        center_price = self._计算中心价(float(k线.收))

        # 3) 计算 CPRP 多层挂单（写入数组）
        _计算_cprp_多层挂单(
            center_price,
            float(账户.持仓数量),
            float(账户.账户权益),
            float(width),
            int(self._grid_layers),
            float(self._min_qty),
            float(self._force_order_band),
            float(self._position_leverage_z),
            float(self._target_ratio),
            self._buy_prices,
            self._buy_qtys,
            self._sell_prices,
            self._sell_qtys,
        )

        post_only = bool(getattr(self._config, "post_only", False))

        目标挂单: list[限价挂单] = []
        for i in range(self._grid_layers):
            qty = float(self._buy_qtys[i])
            if qty > 0:
                目标挂单.append(
                    限价挂单(
                        交易对=账户.交易对 or self._symbol,
                        方向=订单方向.买,
                        价格=float(self._buy_prices[i]),
                        数量=qty,
                        只做挂单=post_only,
                    )
                )

        for i in range(self._grid_layers):
            qty = float(self._sell_qtys[i])
            if qty > 0:
                目标挂单.append(
                    限价挂单(
                        交易对=账户.交易对 or self._symbol,
                        方向=订单方向.卖,
                        价格=float(self._sell_prices[i]),
                        数量=qty,
                        只做挂单=post_only,
                    )
                )

        备注: dict[str, Any] = {
            "close": float(k线.收),
            "center_price": float(center_price),
            "grid_width": float(width),
            "regime_code": int(self._状态.regime),
            "regime": self._regime名称(self._状态.regime),
            "ewma_vol": float(self._状态.ewma_vol),
            "ewma_price": float(self._状态.ewma_price),
            "target_ratio": float(self._target_ratio),
            "position_leverage_z": float(self._position_leverage_z),
        }

        return 策略输出(目标挂单=目标挂单, 备注=备注)

    def 在成交回报(self, 回报: 成交回报) -> None:
        # 当前版本：策略脑子不依赖成交回报维持状态（执行器自己管订单/仓位）。
        # 未来如果要做“更精细的补单/风控”，可以在这里接入。
        return

    # ====== 内部工具 ======

    def _推进波动率状态(self, price: float) -> None:
        s = self._状态
        (
            s.prev_price,
            s.total_returns,
            s.short_pos,
            s.long_pos,
            s.short_count,
            s.long_count,
            s.short_sum,
            s.short_sumsq,
            s.long_sum,
            s.long_sumsq,
            s.ewma_vol,
            s.ewma_price,
            s.regime,
        ) = _波动率引擎_更新一次(
            float(price),
            float(s.prev_price),
            int(s.total_returns),
            s.short_buf,
            s.long_buf,
            int(s.short_pos),
            int(s.long_pos),
            int(s.short_count),
            int(s.long_count),
            float(s.short_sum),
            float(s.short_sumsq),
            float(s.long_sum),
            float(s.long_sumsq),
            int(self._vol_short_window),
            int(self._vol_long_window),
            float(self._vol_ewma_alpha),
            float(s.ewma_vol),
            float(s.ewma_price),
            float(self._regime_spike_threshold),
            float(self._regime_crush_threshold),
            int(s.regime),
        )

    def _计算网格宽度(self) -> float:
        base_width = float(self._状态.ewma_vol) * float(self._vol_k_factor)
        multiplier = 1.0
        if int(self._状态.regime) == 1:
            multiplier = float(self._width_multiplier_spike)
        elif int(self._状态.regime) == 2:
            multiplier = float(self._width_multiplier_crush)

        width = base_width * multiplier
        min_width = float(self._min_grid_width_bps) / 10000.0
        if width < min_width:
            width = min_width
        return float(width)

    def _计算中心价(self, last_close: float) -> float:
        if float(self._状态.ewma_price) > 0:
            return 0.5 * float(last_close) + 0.5 * float(self._状态.ewma_price)
        return float(last_close)

    @staticmethod
    def _regime名称(regime_code: int) -> str:
        if int(regime_code) == 1:
            return "SPIKE"
        if int(regime_code) == 2:
            return "CRUSH"
        return "NORMAL"

