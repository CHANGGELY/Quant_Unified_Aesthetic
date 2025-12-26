"""
币安合约 (USDC) 高频行情采集服务
Binance USDS-M Futures High-Frequency Data Collector

功能：
1. 实时采集 BTC, ETH, SOL, XRP, BNB 的 USDC 本位永续合约数据。
# 2. 订阅 Depth (可配置档位) 和 AggTrade (逐笔成交)。
# 3. 使用异步 IO (asyncio) 接收，线程池 (ThreadPool) 写入 Parquet。
4. 自动断线重连，优雅退出。

依赖库 (请确保安装):
pip install asyncio websockets pandas pyarrow
"""

import fcntl
import asyncio
import json
import logging
import os
import signal
import ssl
import sys
import time
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any

# ==========================================
# 1. 项目路径自动注入 (Path Injection)
# ==========================================
# 自动定位到 Quant_Unified 根目录
# 当前文件: Quant_Unified/服务/数据采集/启动采集.py
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2] # 向上跳 2 层

# 将项目根目录加入 Python 搜索路径
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# ==========================================
# 2. 依赖检查
# ==========================================
try:
    import websockets
    import pandas as pd
    import pyarrow
except ImportError as e:
    print(f"❌ 缺少必要的依赖库: {e.name}")
    print("请运行: pip install websockets pandas pyarrow")
    sys.exit(1)

# ==========================================
# 3. 配置区域
# =======================================# 导入全局配置
try:
    from config import DEPTH_LEVEL
except ImportError:
    # 尝试从 Quant_Unified 包导入 (如果运行方式不同)
    try:
        from Quant_Unified.config import DEPTH_LEVEL
    except ImportError:
        print("⚠️ 未找到全局配置 config.DEPTH_LEVEL，使用默认值 20")
        DEPTH_LEVEL = 20

SYMBOLS = ["BTCUSDC", "ETHUSDC", "SOLUSDC", "XRPUSDC", "BNBUSDC"]

BASE_URL = "wss://fstream.binance.com/stream?streams={}"

# 数据存储路径
DATA_DIR = PROJECT_ROOT / "data" / "行情数据"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 日志路径
LOG_DIR = PROJECT_ROOT / "系统日志"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 缓冲配置
BUFFER_SIZE_TRIGGER = 5000  # 单个缓冲区积累多少条数据触发写入
FLUSH_INTERVAL = 60         # 无论数据多少，每隔多少秒强制写入一次

# 重连配置
MAX_RECONNECT_DELAY = 30    # 最大重连等待时间(秒)

# 自动整理配置
AUTO_ORGANIZE_ENABLED = True
AUTO_ORGANIZE_CHECK_INTERVAL_SEC = 600
AUTO_ORGANIZE_FRAGMENT_THRESHOLD = 120
AUTO_ORGANIZE_LOOKBACK_DAYS = 7
AUTO_ORGANIZE_DELETE_SOURCE = True  # 自动删除源碎文件（今日文件除外，除非手动指定）

# 自动补全配置（基于 depth 缺口推断采集器停机窗口，仅补全 trade）
AUTO_FILL_TRADE_FROM_DEPTH_GAPS_ENABLED = True
AUTO_FILL_DEPTH_GAP_MIN_MS = 60_000
AUTO_FILL_MAX_GAPS_PER_SYMBOL_DAY = 3
AUTO_FILL_MAX_WINDOW_MS = 6 * 60 * 60 * 1000

# ==========================================
# 4. 日志配置
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "market_collector.log", encoding='utf-8')
    ]
)
logger = logging.getLogger("数据采集器")

# ==========================================
# 5. 数据存储引擎 (Storage Engine)
# ==========================================

