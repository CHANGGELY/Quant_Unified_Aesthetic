# -*- coding: utf-8 -*-
"""
api/ws_manager.py - WebSocket（网络长连接）管理器（二号网格策略）

这个文件是干嘛的？
    我们把“WebSocket 管理”做成了公共组件：
        common_core.exchange.BinanceWsManager

    二号网格策略只需要在这里做一层很薄的封装，解决两件事：
    1) 兼容旧 import 路径（老代码还能 import 到同一个名字）
    2) 注入二号策略自己的 ListenKey 获取方式

术语解释（用人话）：
    - WebSocket（网络长连接）：交易所会“主动推送”订单成交/账户变动等消息给你，不用你每秒去问一次。
    - ListenKey（用户数据流钥匙）：币安用它来识别“这是你的私有推送频道”。
    - PM（Portfolio Margin：组合保证金/统一账户）：统一账户对应的用户数据流类型。

怎么用？
    你通常不需要直接运行本文件。
    实盘脚本会这样用它：
        from 策略仓库.二号网格策略.api.ws_manager import BinanceWsManager
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
