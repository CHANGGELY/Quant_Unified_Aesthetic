#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ws_manager.py - WebSocket（长连接）管理器

这个文件是干嘛的？
    WebSocket 可以理解成“电话一直不挂断”：
    - 交易所会不停把最新事件推给你（例如：订单成交、1分钟K线收盘）
    - 你不用每分钟去 REST API 轮询“现在啥情况”，更省请求、更实时

本文件负责：
    1) 同时维护“用户数据流”（订单/成交推送）与“行情数据流”（例如 kline_1m）
    2) 断线自动重连
    3) 把收到的消息交给回调函数处理（回调在 real_trading.py 里定义）
"""
import asyncio
import aiohttp
import json
import time
import logging
import os
import ssl
from 策略仓库.八号香农策略.api import binance_raw as api  # 使用原生 requests 版本

logger = logging.getLogger(__name__)

class BinanceWsManager:
    """
    BinanceWsManager - WebSocket 管理器（用户数据 + 行情数据）

    你可以把 WebSocket 理解成“电话一直不挂断”：
    - REST API：你每分钟打一次电话问“现在啥情况？”（有请求次数/权重成本）
    - WebSocket：交易所主动在电话里不停告诉你“刚发生了啥”（更实时、更省请求）
    """

    def __init__(self, symbols=None, *, market_stream_kind: str = "kline_1m"):
        self.listen_key = None
        self.use_testnet = getattr(api, 'USE_TESTNET', False)
        self.market_stream_kind = str(market_stream_kind or "kline_1m").strip()
        
        # 区分实盘和测试网地址
        if self.use_testnet:
            # 币安 Demo Trading 使用的 WebSocket 地址
            # 注意: 根据官方文档，Demo Trading WS 仍为 fstream.binancefuture.com
            # 参考: https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
            self.market_base_url = "wss://fstream.binancefuture.com/stream?streams="
            self.user_base_url = "wss://fstream.binancefuture.com/ws/"
        else:
            self.market_base_url = "wss://fstream.binance.com/stream?streams="
            self.user_base_url = "wss://fstream.binance.com/ws/"

        self.proxy = getattr(api, 'PROXY', None)
        self.ssl_verify = (os.getenv('BINANCE_WS_SSL_VERIFY', 'true').lower() != 'false')
        if self.proxy:
            self.ssl_verify = False
        self.session = None
        self.user_ws = None
        self.market_ws = None
        self.running = False
        self.callbacks = []
        self.on_connected_callbacks = []
        self.last_keep_alive = 0
        self.symbols = symbols if symbols else []
        self.ssl_context = None
        ca_file = os.getenv('BINANCE_WS_CA_FILE')
        if ca_file and os.path.exists(ca_file):
            try:
                self.ssl_context = ssl.create_default_context(cafile=ca_file)
            except Exception:
                self.ssl_context = None
        elif not self.ssl_verify:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self.ssl_context = ctx

    def add_listener(self, callback):
        """
        添加消息回调函数 callback(event_dict)
        """
        self.callbacks.append(callback)

    def add_connected_listener(self, callback):
        """
        添加连接成功回调函数 callback()
        用于断线重连后触发状态同步
        """
        self.on_connected_callbacks.append(callback)

    async def _get_listen_key(self):
        try:
            # 这里调用同步的 ccxt 方法，实际应放到 executor 中避免阻塞
            # 但为了简单直接调用 (假设耗时短)
            loop = asyncio.get_running_loop()
            self.listen_key = await loop.run_in_executor(None, api.get_listen_key)
            self.last_keep_alive = time.time()
            logger.info(f"获取到 ListenKey: {self.listen_key[:10]}...")
        except Exception as e:
            logger.error(f"获取 ListenKey 失败: {e}")
            raise

    async def _keep_alive(self):
        while self.running:
            await asyncio.sleep(60 * 30) # 30分钟一次
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, api.keep_alive_listen_key)
                logger.info("ListenKey 续期成功")
            except Exception as e:
                logger.error(f"ListenKey 续期失败: {e}")

    async def start(self):
        self.running = True
        await self._get_listen_key()
        asyncio.create_task(self._keep_alive())
        connector = aiohttp.TCPConnector(ssl=self.ssl_context if self.ssl_context else None)
        async with aiohttp.ClientSession(connector=connector) as session:
            self.session = session
            # 同时启动：
            # 1) 用户数据 WS：订单/成交推送（ORDER_TRADE_UPDATE）
            # 2) 行情 WS：1m K线收盘推送（用于波动率引擎）
            tasks = [asyncio.create_task(self._run_user_ws())]
            if self.symbols:
                tasks.append(asyncio.create_task(self._run_market_ws()))
            await asyncio.gather(*tasks)

    async def stop(self):
        self.running = False
        if self.user_ws:
            await self.user_ws.close()
        if self.market_ws:
            await self.market_ws.close()
        if self.session:
            await self.session.close()

    async def _run_user_ws(self):
        while self.running:
            try:
                # user_base_url 已经包含 /ws/，这里为了稳妥，检查一下
                if self.user_base_url.endswith('/'):
                    url = f"{self.user_base_url}{self.listen_key}"
                else:
                    url = f"{self.user_base_url}/{self.listen_key}"
                # ListenKey 属于敏感凭证（等同“临时门票”），日志里只打印前 10 位，避免泄露
                safe_listen_key = (self.listen_key[:10] + "...") if self.listen_key else ""
                safe_url = url.replace(self.listen_key, safe_listen_key) if self.listen_key else url
                logger.info(f"连接用户数据WS: {safe_url}")
                if self.proxy:
                    logger.info(f"用户WS使用代理: {self.proxy}")
                async with self.session.ws_connect(url, proxy=self.proxy, ssl=self.ssl_context if self.ssl_context else None, heartbeat=20.0) as ws:
                    self.user_ws = ws
                    logger.info("用户数据WS连接成功")
                    for cb in self.on_connected_callbacks:
                        try:
                            if asyncio.iscoroutinefunction(cb):
                                await cb()
                            else:
                                cb()
                        except Exception as e:
                            logger.error(f"连接回调执行失败: {e}")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                event_data = json.loads(msg.data)
                                for cb in self.callbacks:
                                    if asyncio.iscoroutinefunction(cb):
                                        await cb(event_data)
                                    else:
                                        cb(event_data)
                            except Exception as e:
                                logger.error(f"处理消息异常: {e}")
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            break
            except Exception as e:
                logger.error(f"WebSocket 连接断开或失败: {e}，5秒后重连...")
                await asyncio.sleep(5)
                try:
                    await self._get_listen_key()
                except Exception:
                    pass

    async def _run_market_ws(self):
        while self.running:
            try:
                streams = []
                for symbol in self.symbols:
                    clean_symbol = symbol.replace('/', '').lower()
                    if self.market_stream_kind == "kline_1m":
                        streams.append(f"{clean_symbol}@kline_1m")
                    elif self.market_stream_kind == "bookTicker":
                        streams.append(f"{clean_symbol}@bookTicker")
                    else:
                        # 兼容旧默认：ticker（不建议再用它来驱动波动率）
                        streams.append(f"{clean_symbol}@ticker")
                if not streams:
                    await asyncio.sleep(5)
                    continue
                stream_path = "/".join(streams)
                url = f"{self.market_base_url}{stream_path}"
                logger.info(f"连接行情WS: {url}")
                if self.proxy:
                    logger.info(f"行情WS使用代理: {self.proxy}")
                async with self.session.ws_connect(url, proxy=self.proxy, ssl=self.ssl_context if self.ssl_context else None, heartbeat=20.0) as ws:
                    self.market_ws = ws
                    logger.info("行情WS连接成功")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                raw_data = json.loads(msg.data)
                                event_data = raw_data.get('data', raw_data)
                                for cb in self.callbacks:
                                    if asyncio.iscoroutinefunction(cb):
                                        await cb(event_data)
                                    else:
                                        cb(event_data)
                            except Exception as e:
                                logger.error(f"处理消息异常: {e}")
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            break
            except Exception as e:
                logger.error(f"WebSocket 连接断开或失败: {e}，5秒后重连...")
                await asyncio.sleep(5)
