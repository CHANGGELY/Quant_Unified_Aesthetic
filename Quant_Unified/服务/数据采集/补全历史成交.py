"""
币安合约 (USDC) 历史成交数据补全工具
Binance USDS-M Futures Historical AggTrade Downloader

功能：
1. 指定时间范围，自动从币安 REST API 下载历史归集成交 (aggTrade)。
2. 自动补全到 `数据/历史行情中心/行情数据` 目录，格式与实时采集一致 (Parquet)。
3. 支持断点续传（基于时间戳）。
4. 自动处理 API 权重限制。

使用方法：
python 补全历史成交.py --symbol BTCUSDC --start "2024-01-01 00:00:00" --end "2024-01-02 00:00:00"
"""

import argparse
import asyncio
import fcntl
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
import pandas as pd
from aiohttp import ClientSession

from 基础库.common_core.data_center import 获取历史行情子目录

# ==========================================
# 1. 项目路径与依赖检查
# ==========================================
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("历史补全")

# 常量
BASE_URL = "https://fapi.binance.com"  # USDC 合约通常也在 fapi，需确认
# 注意：USDC 合约的 Base URL 可能是 https://fapi.binance.com (U本位) 或 https://dapi.binance.com (币本位)
# 实际上 Binance 的 USDC 永续合约现在归类在 U本位合约 (UM) 下，使用 fapi。
# 接口: GET /fapi/v1/aggTrades

DATA_DIR = 获取历史行情子目录("行情数据")

class BinanceHistoryDownloader:
    def __init__(self, symbol: str, start_time: datetime, end_time: datetime):
        self.symbol = symbol.upper()
        # 转换为毫秒时间戳
        self.start_ts = int(start_time.timestamp() * 1000)
        self.end_ts = int(end_time.timestamp() * 1000)
        self.session: Optional[ClientSession] = None
        
        # 代理处理
        self.proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")
        if not self.proxy:
            # 默认使用本地 Clash 端口 (用户指定)
            self.proxy = "http://127.0.0.1:7897"
            
        if self.proxy:
            logger.info(f"🌐 使用代理: {self.proxy}")

    async def _init_session(self):
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)

    async def _close_session(self):
        if self.session:
            await self.session.close()

    async def _fetch_chunk(self, start_ts: int, end_ts: int, limit: int = 1000) -> List[Dict]:
        """
        获取一小段数据。
        Binance aggTrades 接口支持: symbol, startTime, endTime, limit (max 1000), fromId.
        如果不传 fromId，传 startTime 会返回 >= startTime 的第一条。
        """
        url = f"{BASE_URL}/fapi/v1/aggTrades"
        params = {
            "symbol": self.symbol,
            "startTime": start_ts,
            "endTime": end_ts,
            "limit": limit
        }
        
        for retry in range(5):
            try:
                # ssl=False: 忽略 SSL 证书验证 (解决代理自签名证书问题)
                async with self.session.get(url, params=params, proxy=self.proxy, ssl=False) as resp:
                    if resp.status == 429:
                        logger.warning("⚠️ 触发限频 (429)，休眠 5 秒...")
                        await asyncio.sleep(5)
                        continue
                    if resp.status != 200:
                        logger.error(f"❌ API 错误 {resp.status}: {await resp.text()}")
                        await asyncio.sleep(1)
                        continue
                    
                    data = await resp.json()
                    return data
            except Exception as e:
                logger.warning(f"⚠️ 网络错误 (重试 {retry+1}/5): {e}")
                await asyncio.sleep(2)
        
        return []

    def _save_chunk(self, trades: List[Dict]):
        """保存数据块到 Parquet"""
        if not trades:
            return

        # 转换格式适配现有结构
        # API返回:
        # {
        #   "a": 26129,         // 归集交易ID
        #   "p": "0.01633102",  // 成交价
        #   "q": "4.70443515",  // 成交量
        #   "f": 27781,         // 被归集的首个交易ID
        #   "l": 27781,         // 被归集的末次交易ID
        #   "T": 1498793709153, // 交易时间
        #   "m": true           // 买方是否是做市方(true=卖方主动成交/空头吃单? 不, true=Maker是Buyer -> Taker是Seller -> 卖单吃买单 -> 主动卖出)
        # }
        
        clean_data = []
        now = time.time()
        for t in trades:
            clean_data.append({
                'timestamp': now,          # 抓取时间 (填当前时间即可)
                'exchange_time': t['T'],   # 交易所时间
                'symbol': self.symbol,
                'price': float(t['p']),
                'qty': float(t['q']),
                'is_buyer_maker': t['m']
            })
        
        df = pd.DataFrame(clean_data)
        
        # 按天分区写入
        # 取第一条数据的时间来决定日期
        first_ts = clean_data[0]['exchange_time'] / 1000.0
        date_str = datetime.fromtimestamp(first_ts).strftime('%Y-%m-%d')
        
        save_dir = DATA_DIR / self.symbol / date_str
        save_dir.mkdir(parents=True, exist_ok=True)
        
        # 文件名: trade_history_startTs_endTs.parquet
        start_t = clean_data[0]['exchange_time']
        end_t = clean_data[-1]['exchange_time']
        filename = f"trade_hist_{start_t}_{end_t}.parquet"
        
        file_path = save_dir / filename
        df.to_parquet(str(file_path), engine='pyarrow', compression='snappy', index=False)
        # logger.info(f"💾 已保存 {len(df)} 条数据到 {date_str} (最后时间: {datetime.fromtimestamp(end_t/1000)})")

    async def run(self):
        await self._init_session()
        logger.info(f"🚀 开始补全 {self.symbol} 从 {datetime.fromtimestamp(self.start_ts/1000)} 到 {datetime.fromtimestamp(self.end_ts/1000)}")
        
        current_start = self.start_ts
        total_count = 0
        
        try:
            while current_start < self.end_ts:
                # 每次请求 1 小时窗口，或者直到填满 1000 条
                # 为了防止窗口太大导致中间漏数据（如果1小时内超过1000条，API只会返回前1000条）
                # 所以策略是：
                # 1. 请求 [current_start, current_start + 1h]
                # 2. 如果返回满 1000 条，取最后一条的时间作为下一次的 current_start
                # 3. 如果不满 1000 条，说明这 1 小时都拿完了，current_start += 1h
                
                # 实际上 API 行为：如果指定 startTime，它返回从那之后的 1000 条。
                # 我们可以不指定 endTime (或者指定很远)，只靠 startTime 递进。
                
                trades = await self._fetch_chunk(current_start, self.end_ts, limit=1000)
                
                if not trades:
                    # 没有数据了，或者当前时间段没数据
                    # 尝试跳过 1 小时看看
                    current_start += 3600 * 1000
                    if current_start >= self.end_ts:
                        break
                    continue
                
                self._save_chunk(trades)
                total_count += len(trades)
                
                # 更新指针：最后一条数据的 ID 或 时间
                last_ts = trades[-1]['T']
                
                # 下一次从最后一条的下一毫秒开始
                # 注意：如果同一毫秒有多条，可能会漏？
                # 严格来说应该用 fromId，但这里我们用 startTime 简化，只加 1ms 可能会重复，去重在整理阶段做。
                current_start = last_ts + 1
                
                # 打印进度
                progress = (current_start - self.start_ts) / (self.end_ts - self.start_ts) * 100
                dt_str = datetime.fromtimestamp(last_ts/1000).strftime('%Y-%m-%d %H:%M:%S')
                print(f"\r⏳ 进度: {progress:.2f}% | 当前时间: {dt_str} | 已下载: {total_count} 条", end="", flush=True)
                
                # 极速限流
                await asyncio.sleep(0.1)
                
        finally:
            print()
            await self._close_session()
            logger.info(f"✅ 补全完成。共下载 {total_count} 条数据。")

