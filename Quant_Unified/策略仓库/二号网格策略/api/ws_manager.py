# -*- coding: utf-8 -*-
"""
ws_manager.py - WebSocket（长连接）管理器（二号策略专用薄封装）

这个文件是干嘛的？
    我们把通用的 WebSocket 管理逻辑抽到了公共层：
        common_core.exchange.binance_ws_manager.BinanceWsManager

    二号策略（以及复用它的三号策略）只需要：
        - 兼容旧 import 路径
        - 注入二号策略自己的 API（用于 ListenKey）
        - 指定用户数据流类型为 PM

术语解释：
    - PM（Portfolio Margin）：组合保证金/统一账户（WebSocket 路径带 /pm/）
"""

from __future__ import annotations

from common_core.exchange import BinanceWsManager as _CoreBinanceWsManager
from common_core.exchange import ListenKeyProvider as _ListenKeyProvider

from 策略仓库.二号网格策略.api import binance as api


class BinanceWsManager(_CoreBinanceWsManager):
    def __init__(self, symbols=None):
        provider = _ListenKeyProvider(
            get_listen_key=lambda: api.get_listen_key(enable_retry=True),
            keep_alive_listen_key=lambda: api.keep_alive_listen_key(enable_retry=True),
        )
        super().__init__(
            symbols=symbols,
            market_stream_kind="ticker",
            listen_key_provider=provider,
            user_stream_kind="pm",
            use_testnet=None,
            proxy=getattr(api, "PROXY", None),
        )

