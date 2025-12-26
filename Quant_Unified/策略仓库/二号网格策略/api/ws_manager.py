import asyncio
import aiohttp
import json
import time
import logging
import os
import ssl
from 策略仓库.二号网格策略.api import binance as api

logger = logging.getLogger(__name__)

class BinanceWsManager:
    def __init__(self, symbols=None):
        self.listen_key = None
        self.market_base_url = "wss://fstream.binance.com/stream?streams="
        self.user_base_url = "wss://fstream.binance.com/pm/ws/"
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
            user_task = asyncio.create_task(self._run_user_ws())
            market_task = asyncio.create_task(self._run_market_ws())
            await asyncio.gather(user_task, market_task)

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
                url = f"{self.user_base_url}{self.listen_key}"
                logger.info(f"连接用户数据WS: {url}")
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
