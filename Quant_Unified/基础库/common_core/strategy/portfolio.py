# -*- coding: utf-8 -*-
"""
common_core.strategy.portfolio - 组合级（多交易对/多策略）执行器“地基”

你现在的目标架构是“脑子 + 手脚”分离：
    - 策略（脑子）：只负责输出“我想怎么做”（目标仓位/目标挂单）
    - 执行器（手脚）：只负责把输出变成真实动作（回测撮合/实盘下单）+ 风控

那“组合级执行器”是什么？
    单标的执行器只看一个币（例如只看 BTCUSDT）；
    组合级执行器要同时看多个币/多个策略，把它们当成“一个账户”来管理：
    - 账户权益是共享的（同一个钱包）
    - 风险是共享的（多个仓位一起决定是否爆仓）

为什么爆仓逻辑必须上组合级？
    你可以把它想成“一个人同时背了好几笔贷款”：
    - 单看某一笔贷款可能没问题
    - 但所有贷款加起来就可能把你压垮
    在量化回测里同理：多个仓位的总名义（总敞口）太大时，账户会被爆掉。

本文件提供什么？
    1) 组合账户状态（把多个交易对的持仓打包成一个快照）
    2) 组合执行器接口（像“插座标准”一样）
    3) 一个最小可用的组合级调仓执行器（盘口/价格驱动，支持爆仓检查）

说明：
    - 资金费（Funding：永续合约的定期利息）/ 多币种保证金 这些未来可扩展，但本阶段先不强行上。
    - 本实现默认“同一计价币”（例如都用 USDT 计价），且用总名义做爆仓检查。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol

import numpy as np

from ..risk_ctrl.liquidation import LiquidationChecker
from .models import 盘口快照, 账户状态, 仓位方向, 策略输出, 目标仓位


@dataclass(frozen=True, slots=True)
class 组合账户状态:
    """
    组合账户状态（Portfolio Account Snapshot）

    设计原则：
        - 这是“快照”，给策略做决策用
        - 只包含策略常用的口径：权益、可用、各交易对持仓
    """

    账户权益: float
    可用余额: float
    各交易对账户: Mapping[str, 账户状态]
    备注: Mapping[str, Any] = MappingProxyType({})

    def 获取单品种(self, 交易对: str) -> 账户状态 | None:
        return self.各交易对账户.get(str(交易对).upper().strip())


class 组合执行器接口(Protocol):
    """
    组合执行器接口（组合级“手脚”）
    """

    def 获取组合账户状态(self) -> 组合账户状态:  # pragma: no cover
        ...

    def 获取单品种账户状态(self, 交易对: str) -> 账户状态:  # pragma: no cover
        ...

    def 执行策略输出(self, 输出: 策略输出) -> None:  # pragma: no cover
        ...


@dataclass(slots=True)
class 组合调仓统计:
    调仓次数: int = 0
    成交额: float = 0.0
    交易成本: float = 0.0


class 组合盘口调仓执行器(组合执行器接口):
    """
    组合盘口调仓执行器（Portfolio Rebalance Executor）

    适用场景：
        - 多策略/多交易对同时运行，但都输出“目标仓位”（多/空/空仓 + 名义杠杆）
        - 你希望爆仓检查按“组合总敞口”来算，而不是每个币各算各的

    口径说明（非常重要）：
        - 账户权益：会被 mark-to-market（按最新结算价逐步结算浮动盈亏）
        - 爆仓检查：用「账户权益 / 总持仓名义」与最小维持保证金率比较
        - 成交价：买用 ask、卖用 bid，并叠加滑点（更保守）
        - 手续费：成交额 * 手续费率
    """

    def __init__(
        self,
        *,
        初始资金: float,
        数量步进: float,
        手续费率: float,
        滑点率: float,
        最小下单名义: float = 0.0,
        最小维持保证金率: float = 0.005,
        结算价模式: str = "wmp",
    ) -> None:
        if 初始资金 < 0:
            raise ValueError("初始资金 必须 >= 0")
        if 数量步进 <= 0:
            raise ValueError("数量步进 必须 > 0")
        if 手续费率 < 0 or 滑点率 < 0:
            raise ValueError("手续费率/滑点率 必须 >= 0")
        if 最小下单名义 < 0:
            raise ValueError("最小下单名义 必须 >= 0")

        模式 = str(结算价模式 or "").strip().lower()
        if 模式 not in {"mid", "wmp"}:
            raise ValueError("结算价模式 只能是 mid/wmp")

        self._数量步进 = float(数量步进)
        self._手续费率 = float(手续费率)
        self._滑点率 = float(滑点率)
        self._最小下单名义 = float(最小下单名义)
        self._结算价模式 = 模式
        self._风控 = LiquidationChecker(min_margin_rate=float(最小维持保证金率))

        self._账户权益 = float(初始资金)
        self._最新时间_ms: int | None = None

        # 每个交易对的“行情/结算价”
        self._最新_bid1: dict[str, float] = {}
        self._最新_ask1: dict[str, float] = {}
        self._上次结算价: dict[str, float] = {}
        self._最新结算价: dict[str, float] = {}

        # 每个交易对的“持仓”
        self._持仓数量: dict[str, float] = {}
        self._持仓均价: dict[str, float] = {}

        self._统计 = 组合调仓统计()
        self._是否爆仓 = False
        self._爆仓时间_ms: int | None = None
        self._爆仓价格: float | None = None

    # =========================
    # 组合执行器接口
    # =========================

    def 获取组合账户状态(self) -> 组合账户状态:
        symbols = set(self._最新结算价) | set(self._持仓数量) | set(self._持仓均价)
        各交易对: dict[str, 账户状态] = {}

        for s in symbols:
            mark = float(self._最新结算价.get(s, 0.0) or 0.0)
            qty = float(self._持仓数量.get(s, 0.0) or 0.0)
            entry = float(self._持仓均价.get(s, 0.0) or 0.0)
            upnl = float(qty * (mark - entry)) if (qty != 0.0 and mark > 0.0 and entry > 0.0) else 0.0
            各交易对[s] = 账户状态(
                交易对=s,
                账户权益=float(self._账户权益),
                可用余额=float(self._账户权益),
                持仓数量=float(qty),
                持仓均价=float(entry),
                未实现盈亏=float(upnl),
            )

        return 组合账户状态(
            账户权益=float(self._账户权益),
            可用余额=float(self._账户权益),
            各交易对账户=MappingProxyType(各交易对),
            备注=MappingProxyType(
                {
                    "是否爆仓": bool(self._是否爆仓),
                    "爆仓时间_ms": self._爆仓时间_ms,
                    "爆仓价格": self._爆仓价格,
                }
            ),
        )

    def 获取单品种账户状态(self, 交易对: str) -> 账户状态:
        s = str(交易对).upper().strip()
        mark = float(self._最新结算价.get(s, 0.0) or 0.0)
        qty = float(self._持仓数量.get(s, 0.0) or 0.0)
        entry = float(self._持仓均价.get(s, 0.0) or 0.0)
        upnl = float(qty * (mark - entry)) if (qty != 0.0 and mark > 0.0 and entry > 0.0) else 0.0
        return 账户状态(
            交易对=s,
            账户权益=float(self._账户权益),
            可用余额=float(self._账户权益),
            持仓数量=float(qty),
            持仓均价=float(entry),
            未实现盈亏=float(upnl),
        )

    def 执行策略输出(self, 输出: 策略输出) -> None:
        if self._是否爆仓:
            return

        目标 = 输出.目标仓位
        if 目标 is None:
            return

        目标 = self._归一化目标仓位(目标)
        s = str(目标.交易对).upper().strip()
        if not s:
            return

        mark = float(self._最新结算价.get(s, 0.0) or 0.0)
        if mark <= 0.0:
            return

        # 1) 计算目标数量（组合共享权益）
        目标数量 = 0.0
        if 目标.方向 != 仓位方向.空仓 and 目标.名义杠杆 > 0:
            sign = 1.0 if 目标.方向 == 仓位方向.多 else -1.0
            目标名义 = float(self._账户权益) * float(目标.名义杠杆)
            raw_qty = sign * (目标名义 / mark)
            目标数量 = self._按步进截断(raw_qty)
            if abs(目标数量) * mark < self._最小下单名义:
                目标数量 = 0.0

        当前数量 = float(self._持仓数量.get(s, 0.0) or 0.0)
        delta = float(目标数量 - 当前数量)
        if abs(delta) <= 1e-12:
            return

        # 2) 成交价（买用 ask，卖用 bid）+ 滑点
        exec_p = self._计算执行价(交易对=s, delta_qty=delta, fallback_mark=mark)
        if exec_p <= 0.0:
            return

        turnover = abs(delta) * exec_p
        fee_cost = turnover * self._手续费率
        impact_cost = abs(delta) * abs(exec_p - mark)

        self._账户权益 -= float(fee_cost + impact_cost)
        self._统计.调仓次数 += 1
        self._统计.成交额 += float(turnover)
        self._统计.交易成本 += float(fee_cost + impact_cost)

        self._更新持仓(交易对=s, delta_qty=delta, exec_price=exec_p)

        # 3) 调仓后立即检查爆仓
        self._检查爆仓(self._最新时间_ms)

    def 获取调仓统计(self) -> 组合调仓统计:
        return self._统计

    @property
    def 是否爆仓(self) -> bool:
        return bool(self._是否爆仓)

    @property
    def 爆仓时间_ms(self) -> int | None:
        return self._爆仓时间_ms

    @property
    def 爆仓价格(self) -> float | None:
        return self._爆仓价格

    # =========================
    # 行情推进（盘口/价格结算）
    # =========================

    def 推进盘口快照结算(self, 快照: 盘口快照) -> None:
        """
        用一帧盘口快照做一次结算（mark-to-market）
        """
        s = str(快照.交易对).upper().strip()
        if not s:
            return

        bid1 = float(快照.买一价())
        ask1 = float(快照.卖一价())
        self._最新_bid1[s] = bid1
        self._最新_ask1[s] = ask1
        self._最新时间_ms = int(快照.时间_ms)

        mark = float(self._计算结算价(快照))
        if mark <= 0.0:
            return

        if self._是否爆仓:
            self._最新结算价[s] = mark
            self._上次结算价[s] = mark
            return

        prev = float(self._上次结算价.get(s, 0.0) or 0.0)
        qty = float(self._持仓数量.get(s, 0.0) or 0.0)
        if prev > 0.0 and qty != 0.0:
            self._账户权益 += (mark - prev) * qty

        self._上次结算价[s] = mark
        self._最新结算价[s] = mark

        self._检查爆仓(self._最新时间_ms)

    # =========================
    # 内部工具
    # =========================

    def _按步进截断(self, raw_qty: float) -> float:
        step = self._数量步进
        lots = float(np.floor(abs(raw_qty) / step))
        return float(np.sign(raw_qty) * lots * step)

    @staticmethod
    def _归一化目标仓位(目标: 目标仓位) -> 目标仓位:
        方向 = 目标.方向
        if 方向 not in (仓位方向.多, 仓位方向.空, 仓位方向.空仓):
            方向 = 仓位方向.空仓
        名义杠杆 = float(目标.名义杠杆)
        if not math.isfinite(名义杠杆) or 名义杠杆 < 0:
            名义杠杆 = 0.0
        return 目标仓位(交易对=str(目标.交易对).upper().strip(), 方向=方向, 名义杠杆=名义杠杆)

    def _计算结算价(self, 快照: 盘口快照) -> float:
        if self._结算价模式 == "wmp":
            return float(快照.计算加权中间价())
        return float(快照.计算中间价())

    def _计算执行价(self, *, 交易对: str, delta_qty: float, fallback_mark: float) -> float:
        bid1 = float(self._最新_bid1.get(交易对, 0.0) or 0.0)
        ask1 = float(self._最新_ask1.get(交易对, 0.0) or 0.0)

        if delta_qty > 0:
            base = ask1 if ask1 > 0.0 else fallback_mark
            return float(base * (1.0 + self._滑点率))
        base = bid1 if bid1 > 0.0 else fallback_mark
        return float(base * (1.0 - self._滑点率))

    def _更新持仓(self, *, 交易对: str, delta_qty: float, exec_price: float) -> None:
        s = str(交易对).upper().strip()
        prev_qty = float(self._持仓数量.get(s, 0.0) or 0.0)
        prev_entry = float(self._持仓均价.get(s, 0.0) or 0.0)

        new_qty = float(prev_qty + float(delta_qty))
        if abs(new_qty) <= 1e-12:
            self._持仓数量[s] = 0.0
            self._持仓均价[s] = 0.0
            return

        if abs(prev_qty) <= 1e-12:
            self._持仓数量[s] = float(new_qty)
            self._持仓均价[s] = float(exec_price)
            return

        prev_sign = 1.0 if prev_qty > 0 else -1.0
        new_sign = 1.0 if new_qty > 0 else -1.0
        if prev_sign != new_sign:
            self._持仓数量[s] = float(new_qty)
            self._持仓均价[s] = float(exec_price)
            return

        # 同方向加减仓：加权平均（减仓在严格意义上不该改均价，但此口径足够稳定且与单标的执行器一致）
        prev_val = abs(prev_qty) * float(prev_entry)
        delta_val = abs(delta_qty) * float(exec_price)
        total_qty = abs(new_qty)
        if total_qty > 0.0:
            self._持仓均价[s] = float((prev_val + delta_val) / total_qty)
        self._持仓数量[s] = float(new_qty)

    def _检查爆仓(self, 时间戳_ms: int | None) -> None:
        if self._是否爆仓:
            return
        if self._账户权益 <= 0.0:
            # 归零也算爆仓（防止继续交易）
            self._是否爆仓 = True
            self._爆仓时间_ms = int(时间戳_ms) if 时间戳_ms is not None else None
            self._爆仓价格 = None
            return

        total_pos_val = 0.0
        for s, qty in self._持仓数量.items():
            q = float(qty or 0.0)
            if abs(q) <= 1e-12:
                continue
            mark = float(self._最新结算价.get(s, 0.0) or 0.0)
            if mark <= 0.0:
                continue
            total_pos_val += abs(q) * mark

        is_liq, _ = self._风控.check_margin_rate(self._账户权益, total_pos_val)
        if not is_liq:
            return

        self._是否爆仓 = True
        self._爆仓时间_ms = int(时间戳_ms) if 时间戳_ms is not None else None
        # 爆仓价格用“总敞口最大”的那一腿作为代表（便于日志/可视化）
        worst_symbol = None
        worst_val = 0.0
        for s, qty in self._持仓数量.items():
            q = float(qty or 0.0)
            mark = float(self._最新结算价.get(s, 0.0) or 0.0)
            v = abs(q) * mark
            if v > worst_val:
                worst_val = v
                worst_symbol = s
        self._爆仓价格 = float(self._最新结算价.get(worst_symbol, 0.0) or 0.0) if worst_symbol else None

        # 统一处理：爆仓后账户归零（便于指标/可视化“立刻看到死掉”）
        self._账户权益 = 0.0
        for s in list(self._持仓数量.keys()):
            self._持仓数量[s] = 0.0
            self._持仓均价[s] = 0.0

