# -*- coding: utf-8 -*-
"""
common_core.strategy.live_executors - 实盘执行器（把策略输出变成真实下单）

这个文件是干嘛的？
    你可以把量化系统想成一个机器人：
    - 策略（脑子）：只负责“想”——看到行情后，输出“目标仓位/目标挂单”
    - 执行器（手脚）：只负责“做”——去交易所真正下单、撤单、同步账户、做风控

    回测执行器我们已经有了（K线撮合/盘口撮合）。
    这个文件补齐“实盘执行器”，用于真实交易所。

术语解释（遇到缩写必须展开）：
    - REST：普通 HTTP 请求（像“你发一条消息问一次”，一问一答）
    - WebSocket（长连接）：像“电话不挂断”，交易所主动推送事件（更实时、也更省请求）
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np

from .models import 账户状态, 策略输出, 目标仓位, 仓位方向


def _按步进截断(raw_qty: float, step: float) -> float:
    if step <= 0:
        raise ValueError("step 必须 > 0")
    lots = float(np.floor(abs(raw_qty) / step))
    return float(np.sign(raw_qty) * lots * step)


def _lazy_binance_raw():
    """
    延迟导入（lazy import），避免：
        - 仅 import common_core.strategy 时就触发 binance_raw 的环境检测日志
        - 单元测试跑离线测试时被 API Key 警告刷屏
    """
    from common_core.exchange import binance_raw as api  # noqa: WPS433（项目内约定：允许延迟导入）

    return api


@dataclass(slots=True)
class 实盘调仓统计:
    调仓次数: int = 0
    成交额: float = 0.0
    交易成本: float = 0.0


class 币安USDM目标仓位执行器:
    """
    币安 U 本位合约（USDⓈ-M Futures）目标仓位执行器

    适用场景：
        - MACD/VWAP/预测策略这类“输出目标仓位（多/空/空仓）”的策略

    核心思想：
        - 策略输出“方向 + 名义杠杆”
        - 执行器根据账户权益与最新价格，计算目标持仓数量
        - 用市价单把当前仓位“推到目标仓位”

    注意（非常重要）：
        市价单会吃点差 + 可能有滑点（这就是你在回测里需要扣 fee/slippage 的原因）。
    """

    def __init__(
        self,
        *,
        交易对: str,
        权益计价币: str = "USDT",
        数量步进: float,
        最小下单名义: float,
        最小下单间隔_s: float = 1.0,
    ) -> None:
        self._交易对 = str(交易对).upper().strip()
        self._权益计价币 = str(权益计价币).upper().strip()

        self._数量步进 = float(数量步进)
        if self._数量步进 <= 0:
            raise ValueError("数量步进 必须 > 0")

        self._最小下单名义 = float(最小下单名义)
        if self._最小下单名义 < 0:
            raise ValueError("最小下单名义 必须 >= 0")

        self._最小下单间隔_s = float(最小下单间隔_s)
        if self._最小下单间隔_s <= 0:
            raise ValueError("最小下单间隔_s 必须 > 0")

        self._最新_bid1 = 0.0
        self._最新_ask1 = 0.0
        self._最新时间_ms: int | None = None

        # 账户缓存（从 REST 同步）
        self._账户权益 = 0.0
        self._可用余额 = 0.0
        self._持仓数量 = 0.0
        self._持仓均价 = 0.0
        self._未实现盈亏 = 0.0

        self._上次下单时间 = 0.0
        self._统计 = 实盘调仓统计()

    # =========================
    # 行情/账户同步
    # =========================

    def 更新盘口(self, *, 时间_ms: int, bid1: float, ask1: float) -> None:
        bid1 = float(bid1)
        ask1 = float(ask1)
        if bid1 > 0:
            self._最新_bid1 = bid1
        if ask1 > 0:
            self._最新_ask1 = ask1
        self._最新时间_ms = int(时间_ms)

    def 同步账户状态(self) -> None:
        api = _lazy_binance_raw()
        data = api.fetch_account_status(self._权益计价币, self._交易对)
        if not data:
            raise RuntimeError("fetch_account_status 返回空，无法同步账户状态（请检查 API Key/网络/权限）")

        self._账户权益 = float(data.get("wallet_balance", 0.0) or 0.0) + float(data.get("unrealized_pnl", 0.0) or 0.0)
        self._可用余额 = float(data.get("available_balance", 0.0) or 0.0)
        self._持仓数量 = float(data.get("position_amt", 0.0) or 0.0)
        self._持仓均价 = float(data.get("position_entry", 0.0) or 0.0)
        self._未实现盈亏 = float(data.get("position_unPnl", 0.0) or 0.0)

    def 获取账户状态(self) -> 账户状态:
        return 账户状态(
            交易对=self._交易对,
            账户权益=float(self._账户权益),
            可用余额=float(self._可用余额),
            持仓数量=float(self._持仓数量),
            持仓均价=float(self._持仓均价),
            未实现盈亏=float(self._未实现盈亏),
        )

    # =========================
    # 执行策略输出
    # =========================

    def 执行策略输出(self, 输出: 策略输出) -> None:
        目标 = 输出.目标仓位
        if 目标 is None:
            return

        now = time.time()
        if now - self._上次下单时间 < self._最小下单间隔_s:
            return

        mid = self._计算中间价()
        if mid <= 0.0:
            return

        # 用最新账户权益计算目标数量（更贴近“实时资金规模”）
        if self._账户权益 <= 0:
            self.同步账户状态()
        equity = float(self._账户权益)
        if equity <= 0:
            return

        目标 = self._归一化目标仓位(目标)
        目标数量 = self._计算目标数量(目标=目标, 账户权益=equity, mid_price=mid)

        delta = float(目标数量 - self._持仓数量)
        if abs(delta) <= 1e-12:
            return

        # 最小名义过滤（避免下不出去的小单）
        if abs(delta) * mid < self._最小下单名义:
            return

        side = "BUY" if delta > 0 else "SELL"
        qty = abs(delta)

        api = _lazy_binance_raw()
        api.place_market_order(self._交易对, side, qty)

        self._上次下单时间 = now
        self._统计.调仓次数 += 1
        self._统计.成交额 += float(qty * mid)

        # 下完单立刻同步一次（保证策略下一轮看到的账户是新的）
        self.同步账户状态()

    def 获取调仓统计(self) -> 实盘调仓统计:
        return self._统计

    # =========================
    # 内部工具
    # =========================

    def _计算中间价(self) -> float:
        bid1 = float(self._最新_bid1)
        ask1 = float(self._最新_ask1)
        if bid1 > 0.0 and ask1 > 0.0:
            return float((bid1 + ask1) * 0.5)
        return float(max(bid1, ask1, 0.0))

    def _归一化目标仓位(self, 目标: 目标仓位) -> 目标仓位:
        方向 = 目标.方向
        if 方向 not in (仓位方向.多, 仓位方向.空, 仓位方向.空仓):
            方向 = 仓位方向.空仓
        名义杠杆 = float(目标.名义杠杆)
        if not math.isfinite(名义杠杆) or 名义杠杆 < 0:
            名义杠杆 = 0.0
        return 目标仓位(交易对=self._交易对, 方向=方向, 名义杠杆=名义杠杆)

    def _计算目标数量(self, *, 目标: 目标仓位, 账户权益: float, mid_price: float) -> float:
        if 目标.方向 == 仓位方向.空仓 or 目标.名义杠杆 <= 0:
            return 0.0
        sign = 1.0 if 目标.方向 == 仓位方向.多 else -1.0
        target_notional = float(账户权益) * float(目标.名义杠杆)
        raw_qty = sign * (target_notional / float(mid_price))
        return float(_按步进截断(raw_qty, self._数量步进))

