# -*- coding: utf-8 -*-
"""
common_core.strategy.interfaces - “插座标准”：策略和执行器怎么对接

这个文件是干嘛的？
    如果每个策略都用不同的函数签名（参数/返回值），那回测/实盘执行环境就没法复用。
    所以这里定义“接口（Interface）”：
    - 策略接口：策略必须提供哪些能力
    - 执行器接口：执行环境必须提供哪些能力

接口你可以理解成“插座标准”：
    - 只要插头（策略）遵守标准
    - 不同国家（回测/实盘/不同交易所）的插座（执行器）都能插

术语解释：
    - Protocol（协议接口）：Python 的一种“软接口”，不强制继承，但会做类型检查（更灵活）。
"""

from __future__ import annotations

from typing import Protocol

from .models import K线, 账户状态, 成交回报, 策略输出


class 策略接口(Protocol):
    """
    策略接口：策略的“最小可用能力”
    """

    @property
    def 策略名称(self) -> str:  # pragma: no cover
        ...

    def 在K线收盘(self, k线: K线, 账户: 账户状态) -> 策略输出:  # pragma: no cover
        """
        输入：
            - 一根已收盘的 K 线（1m 或更大周期）
            - 当前账户状态（余额、持仓等）

        输出：
            - 本次决策想挂的目标挂单（不直接下单）
        """
        ...

    def 在成交回报(self, 回报: 成交回报) -> None:  # pragma: no cover
        """
        当交易所推送成交回报时，策略可以用它来更新内部状态（可选实现）。
        """
        ...


class 执行器接口(Protocol):
    """
    执行器接口：执行环境的“最小可用能力”

    回测执行器/实盘执行器都会实现它。
    """

    def 获取账户状态(self) -> 账户状态:  # pragma: no cover
        ...

    def 执行策略输出(self, 输出: 策略输出) -> None:  # pragma: no cover
        """
        把策略输出变成真实动作：
        - 回测：撮合成交、更新账户
        - 实盘：下单/撤单、等待 WebSocket 成交推送
        """
        ...