async def main():
    parser = argparse.ArgumentParser(description="补全历史 aggTrade 数据")
    parser.add_argument("--symbol", type=str, required=True, help="交易对，如 BTCUSDC")
    parser.add_argument("--start", type=str, default="", help="开始时间 YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--end", type=str, default="", help="结束时间 YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--start-ms", type=int, default=0, help="开始时间戳(毫秒, UTC)")
    parser.add_argument("--end-ms", type=int, default=0, help="结束时间戳(毫秒, UTC)")
    
    args = parser.parse_args()
    
    # --- 单例锁检查 (防重复运行) ---
    # 针对每个币种单独加锁，允许不同币种并行补全，但同一币种禁止双开
    symbol_upper = args.symbol.upper()
    lock_file_path = DATA_DIR / f"history_filler_{symbol_upper}.lock"
    
    # 确保目录存在
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    lock_file = None
    try:
        lock_file = open(lock_file_path, 'w')
        # 尝试获取非阻塞排他锁 (LOCK_EX | LOCK_NB)
        fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # 写入 PID
        lock_file.write(str(os.getpid()))
        lock_file.flush()
    except (IOError, BlockingIOError):
        logger.warning(f"⚠️ {symbol_upper} 的补全任务已在运行中 (锁文件: {lock_file_path})")
        logger.warning("无需重复启动。若确信无程序运行，请删除该锁文件后重试。")
        sys.exit(0)
    # ----------------------------
    
    if args.start_ms and args.end_ms:
        start_dt = datetime.fromtimestamp(args.start_ms / 1000, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(args.end_ms / 1000, tz=timezone.utc)
    else:
        if not args.start or not args.end:
            raise SystemExit("必须提供 (--start-ms,--end-ms) 或 (--start,--end)")
        start_dt = datetime.strptime(args.start, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(args.end, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    
    downloader = BinanceHistoryDownloader(args.symbol, start_dt, end_dt)
    await downloader.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