class DataStorageEngine:
    """
    负责数据的内存缓冲和磁盘写入。
    消费者模式：在独立的线程池中执行写入，不卡 WebSocket。
    """
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        # 数据缓冲区: { 'BTCUSDC': { 'depth': [], 'trade': [] }, ... }
        self.buffers: Dict[str, Dict[str, List[Dict]]] = {
            s: {'depth': [], 'trade': []} for s in SYMBOLS
        }
        self.last_flush_time = time.time()
        # 线程池：用于执行 CPU 密集型和 IO 密集型的 Parquet 写入
        self.io_executor = ThreadPoolExecutor(max_workers=4)
        self.lock = asyncio.Lock() # 协程锁

    def buffer_data(self, symbol: str, data_type: str, record: Dict[str, Any]):
        """生产数据：放入内存队列"""
        self.buffers[symbol][data_type].append(record)

    def check_flush_condition(self) -> bool:
        """检查是否满足写入条件"""
        now = time.time()
        # 条件1: 时间到了
        if now - self.last_flush_time >= FLUSH_INTERVAL:
            return True
        
        # 条件2: 任意一个缓冲区满了
        for symbol in SYMBOLS:
            for dtype in ['depth', 'trade']:
                if len(self.buffers[symbol][dtype]) >= BUFFER_SIZE_TRIGGER:
                    return True
        return False

    async def flush(self, force: bool = False):
        """
        触发数据落盘 (Consumer)
        """
        # 如果没获取到锁，说明正在写入，跳过本次检查（除非强制）
        if self.lock.locked() and not force:
            return

        async with self.lock:
            if not force and not self.check_flush_condition():
                return

            tasks = []
            current_time = time.time()
            
            # 遍历缓冲区，取出数据，清空缓冲区
            for symbol in SYMBOLS:
                for dtype in ['depth', 'trade']:
                    data_chunk = self.buffers[symbol][dtype]
                    if not data_chunk:
                        continue
                    
                    # 原子交换：先把引用拿出来，立刻清空原列表
                    # 这样主线程可以继续往 buffers 里塞新数据，互不影响
                    to_write = data_chunk
                    self.buffers[symbol][dtype] = []
                    
                    # 将写入任务扔给线程池
                    tasks.append(
                        asyncio.get_running_loop().run_in_executor(
                            self.io_executor,
                            self._write_parquet,
                            symbol,
                            dtype,
                            to_write
                        )
                    )
            
            if tasks:
                logger.info(f"⚡ 触发批量写入 (Force={force}, Tasks={len(tasks)})...")
                # 等待所有线程完成写入
                await asyncio.gather(*tasks)
                self.last_flush_time = current_time
                logger.info("✅ 批量写入完成")

    def _write_parquet(self, symbol: str, data_type: str, data: List[Dict]):
        """
        [阻塞函数] 在线程中运行。
        """
        try:
            if not data:
                return

            df = pd.DataFrame(data)
            
            # 生成路径: ./data/行情数据/BTCUSDC/2025-12-20/
            today_str = datetime.now().strftime('%Y-%m-%d')
            save_dir = self.output_dir / symbol / today_str
            save_dir.mkdir(parents=True, exist_ok=True)

            # 文件名: trade_1698372312123456.parquet (纳秒时间戳防止重名)
            timestamp_ns = time.time_ns()
            filename = f"{data_type}_{timestamp_ns}.parquet"
            file_path = save_dir / filename

            # 写入 Parquet (Snappy 压缩)
            df.to_parquet(str(file_path), engine='pyarrow', compression='snappy', index=False)
            
        except Exception as e:
            logger.error(f"❌ 写入文件失败 {symbol} {data_type}: {e}")

# ==========================================
# 6. 采集核心 (Collector)
# ==========================================

