# -*- coding: utf-8 -*-
"""
4号做市策略 - 策略脑子（策略接口版）

这个文件是干嘛的？
    把“做市策略”的核心决策逻辑，做成统一接口：
        - 输入：K线 + 账户状态（含多头/空头）
        - 输出：一组对冲模式挂单（开多、开空、平多、平空）

核心思想（用人话解释）：
    你可以把做市理解成“摆摊”：
        - 你在摊位左边挂一个“收购价”（买单）
        - 在摊位右边挂一个“出售价”（卖单）
    价格来回波动时：
        - 有人把货卖给你，你低价买到（开多）
        - 有人从你这买走，你高价卖出（开空）
    然后你再挂更远一点的“平仓单”去锁利润。

术语解释：
    - 对冲模式（Hedge Mode）：同一标的可以同时有多头(LONG)和空头(SHORT)，互不冲掉。
    - ATR（Average True Range，平均真实波幅）：衡量“最近波动有多大”的指标，用来动态调价差。
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import deque

from 基础库.common_core.strategy import K线, 账户状态, 成交回报, 仓位方向, 策略输出, 限价挂单, 订单方向

from config_backtest_interface import 四号做市回测配置


@dataclass(slots=True)
class _ATR监控器:
    """
    简化 ATR 监控器（只做均值，不做复杂加权）
    """

    周期: int
    _tr队列: deque[float]
    _上次收盘: float | None = None

    def __init__(self, 周期: int) -> None:
        self.周期 = int(周期)
        self._tr队列 = deque(maxlen=max(2, int(周期)))
        self._上次收盘 = None

    def 更新(self, *, high: float, low: float, close: float) -> None:
        if self._上次收盘 is None:
            self._上次收盘 = float(close)
            return

        prev_close = float(self._上次收盘)
        h = float(high)
        l = float(low)
        c = float(close)

        tr1 = h - l
        tr2 = abs(h - prev_close)
        tr3 = abs(l - prev_close)
        tr = max(tr1, tr2, tr3)

        if tr >= 0.0:
            self._tr队列.append(float(tr))
        self._上次收盘 = c

    def 获取_atr_pct(self, 当前价: float) -> float:
        if not self._tr队列:
            return 0.0
        if 当前价 <= 0:
            return 0.0
        atr = sum(self._tr队列) / len(self._tr队列)
        return float(atr / float(当前价))


class 四号做市策略脑子:
    策略名称 = "4号做市策略"

    def __init__(self, 配置: 四号做市回测配置 | dict) -> None:
        if isinstance(配置, 四号做市回测配置):
            self._cfg = 配置
        else:
            self._cfg = 四号做市回测配置(**dict(配置))

        self._atr = _ATR监控器(self._cfg.atr_period)

    def 在K线收盘(self, k线: K线, 账户: 账户状态) -> 策略输出:
        mid = float(k线.收)
        if mid <= 0:
            return 策略输出()

        self._atr.更新(high=float(k线.高), low=float(k线.低), close=float(k线.收))

        bid_spread, ask_spread = self._计算自适应价差(mid)

        bid = mid * (1.0 - bid_spread)
        ask = mid * (1.0 + ask_spread)

        long_pos = float(getattr(账户, "多头持仓数量", 0.0) or 0.0)
        short_pos = float(getattr(账户, "空头持仓数量", 0.0) or 0.0)
        equity = float(getattr(账户, "账户权益", 0.0) or 0.0)

        # ====== 动态最大仓位限制（总持仓名义）======
        max_pos_value = max(0.0, equity * float(self._cfg.leverage) * float(self._cfg.max_position_value_ratio))
        total_pos_value = (long_pos + short_pos) * mid

        # 单边限制：简单按 50% 分摊
        max_side_pos = (max_pos_value / mid) * 0.5 if mid > 0 else 0.0

        # ====== 动态下单量 ======
        open_qty = self._计算动态下单量(mid, equity)
        close_qty = open_qty

        # ====== post-only 价格微调（让挂单更“像挂单”）======
        post_only = bool(self._cfg.post_only)
        tick = float(self._cfg.tick_size)
        off_buy = int(self._cfg.post_only_tick_offset_buy)
        off_sell = int(self._cfg.post_only_tick_offset_sell)

        buy_price = bid - tick * off_buy if post_only else bid
        sell_price = ask + tick * off_sell if post_only else ask

        # 平仓价格：比开仓再多跨一格（更像做市“赚价差”）
        close_long_price = (ask * (1.0 + ask_spread)) + (tick * off_sell if post_only else 0.0)
        close_short_price = (bid * (1.0 - bid_spread)) - (tick * off_buy if post_only else 0.0)

        目标挂单: list[限价挂单] = []

        # ====== 开仓挂单：开多 / 开空 ======
        if total_pos_value <= max_pos_value and open_qty > 0.0:
            if long_pos < max_side_pos - 1e-12:
                目标挂单.append(
                    限价挂单(
                        交易对=self._cfg.symbol,
                        方向=订单方向.买,
                        价格=float(buy_price),
                        数量=float(open_qty),
                        只做挂单=post_only,
                        只减仓=False,
                        仓位方向=仓位方向.多,
                    )
                )
            if short_pos < max_side_pos - 1e-12:
                目标挂单.append(
                    限价挂单(
                        交易对=self._cfg.symbol,
                        方向=订单方向.卖,
                        价格=float(sell_price),
                        数量=float(open_qty),
                        只做挂单=post_only,
                        只减仓=False,
                        仓位方向=仓位方向.空,
                    )
                )

        # ====== 平仓挂单：平多 / 平空（只减仓）======
        if long_pos > 0.0 and close_qty > 0.0:
            目标挂单.append(
                限价挂单(
                    交易对=self._cfg.symbol,
                    方向=订单方向.卖,
                    价格=float(close_long_price),
                    数量=float(min(close_qty, long_pos)),
                    只做挂单=post_only,
                    只减仓=True,
                    仓位方向=仓位方向.多,
                )
            )
        if short_pos > 0.0 and close_qty > 0.0:
            目标挂单.append(
                限价挂单(
                    交易对=self._cfg.symbol,
                    方向=订单方向.买,
                    价格=float(close_short_price),
                    数量=float(min(close_qty, short_pos)),
                    只做挂单=post_only,
                    只减仓=True,
                    仓位方向=仓位方向.空,
                )
            )

        return 策略输出(
            目标挂单=目标挂单,
            备注={
                "symbol": self._cfg.symbol,
                "bid_spread": float(bid_spread),
                "ask_spread": float(ask_spread),
                "atr_pct": float(self._atr.获取_atr_pct(mid)),
                "mid": float(mid),
            },
        )

    def 在成交回报(self, 回报: 成交回报) -> None:
        # 当前版本不需要用成交来更新内部状态（执行器会维护仓位/权益）
        _ = 回报
        return

    # =========================
    # 内部工具
    # =========================

    def _计算动态下单量(self, 当前价: float, 账户权益: float) -> float:
        if 当前价 <= 0:
            return 0.0
        if not bool(self._cfg.use_dynamic_order_size):
            return float(self._cfg.min_order_amount)

        effective_leverage = max(1.0, float(self._cfg.leverage))
        position_ratio = 1.0 / effective_leverage

        order_value = float(账户权益) * position_ratio
        qty = order_value / 当前价

        min_amount = max(float(self._cfg.min_order_amount), float(账户权益) / 1000.0 / 当前价)
        max_amount = float(self._cfg.max_order_amount)

        return float(max(min_amount, min(max_amount, qty)))

    def _计算自适应价差(self, 当前价: float) -> tuple[float, float]:
        base_bid = float(self._cfg.bid_spread)
        base_ask = float(self._cfg.ask_spread)

        if not bool(self._cfg.enable_volatility_adaptive):
            return base_bid, base_ask

        atr_pct = float(self._atr.获取_atr_pct(float(当前价)))
        if atr_pct <= 0:
            return base_bid, base_ask

        high = float(self._cfg.high_volatility_threshold)
        extreme = float(self._cfg.extreme_volatility_threshold)

        if atr_pct >= extreme:
            m = float(self._cfg.max_spread_multiplier)
        elif atr_pct >= high:
            m = float(self._cfg.spread_adjustment_factor)
        else:
            m = 1.0

        return base_bid * m, base_ask * m
