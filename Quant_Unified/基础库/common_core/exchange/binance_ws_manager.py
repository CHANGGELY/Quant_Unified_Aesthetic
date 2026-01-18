# -*- coding: utf-8 -*-
"""
common_core.exchange.binance_ws_manager - 币安 WebSocket（长连接）管理器（公共版）

这个文件是干嘛的？
    WebSocket（长连接）可以理解成“电话一直不挂断”：
    - 交易所会不断把最新事件推给你（订单成交、盘口变化、K线收盘等）
    - 你不用自己每秒/每分钟去 REST API（普通 HTTP 请求）轮询

为什么要放到 common_core？
    你现在仓库里有多个策略各自复制了一份 ws_manager.py，
    它们 80% 逻辑一样，只是：
    - 订阅的数据流不一样（ticker / kline_1m / depth20@100ms …）
    - 用户数据流地址不一样（普通 U 本位合约 vs 组合保证金/统一账户）

    抽到公共层后：
    - 代码更短、更稳
    - 修一次 bug，全仓库受益

术语解释（遇到缩写必须展开）：
    - UM（USDⓈ-M Futures）：U 本位合约（用 USDT/USDC 作为保证金）
    - PM（Portfolio Margin）：组合保证金 / 统一账户（多个资产一起算保证金，WebSocket 路径不同）
    - L2（Level 2）：多档位盘口深度（不是只有买一卖一）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import aiohttp

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ListenKeyProvider:
    """
    ListenKey 提供器（给用户数据流用）

    ListenKey（监听 Key）你可以理解成“临时门票”：
    - 你拿着这张门票连上用户数据流，交易所就会推送“你的订单成交/账户更新”

    这里用两个可调用对象（callable）来提供：
        - get_listen_key(): str
        - keep_alive_listen_key(): None
    """

    get_listen_key: Callable[[], str]
    keep_alive_listen_key: Callable[[], None]


class BinanceWsManager:
    """
    BinanceWsManager（公共版）

    支持：
        - 用户数据流（订单/成交推送）
        - 行情数据流（kline_1m / bookTicker / ticker / depth{N}@100ms 等）
        - 断线自动重连
        - 回调分发（把消息交给你在 real_trading.py 里写的 handler）
    """

    def __init__(
        self,
        symbols: Iterable[str] | None = None,
        *,
        market_stream_kind: str = "ticker",
        market_stream_kinds: list[str] | None = None,
        listen_key_provider: ListenKeyProvider | None = None,
        user_stream_kind: str = "um",
        use_testnet: bool | None = None,
        proxy: str | None = None,
    ) -> None:
        self.symbols = [str(s).strip().upper() for s in (symbols or []) if str(s).strip()]

        # 行情流类型：兼容“单个字符串”和“多个流”
        if market_stream_kinds is None:
            market_stream_kinds = [str(market_stream_kind or "ticker").strip()]
        self.market_stream_kinds = [str(x).strip() for x in market_stream_kinds if str(x).strip()]
        if not self.market_stream_kinds:
            self.market_stream_kinds = ["ticker"]

        kind = str(user_stream_kind or "um").strip().lower()
        if kind not in {"um", "pm"}:
            raise ValueError(f"user_stream_kind 只能是 um/pm, 当前={user_stream_kind}")
        self.user_stream_kind = kind

        # 是否测试网：默认从环境变量判断（也允许显式传入覆盖）
        if use_testnet is None:
            use_testnet = os.getenv("BINANCE_USE_TESTNET", "false").lower() == "true"
        self.use_testnet = bool(use_testnet)

        # WS 地址（主网/测试网）
        if self.use_testnet:
            self.market_base_url = "wss://fstream.binancefuture.com/stream?streams="
            self.user_base_url_um = "wss://fstream.binancefuture.com/ws/"
            self.user_base_url_pm = "wss://fstream.binancefuture.com/pm/ws/"
        else:
            self.market_base_url = "wss://fstream.binance.com/stream?streams="
            self.user_base_url_um = "wss://fstream.binance.com/ws/"
            self.user_base_url_pm = "wss://fstream.binance.com/pm/ws/"

        self.listen_key_provider = listen_key_provider
        self.listen_key: str | None = None

        # 代理与 SSL
        self.proxy = proxy or os.getenv("BINANCE_WS_PROXY") or None
        self.ssl_verify = (os.getenv("BINANCE_WS_SSL_VERIFY", "true").lower() != "false")
        if self.proxy:
            # 很多代理会拦截证书，允许你用环境变量手动控制
            self.ssl_verify = False

        self.ssl_context: ssl.SSLContext | None = None
        ca_file = os.getenv("BINANCE_WS_CA_FILE")
        if ca_file and os.path.exists(ca_file):
            try:
                self.ssl_context = ssl.create_default_context(cafile=ca_file)
                logger.info(f"已加载自定义 CA 证书: {ca_file}")
            except Exception:
                self.ssl_context = None
        elif not self.ssl_verify:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self.ssl_context = ctx
            logger.warning("已关闭 WebSocket SSL 证书校验 (BINANCE_WS_SSL_VERIFY=false)")

        # 运行状态
        self.session: aiohttp.ClientSession | None = None
        self.user_ws: aiohttp.ClientWebSocketResponse | None = None
        self.market_ws: aiohttp.ClientWebSocketResponse | None = None
        self.running = False
        self.callbacks: list[Callable[[dict[str, Any]], Any]] = []
        self.on_connected_callbacks: list[Callable[[], Any]] = []

        self._last_keep_alive = 0.0

    # =========================
    # 回调管理
    # =========================

    def add_listener(self, callback: Callable[[dict[str, Any]], Any]) -> None:
        self.callbacks.append(callback)

    def add_connected_listener(self, callback: Callable[[], Any]) -> None:
        self.on_connected_callbacks.append(callback)

    # =========================
    # 生命周期
    # =========================

    async def start(self) -> None:
        self.running = True

        connector = aiohttp.TCPConnector(ssl=self.ssl_context if self.ssl_context else None)
        async with aiohttp.ClientSession(connector=connector) as session:
            self.session = session

            tasks: list[asyncio.Task[None]] = []

            if self.listen_key_provider is not None:
                await self._get_listen_key()
                tasks.append(asyncio.create_task(self._keep_alive()))
                tasks.append(asyncio.create_task(self._run_user_ws()))

            if self.symbols and self.market_stream_kinds:
                tasks.append(asyncio.create_task(self._run_market_ws()))

            if not tasks:
                raise RuntimeError("未配置任何数据流：请提供 symbols 或 listen_key_provider")

            await asyncio.gather(*tasks)

    async def stop(self) -> None:
        self.running = False
        if self.user_ws:
            await self.user_ws.close()
        if self.market_ws:
            await self.market_ws.close()
        if self.session:
            await self.session.close()

    # =========================
    # ListenKey
    # =========================

    async def _get_listen_key(self) -> None:
        if self.listen_key_provider is None:
            return
        try:
            loop = asyncio.get_running_loop()
            self.listen_key = await loop.run_in_executor(None, self.listen_key_provider.get_listen_key)
            self._last_keep_alive = time.time()
            safe = (self.listen_key[:10] + "...") if self.listen_key else ""
            logger.info(f"获取到 ListenKey: {safe}")
        except Exception as e:
            logger.error(f"获取 ListenKey 失败: {e}")
            raise

    async def _keep_alive(self) -> None:
        if self.listen_key_provider is None:
            return
        while self.running:
            await asyncio.sleep(60 * 30)  # 30 分钟一次
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self.listen_key_provider.keep_alive_listen_key)
                logger.info("ListenKey 续期成功")
            except Exception as e:
                logger.error(f"ListenKey 续期失败: {e}")

    # =========================
    # WebSocket 循环
    # =========================

    def _user_base_url(self) -> str:
        return self.user_base_url_pm if self.user_stream_kind == "pm" else self.user_base_url_um

    async def _run_user_ws(self) -> None:
        if self.session is None:
            raise RuntimeError("session 未初始化")
        while self.running:
            try:
                if not self.listen_key:
                    await self._get_listen_key()
                    if not self.listen_key:
                        raise RuntimeError("listen_key 为空")

                base = self._user_base_url()
                url = f"{base}{self.listen_key}" if base.endswith("/") else f"{base}/{self.listen_key}"
                safe_url = url.replace(self.listen_key, (self.listen_key[:10] + "..."))
                logger.info(f"连接用户数据WS: {safe_url}")
                if self.proxy:
                    logger.info(f"用户WS使用代理: {self.proxy}")

                async with self.session.ws_connect(
                    url,
                    proxy=self.proxy,
                    ssl=self.ssl_context if self.ssl_context else None,
                    heartbeat=20.0,
                ) as ws:
                    self.user_ws = ws
                    logger.info("用户数据WS连接成功")

                    for cb in self.on_connected_callbacks:
                        await self._safe_call_connected(cb)

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._dispatch_text(msg.data, wrapped=False)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            break
            except Exception as e:
                logger.error(f"用户WS断开或失败: {e}，5秒后重连...")
                await asyncio.sleep(5)
                try:
                    await self._get_listen_key()
                except Exception:
                    pass

    async def _run_market_ws(self) -> None:
        if self.session is None:
            raise RuntimeError("session 未初始化")

        while self.running:
            try:
                streams: list[str] = []
                for symbol in self.symbols:
                    clean_symbol = symbol.replace("/", "").lower()
                    for kind in self.market_stream_kinds:
                        # kind 直接使用 Binance 的 stream suffix，例如：
                        # - kline_1m
                        # - bookTicker
                        # - depth20@100ms
                        streams.append(f"{clean_symbol}@{kind}")

                if not streams:
                    await asyncio.sleep(5)
                    continue

                stream_path = "/".join(streams)
                url = f"{self.market_base_url}{stream_path}"
                logger.info(f"连接行情WS: {url}")
                if self.proxy:
                    logger.info(f"行情WS使用代理: {self.proxy}")

                async with self.session.ws_connect(
                    url,
                    proxy=self.proxy,
                    ssl=self.ssl_context if self.ssl_context else None,
                    heartbeat=20.0,
                ) as ws:
                    self.market_ws = ws
                    logger.info("行情WS连接成功")

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._dispatch_text(msg.data, wrapped=True)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            break
            except Exception as e:
                logger.error(f"行情WS断开或失败: {e}，5秒后重连...")
                await asyncio.sleep(5)

    # =========================
    # 分发工具
    # =========================

    async def _dispatch_text(self, text: str, *, wrapped: bool) -> None:
        try:
            raw_data = json.loads(text)
            event_data = raw_data.get("data", raw_data) if wrapped else raw_data
            for cb in self.callbacks:
                await self._safe_call(cb, event_data)
        except Exception as e:
            logger.error(f"处理消息异常: {e}")

    @staticmethod
    async def _safe_call(cb: Callable[[dict[str, Any]], Any], event: dict[str, Any]) -> None:
        try:
            if asyncio.iscoroutinefunction(cb):
                await cb(event)
            else:
                cb(event)
        except Exception as e:
            logger.error(f"回调执行失败: {e}")

    @staticmethod
    async def _safe_call_connected(cb: Callable[[], Any]) -> None:
        try:
            if asyncio.iscoroutinefunction(cb):
                await cb()
            else:
                cb()
        except Exception as e:
            logger.error(f"连接回调执行失败: {e}")

