# -*- coding: utf-8 -*-
"""
strategy_brain.py - 6号 MACD 策略的“脑子”（只输出目标仓位）

这个文件是干嘛的？
    把 6 号策略改造成“策略脑子 + 执行器”的统一形态：
      - 脑子：只负责算信号 -> 输出“我想做多/做空/空仓 + 用多大杠杆”
      - 执行器：负责撮合成交、扣手续费/滑点、以及最关键的爆仓检测

为什么要这样拆？
    你可以把量化系统想成“机器人”：
      - 脑子负责想
      - 手脚负责做
    脑子如果自己还负责“成交/扣费/爆仓”，就会导致回测和实盘越写越分叉。

MACD 是什么？（用人话）
    MACD（Moving Average Convergence Divergence：指数均线的“收敛/发散”）本质是在看：
      - 快线（更敏感的平均价）和慢线（更迟钝的平均价）谁在上面
    当快线从下往上穿过慢线，常叫“金叉” -> 偏多
    当快线从上往下穿过慢线，常叫“死叉” -> 偏空

实现细节（为什么这样写）
    pandas 的 ewm(adjust=False) 用的是“递推EMA”：
      EMA_t = α * price_t + (1-α) * EMA_{t-1}
    这样才能做到“实盘每来一根 K 线就更新一次”，而不是每次重算全历史。
"""

from __future__ import annotations

from dataclasses import dataclass

from 基础库.common_core.strategy import (
    K线,
    账户状态,
    仓位方向,
    目标仓位,
    策略输出,
    策略接口,
)


@dataclass(slots=True)
class _MACD递推状态:
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    dea: float = 0.0
    prev_diff: float = 0.0
    inited: bool = False


class 六号MACD策略脑子(策略接口):
    def __init__(self, config):
        self._config = config

        self._symbol = str(getattr(config, "symbol", "ETHUSDT") or "ETHUSDT").upper().strip()

        self._fast = int(getattr(config, "macd_fast", 12))
        self._slow = int(getattr(config, "macd_slow", 26))
        self._signal = int(getattr(config, "macd_signal", 9))
        if self._fast <= 0 or self._slow <= 0 or self._signal <= 0:
            raise ValueError("MACD 参数必须为正整数")
        if self._fast >= self._slow:
            raise ValueError("macd_fast 必须小于 macd_slow（不然快慢线就没意义）")

        # pandas ewm(span=...).mean(adjust=False) 的 α
        self._a_fast = 2.0 / (self._fast + 1.0)
        self._a_slow = 2.0 / (self._slow + 1.0)
        self._a_sig = 2.0 / (self._signal + 1.0)

        # 默认杠杆：如果 config 没给，就用 1.0（不加杠杆）
        self._默认名义杠杆 = float(getattr(config, "leverage", 1.0) or 1.0)
        if self._默认名义杠杆 < 0:
            raise ValueError("leverage 必须 >= 0")

        self._方向: 仓位方向 = 仓位方向.空仓
        self._状态 = _MACD递推状态()

    @property
    def 策略名称(self) -> str:
        return "6号MACD策略"

    def 在K线收盘(self, k线: K线, 账户: 账户状态) -> 策略输出:
        price = float(k线.收)
        if price <= 0:
            return 策略输出(目标仓位=目标仓位(交易对=账户.交易对 or self._symbol, 方向=仓位方向.空仓, 名义杠杆=0.0))

        s = self._状态
        if not s.inited:
            s.ema_fast = price
            s.ema_slow = price
            dif = 0.0
            s.dea = 0.0
            diff = 0.0
            s.prev_diff = 0.0
            s.inited = True
        else:
            s.ema_fast = self._a_fast * price + (1.0 - self._a_fast) * s.ema_fast
            s.ema_slow = self._a_slow * price + (1.0 - self._a_slow) * s.ema_slow
            dif = s.ema_fast - s.ema_slow
            s.dea = self._a_sig * dif + (1.0 - self._a_sig) * s.dea
            diff = dif - s.dea

        # 金叉/死叉判断（用 diff 过零）
        if diff > 0.0 and s.prev_diff <= 0.0:
            self._方向 = 仓位方向.多
        elif diff < 0.0 and s.prev_diff >= 0.0:
            self._方向 = 仓位方向.空
        # 否则保持原方向（持有到反向信号出现）

        s.prev_diff = diff

        目标方向 = self._方向
        杠杆 = 0.0 if 目标方向 == 仓位方向.空仓 else float(self._默认名义杠杆)

        return 策略输出(
            目标仓位=目标仓位(
                交易对=账户.交易对 or self._symbol,
                方向=目标方向,
                名义杠杆=杠杆,
            ),
            备注={
                "close": price,
                "ema_fast": float(s.ema_fast),
                "ema_slow": float(s.ema_slow),
                "dif": float(dif),
                "dea": float(s.dea),
                "diff": float(diff),
                "direction": str(目标方向.value),
            },
        )

    def 在成交回报(self, 回报) -> None:
        # 6号 MACD 策略的脑子不依赖成交回报维持指标状态（只看价格序列）。
        return