class BinanceRecorder:
    def __init__(self):
        self.running = True
        self.storage = DataStorageEngine(DATA_DIR)

        self._auto_organize_last_run: Dict[tuple[str, str], float] = {}
        self._auto_organize_guard = asyncio.Lock()

        ssl_verify_env = os.getenv('BINANCE_WS_SSL_VERIFY')
        self.ssl_verify = ((ssl_verify_env or 'true').lower() != 'false')
        self._allow_insecure_ssl_fallback = (ssl_verify_env is None)
        self._insecure_ssl_fallback_used = False
        
        # --- 智能诊断配置 ---
        self.consecutive_failures = 0
        self.last_ip_check_time = 0
        # 币安限制或部分限制的地区代码 (ISO 3166-1 alpha-2)
        self.RESTRICTED_REGIONS = {
            'US': '美国 (United States)',
            'CN': '中国内地 (Mainland China)',
            'GB': '英国 (United Kingdom)',
            'CA': '加拿大 (Canada)',
            'HK': '香港 (Hong Kong)',
            'JP': '日本 (Japan)',
            'IT': '意大利 (Italy)',
            'DE': '德国 (Germany)',
            'NL': '荷兰 (Netherlands)',
        }

        self.ssl_context = None
        ca_file = os.getenv('BINANCE_WS_CA_FILE')
        if ca_file and os.path.exists(ca_file):
            try:
                self.ssl_context = ssl.create_default_context(cafile=ca_file)
                logger.info(f"已加载自定义 CA 证书: {ca_file}")
            except Exception as e:
                logger.error(f"加载自定义 CA 证书失败: {e}")
                self.ssl_context = None
        elif not self.ssl_verify:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self.ssl_context = ctx
            logger.warning("已关闭 WebSocket SSL 证书校验 (BINANCE_WS_SSL_VERIFY=false)")
        
        # 构造 Combined Stream URL
        # 格式: btcusdc@depth5@100ms / btcusdc@aggTrade
        streams = []
        for s in SYMBOLS:
            lower_s = s.lower()
            streams.append(f"{lower_s}@depth{DEPTH_LEVEL}@100ms")
            streams.append(f"{lower_s}@aggTrade")
        
        self.url = BASE_URL.format("/".join(streams))
        logger.info(f"订阅 {len(SYMBOLS)} 个币种，共 {len(streams)} 个数据流")
        logger.info(f"数据存放目录: {DATA_DIR}")

    async def _get_current_ip_info(self) -> Dict[str, Any]:
        """获取当前 IP 的地理位置信息"""
        # 避免频繁查询 IP 接口 (至少间隔 60 秒)
        now = time.time()
        if now - self.last_ip_check_time < 60:
            return {}
        
        self.last_ip_check_time = now
        url = "http://ip-api.com/json/?fields=status,message,countryCode,query"
        
        def _fetch_blocking():
            import urllib.request
            try:
                # 显式禁用代理进行 IP 检查，以获取真实的出口 IP (或者根据需要决定是否带代理)
                # 这里我们保持系统默认，这样如果是 VPN/代理切换，能查到切换后的 IP
                with urllib.request.urlopen(url, timeout=5) as response:
                    return json.loads(response.read().decode())
            except Exception as e:
                return {"status": "fail", "message": str(e)}

        return await asyncio.get_running_loop().run_in_executor(None, _fetch_blocking)

    async def _diagnose_connection_issue(self, error_msg: str = ""):
        """诊断连接问题并给出建议"""
        logger.info("🔍 正在启动智能连接诊断...")
        ip_info = await self._get_current_ip_info()
        
        if not ip_info or ip_info.get("status") != "success":
            logger.warning(f"⚠️ 诊断失败: 无法获取 IP 地理位置信息 ({ip_info.get('message', '未知错误')})")
            return

        current_ip = ip_info.get("query", "未知")
        country_code = ip_info.get("countryCode", "未知")
        country_name = self.RESTRICTED_REGIONS.get(country_code, country_code)

        logger.info(f"📍 当前出口 IP: {current_ip} | 归属地: {country_name}")

        # 场景 1: 地理位置受限
        if country_code in self.RESTRICTED_REGIONS:
            logger.error("🛑 [诊断结果] 严重：当前 IP 归属地处于币安限制地区！")
            logger.error(f"   原因: 币安不支持来自 {country_name} 的直接 API 访问。")
            logger.error("   建议: 请切换 VPN/代理至新加坡、日本或其他不受限地区。")
        
        # 场景 2: 捕获到 403 错误
        elif "403" in error_msg:
            logger.error("🛑 [诊断结果] 访问被封锁 (Forbidden 403)")
            logger.error("   原因: 你的 IP 可能已被币安暂时屏蔽或因为地区政策原因被拦截。")
            logger.error("   建议: 即便归属地看似正常，也请尝试更换代理节点。")
        
        # 场景 3: 连续失败多次
        elif self.consecutive_failures >= 5:
            logger.warning("🛑 [诊断结果] 持续连接超时或失败")
            logger.info("   建议: 请检查你的本地网络连接是否稳定，或者尝试重启代理服务。")

    def _get_proxy_env(self) -> Dict[str, str]:
        keys = [
            'ALL_PROXY', 'all_proxy',
            'HTTPS_PROXY', 'https_proxy',
            'HTTP_PROXY', 'http_proxy',
        ]
        env = {}
        for k in keys:
            v = os.environ.get(k)
            if v:
                env[k] = v
        return env

    def _disable_proxy_env(self):
        for k in [
            'ALL_PROXY', 'all_proxy',
            'HTTPS_PROXY', 'https_proxy',
            'HTTP_PROXY', 'http_proxy',
        ]:
            os.environ.pop(k, None)
        os.environ['NO_PROXY'] = '*'
        os.environ['no_proxy'] = '*'

    def _socks_proxy_configured(self) -> bool:
        env = self._get_proxy_env()
        for v in env.values():
            low = str(v).strip().lower()
            if low.startswith(('socks5://', 'socks5h://', 'socks4://', 'socks://')):
                return True
        return False

    async def _connect_ws(self):
        proxy_env = self._get_proxy_env()
        use_direct = False

        if self._socks_proxy_configured():
            try:
                import python_socks  # noqa: F401
            except Exception:
                use_direct = True
                proxy_view = ", ".join([f"{k}={v}" for k, v in proxy_env.items()])
                logger.error(
                    "检测到你设置了 SOCKS 代理，但当前环境缺少 python-socks，导致 WebSocket 无法连接。"
                    "已自动临时禁用代理，改为直连。若你必须走代理，请先安装: pip install python-socks\n"
                    f"当前代理环境变量: {proxy_view}"
                )

        if use_direct:
            self._disable_proxy_env()

        async def _do_connect():
            kwargs = {
                'ping_interval': 20,
                'ping_timeout': 20,
            }
            if self.ssl_context is not None:
                kwargs['ssl'] = self.ssl_context

            try:
                return await websockets.connect(self.url, proxy=None, **kwargs)
            except TypeError:
                return await websockets.connect(self.url, **kwargs)

        try:
            return await _do_connect()
        except Exception as e:
            msg = str(e)
            
            # 扩展：不仅捕获证书错误，也捕获 HTTP 400 (通常也是代理/防火墙导致的握手失败)
            is_ssl_error = 'CERTIFICATE_VERIFY_FAILED' in msg
            is_handshake_error = 'HTTP 400' in msg or 'InvalidStatusCode' in msg

            if (
                self.ssl_verify
                and self.ssl_context is None
                and getattr(self, '_allow_insecure_ssl_fallback', False)
                and not getattr(self, '_insecure_ssl_fallback_used', False)
                and (is_ssl_error or is_handshake_error)
            ):
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                self.ssl_context = ctx
                self._insecure_ssl_fallback_used = True
                
                reason = "SSL 证书校验失败" if is_ssl_error else "HTTP 400 握手异常"
                logger.warning(
                    f"⚠️ {reason}，已自动改为不校验 SSL 继续连接。"
                    "若要恢复安全校验：设置 BINANCE_WS_CA_FILE=/path/to/ca.pem，"
                    "或设置 BINANCE_WS_SSL_VERIFY=true 强制校验。"
                )
                return await _do_connect()
            raise

    def _parse_depth(self, payload: Dict) -> Dict:
        """
        清洗 depth5 数据
        """
        ts_recv = time.time()
        # T: Transaction Time (撮合时间)
        ts_exch = payload.get('T', payload.get('E', 0)) 
        
        item = {
            'timestamp': ts_recv,
            'exchange_time': ts_exch,
            'symbol': payload['s']
        }

        # 展平 Bids (买单)
        bids = payload.get('b', [])
        for i in range(DEPTH_LEVEL):
            if i < len(bids):
                item[f'bid{i+1}_p'] = float(bids[i][0])
                item[f'bid{i+1}_q'] = float(bids[i][1])
            else:
                item[f'bid{i+1}_p'] = None
                item[f'bid{i+1}_q'] = None

        # 展平 Asks (卖单)
        asks = payload.get('a', [])
        for i in range(DEPTH_LEVEL):
            if i < len(asks):
                item[f'ask{i+1}_p'] = float(asks[i][0])
                item[f'ask{i+1}_q'] = float(asks[i][1])
            else:
                item[f'ask{i+1}_p'] = None
                item[f'ask{i+1}_q'] = None
        
        return item

    def _parse_agg_trade(self, payload: Dict) -> Dict:
        """
        清洗 aggTrade 数据
        """
        return {
            'timestamp': time.time(),
            'exchange_time': payload['T'],
            'symbol': payload['s'],
            'price': float(payload['p']),
            'qty': float(payload['q']),
            'is_buyer_maker': payload['m'] # True=卖方主动, False=买方主动
        }

    def _count_parquet_files(self, symbol: str, date: str) -> int:
        p = DATA_DIR / symbol / date
        if not p.exists():
            return 0
        try:
            return len(list(p.glob("*.parquet")))
        except Exception:
            return 0

    def _iter_candidate_dates(self) -> list[str]:
        today = datetime.now().date()
        cutoff = today - timedelta(days=int(AUTO_ORGANIZE_LOOKBACK_DAYS))

        dates: set[str] = set()
        for symbol in SYMBOLS:
            symbol_dir = DATA_DIR / symbol
            if not symbol_dir.exists():
                continue
            for date_dir in symbol_dir.iterdir():
                if not date_dir.is_dir():
                    continue
                d = date_dir.name
                try:
                    day = datetime.strptime(d, "%Y-%m-%d").date()
                except Exception:
                    continue
                if day > today:  # 只排除未来的日期（允许整理今天）
                    continue
                if day < cutoff:
                    continue
                dates.add(d)

        return sorted(dates)

    async def _run_organize(self, date: str, symbols_csv: str) -> dict | None:
        cmd = [
            sys.executable,
            str(CURRENT_FILE.parent / "整理行情数据.py"),
            "--date",
            date,
            "--symbols",
            symbols_csv,
            "--check-gap",
            "--overwrite",
        ]
        if AUTO_ORGANIZE_DELETE_SOURCE:
            cmd.append("--delete-source")

        def _run_blocking():
            return subprocess.run(cmd, check=False)

        await asyncio.get_running_loop().run_in_executor(None, _run_blocking)

        report_path = PROJECT_ROOT / "data" / "行情数据_整理" / "整理报告.json"
        try:
            return json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    async def _run_fill_trade(self, symbol: str, start_ms: int, end_ms: int) -> None:
        if start_ms >= end_ms:
            return
        cmd = [
            sys.executable,
            str(CURRENT_FILE.parent / "补全历史成交.py"),
            "--symbol",
            symbol,
            "--start-ms",
            str(int(start_ms)),
            "--end-ms",
            str(int(end_ms)),
        ]

        def _run_blocking():
            return subprocess.run(cmd, check=False)

        await asyncio.get_running_loop().run_in_executor(None, _run_blocking)

    async def _run_auto_organize(self):
        logger.info("📅 启动自动整理守护...")

        while self.running:
            if not AUTO_ORGANIZE_ENABLED:
                await asyncio.sleep(int(AUTO_ORGANIZE_CHECK_INTERVAL_SEC))
                continue

            try:
                async with self._auto_organize_guard:
                    now_ts = time.time()
                    candidates = self._iter_candidate_dates()

                    for date in candidates:
                        need_symbols: list[str] = []
                        for symbol in SYMBOLS:
                            frag_count = self._count_parquet_files(symbol, date)
                            if frag_count < int(AUTO_ORGANIZE_FRAGMENT_THRESHOLD):
                                continue
                            last = self._auto_organize_last_run.get((symbol, date), 0.0)
                            if now_ts - last < 3600:
                                continue
                            need_symbols.append(symbol)

                        if not need_symbols:
                            continue

                        symbols_csv = ",".join(need_symbols)
                        logger.info(
                            f"🧹 触发自动整理: date={date}, symbols={symbols_csv}, threshold={AUTO_ORGANIZE_FRAGMENT_THRESHOLD}"
                        )
                        report = await self._run_organize(date=date, symbols_csv=symbols_csv)
                        for s in need_symbols:
                            self._auto_organize_last_run[(s, date)] = now_ts

                        if not (AUTO_FILL_TRADE_FROM_DEPTH_GAPS_ENABLED and report):
                            continue

                        gap_samples = report.get("gap_samples") or []
                        depth_gaps = [
                            g
                            for g in gap_samples
                            if g.get("dtype") == "depth" and int(g.get("gap_ms", 0)) >= int(AUTO_FILL_DEPTH_GAP_MIN_MS)
                        ]
                        if not depth_gaps:
                            continue

                        by_symbol: Dict[str, list[dict]] = {}
                        for g in depth_gaps:
                            sym = str(g.get("symbol") or "")
                            if not sym:
                                continue
                            by_symbol.setdefault(sym, []).append(g)

                        for sym, gaps in by_symbol.items():
                            gaps_sorted = sorted(gaps, key=lambda x: int(x.get("gap_ms", 0)), reverse=True)
                            for g in gaps_sorted[: int(AUTO_FILL_MAX_GAPS_PER_SYMBOL_DAY)]:
                                start_ms = int(g["prev_exchange_time"]) + 1
                                end_ms = int(g["next_exchange_time"]) - 1
                                if end_ms - start_ms > int(AUTO_FILL_MAX_WINDOW_MS):
                                    end_ms = start_ms + int(AUTO_FILL_MAX_WINDOW_MS)

                                logger.info(f"🧩 触发补全 trade: {sym} {date} {start_ms}->{end_ms}")
                                await self._run_fill_trade(symbol=sym, start_ms=start_ms, end_ms=end_ms)

                            logger.info(f"🔁 补全后复整理 trade: {sym} {date}")
                            await self._run_organize(date=date, symbols_csv=sym)

            except Exception as e:
                logger.error(f"自动整理守护异常: {e}")

            await asyncio.sleep(int(AUTO_ORGANIZE_CHECK_INTERVAL_SEC))

    async def connect(self):
        """主连接循环 (含断线重连)"""
        # 1. 静音 websockets 库的 INFO 日志，防止重连时控制台刷屏
        logging.getLogger("websockets").setLevel(logging.WARNING)

        asyncio.create_task(self._run_auto_organize())

        retry_delay = 1
        
        while self.running:
            # 记录尝试连接的时间，用于判断是否为"抖动"连接
            connect_start_time = time.time()
            
            try:
                logger.info(f"📡 正在连接币安合约 WebSocket...")
                async with await self._connect_ws() as ws:
                    logger.info("🟢 连接成功! 开始接收数据...")
                    
                    # ⚠️ 注意：此处不再立即重置 retry_delay = 1
                    # 我们改为在连接断开时，判断"这次连接存活了多久"。
                    # 只有存活时间 > 10秒，才判定为网络稳定，重置延迟。
                    # 这样可以完美解决 IP 切换时"连上即断"导致的无限报错刷屏问题。
                    
                    while self.running:
                        try:
                            # 1秒超时，确保能定期醒来检查 flush 和 running 状态
                            message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            data = json.loads(message)
                            
                            # 只要收到有效数据，就认为连接是通的，重置失败计数
                            self.consecutive_failures = 0
                            
                            if 'data' not in data:
                                continue
                                
                            payload = data['data']
                            stream_name = data['stream']
                            
                            # 分发处理
                            if 'depth5' in stream_name:
                                clean_data = self._parse_depth(payload)
                                self.storage.buffer_data(clean_data['symbol'], 'depth', clean_data)
                            elif 'aggTrade' in stream_name:
                                clean_data = self._parse_agg_trade(payload)
                                self.storage.buffer_data(clean_data['symbol'], 'trade', clean_data)
                                
                        except asyncio.TimeoutError:
                            pass # 超时只是为了让循环转起来，检查 flush
                        except websockets.exceptions.ConnectionClosed as e:
                            # 连接已断开，必须跳出内层循环，让外层循环重新连接
                            # 这里我们用 raise 把异常向上抛，让外层的 except 捕获
                            raise
                        except Exception as e:
                            # 其他异常（如 JSON 解析错误）只打印日志，不中断循环
                            logger.error(f"处理消息异常: {e}")
                        
                        # 每次循环都检查是否需要写入硬盘
                        await self.storage.flush()

            except (websockets.exceptions.ConnectionClosed, OSError) as e:
                # === 智能退避逻辑 ===
                alive_duration = time.time() - connect_start_time
                self.consecutive_failures += 1
                
                if alive_duration > 15:
                    retry_delay = 1
                
                msg = str(e)
                # 触发智能诊断的条件：捕获到 403 错误，或者连续失败 5 次
                do_diagnose = "403" in msg or self.consecutive_failures >= 5
                
                if "CERTIFICATE_VERIFY_FAILED" in msg:
                    logger.error("🔴 SSL 证书校验失败...")
                else:
                    logger.warning(f"🔴 连接断开 (存活 {alive_duration:.1f}s, 第{self.consecutive_failures}次失败): {e}")

                if do_diagnose:
                    await self._diagnose_connection_issue(msg)

                if not self.running:
                    break
                
                logger.info(f"⏳ {retry_delay}秒后重连...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, MAX_RECONNECT_DELAY)

            except Exception as e:
                # === 智能退避逻辑 ===
                alive_duration = time.time() - connect_start_time
                self.consecutive_failures += 1
                if alive_duration > 15:
                    retry_delay = 1

                msg = str(e)
                do_diagnose = "403" in msg or self.consecutive_failures >= 5

                if "python-socks is required" in msg:
                    logger.error("❌ 缺少 python-socks 库...")
                elif "CERTIFICATE_VERIFY_FAILED" in msg:
                    logger.error(f"❌ SSL 证书问题: {msg}")
                else:
                    logger.error(f"❌ 未知错误 (存活 {alive_duration:.1f}s, 第{self.consecutive_failures}次失败): {e}")
                
                if do_diagnose:
                    await self._diagnose_connection_issue(msg)

                logger.info(f"⏳ {retry_delay}秒后重连...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, MAX_RECONNECT_DELAY)

    async def shutdown(self):
        """优雅退出"""
        logger.info("🛑 正在停止采集器，请稍候...")
        self.running = False
        # 强制刷写剩余数据
        await self.storage.flush(force=True)
        # 关闭线程池
        self.storage.io_executor.shutdown(wait=True)
        logger.info("👋 再见。")

# ==========================================
# 7. 主程序入口
# ==========================================

async def main():
    # --- 单例锁检查 (防重复启动) ---
    lock_file_path = DATA_DIR / "market_collector.lock"
    try:
        # 打开锁文件（如果不存在则创建）
        lock_file = open(lock_file_path, 'w')
        # 尝试获取非阻塞排他锁
        # LOCK_EX: 排他锁 (Exclusive Lock)
        # LOCK_NB: 非阻塞 (Non-Blocking)，如果已被锁住则立即抛异常
        fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        
        # 写入当前进程 ID，方便调试（可选）
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        
        # 注意：不要关闭 lock_file，也不要 fcntl.LOCK_UN，
        # 直到程序退出（操作系统会自动释放锁）。
        # 如果在这里 close 了，锁就失效了。
        # 我们把 lock_file 引用挂在 loop 上防止被垃圾回收（虽然 main 函数不退出也行）
        
    except (IOError, BlockingIOError):
        logger.warning(f"⚠️ 程序已在运行中 (锁文件占用: {lock_file_path})")
        logger.warning("无需重复启动。若确信无程序运行，请删除该锁文件后重试。")
        # 优雅退出
        sys.exit(0)
    # ----------------------------

    recorder = BinanceRecorder()
    
    # 注册信号处理 (Ctrl+C)
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    
    def signal_handler():
        logger.info("收到退出信号 (SIGINT/SIGTERM)...")
        stop_event.set()

    # 注册信号（Windows 下可能不支持 add_signal_handler，需特殊处理，这里默认 Unix/Mac）
    if sys.platform != 'win32':
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
    else:
        logger.info("Windows环境: 请按 Ctrl+C 触发 KeyboardInterrupt")

    # 启动采集任务
    collector_task = asyncio.create_task(recorder.connect())
    
    # 等待退出信号
    try:
        if sys.platform == 'win32':
            # Windows 下简单的等待，依靠外层 KeyboardInterrupt 捕获
            while not stop_event.is_set():
                await asyncio.sleep(1)
        else:
            await stop_event.wait()
    except asyncio.CancelledError:
        pass
    
    # 执行清理
    await recorder.shutdown()
    collector_task.cancel()
    try:
        await collector_task
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    try:
        # Windows下可能需要设置 SelectorEventLoop
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            
        asyncio.run(main())
    except KeyboardInterrupt:
        # 再次捕获以防万一
        pass
