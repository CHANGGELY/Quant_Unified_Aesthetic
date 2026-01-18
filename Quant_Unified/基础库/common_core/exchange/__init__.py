# -*- coding: utf-8 -*-
"""
common_core.exchange - 交易所访问与连接的公共层

这个包是干嘛的？
    这里放“跟交易所打交道”的通用组件，例如：
    - REST 客户端（普通 HTTP 请求）
    - WebSocket 管理器（长连接：像电话不挂断，交易所主动推送事件）

为什么要集中到 common_core？
    因为这些东西属于“基础设施”，一旦写错，所有策略都会受影响。
"""

from .binance_ws_manager import BinanceWsManager, ListenKeyProvider

__all__ = [
    "BinanceWsManager",
    "ListenKeyProvider",
]

