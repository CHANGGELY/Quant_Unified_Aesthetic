#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ws_manager.py - WebSocket（长连接）管理器（八号策略专用薄封装）

这个文件是干嘛的？
    早期每个策略都复制了一份 WebSocket 管理器代码，维护成本很高。
    现在我们把“通用 WebSocket 管理逻辑”抽到了公共层：
        common_core.exchange.binance_ws_manager.BinanceWsManager

    本文件只做两件事：
        1) 提供与旧代码完全兼容的类名/接口（避免大面积改 import）
        2) 注入八号策略自己的 API 实现（用于获取/续期 ListenKey）

术语解释：
    - WebSocket（长连接）：像“电话不挂断”，交易所会主动推送成交/行情
    - ListenKey（监听 Key）：用户数据流的“临时门票”，用来订阅你的订单成交推送
"""

from __future__ import annotations

from common_core.exchange import BinanceWsManager as _CoreBinanceWsManager
from common_core.exchange import ListenKeyProvider as _ListenKeyProvider

from 策略仓库.八号香农策略.api import binance_raw as api


class BinanceWsManager(_CoreBinanceWsManager):
    """
    向后兼容：保留旧的构造参数 market_stream_kind
    """

    def __init__(self, symbols=None, *, market_stream_kind: str = "kline_1m"):
        provider = _ListenKeyProvider(
            get_listen_key=api.get_listen_key,
            keep_alive_listen_key=api.keep_alive_listen_key,
        )
        super().__init__(
            symbols=symbols,
            market_stream_kind=str(market_stream_kind or "kline_1m").strip(),
            listen_key_provider=provider,
            user_stream_kind="um",
            use_testnet=bool(getattr(api, "USE_TESTNET", False)),
            proxy=getattr(api, "PROXY", None),
        )

