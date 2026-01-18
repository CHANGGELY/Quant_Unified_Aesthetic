# -*- coding: utf-8 -*-
"""
strategy_brain.py - 7号 VWAP 策略的“脑子”（只输出目标仓位）

策略核心（用人话）：
    - VWAP：成交量加权平均价，像“这段时间大家平均的成交成本”
    - 收盘价 > VWAP：偏多
    - 收盘价 < VWAP：偏空

关键：避免看未来（Look-ahead Bias）
    回测里你必须等一根 K 线“收盘”才知道 close 的值，
    所以信号要延迟 1 根 K 线执行：
        本根收盘算出信号 -> 下一根才按这个信号调仓
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from 基础库.common_core.strategy import (
    K线,
    账户状态,
    仓位方向,
    目标仓位,
    策略输出,
    策略接口,
)


@dataclass(slots=True)
class _VWAP递推状态:
    window: int
    quote_buf: np.ndarray
    vol_buf: np.ndarray
    pos: int = 0
    count: int = 0
    sum_quote: float = 0.0
    sum_vol: float = 0.0
    上一根信号: 仓位方向 = 仓位方向.空仓


class 七号VWAP策略脑子(策略接口):
    def __init__(self, config):
        self._config = config
        self._symbol = str(getattr(config, "symbol", "ETHUSDT") or "ETHUSDT").upper().strip()

        window = int(getattr(config, "vwap_window", 1200))
        if window <= 0:
            raise ValueError(f"vwap_window 必须 > 0, 当前={window}")

        self._杠杆 = float(getattr(config, "leverage", 1.0) or 1.0)
        if self._杠杆 < 0:
            raise ValueError("leverage 必须 >= 0")

        self._状态 = _VWAP递推状态(
            window=window,
            quote_buf=np.zeros(window, dtype=np.float64),
            vol_buf=np.zeros(window, dtype=np.float64),
        )

    @property
    def 策略名称(self) -> str:
        return "7号VWAP策略"

    def 在K线收盘(self, k线: K线, 账户: 账户状态) -> 策略输出:
        close = float(k线.收)
        vol = float(k线.成交量)
        if close <= 0:
            return 策略输出(目标仓位=目标仓位(交易对=账户.交易对 or self._symbol, 方向=仓位方向.空仓, 名义杠杆=0.0))
        if vol < 0:
            vol = 0.0

        s = self._状态
        quote = close * vol

        if s.count < s.window:
            s.quote_buf[s.pos] = quote
            s.vol_buf[s.pos] = vol
            s.sum_quote += quote
            s.sum_vol += vol
            s.count += 1
            s.pos = (s.pos + 1) % s.window
        else:
            old_q = float(s.quote_buf[s.pos])
            old_v = float(s.vol_buf[s.pos])
            s.sum_quote += quote - old_q
            s.sum_vol += vol - old_v
            s.quote_buf[s.pos] = quote
            s.vol_buf[s.pos] = vol
            s.pos = (s.pos + 1) % s.window

        vwap = close
        if s.sum_vol > 0:
            vwap = float(s.sum_quote / s.sum_vol)

        # 本根信号（用于下一根执行）
        if close > vwap:
            本根信号 = 仓位方向.多
        elif close < vwap:
            本根信号 = 仓位方向.空
        else:
            本根信号 = 仓位方向.空仓

        # 输出：执行“上一根信号”（延迟 1 根K线，避免看未来）
        执行方向 = s.上一根信号
        s.上一根信号 = 本根信号

        名义杠杆 = 0.0 if 执行方向 == 仓位方向.空仓 else float(self._杠杆)
        return 策略输出(
            目标仓位=目标仓位(
                交易对=账户.交易对 or self._symbol,
                方向=执行方向,
                名义杠杆=名义杠杆,
            ),
            备注={
                "close": close,
                "vwap": float(vwap),
                "signal_now": str(本根信号.value),
                "signal_exec": str(执行方向.value),
            },
        )

    def 在成交回报(self, 回报) -> None:
        # VWAP 信号只依赖价格序列，不依赖成交回报。
        return

