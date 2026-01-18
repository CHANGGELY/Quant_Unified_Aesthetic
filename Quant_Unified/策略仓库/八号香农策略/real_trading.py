# -*- coding: utf-8 -*-
"""
8号香农策略 - 实盘脚本（被动挂单吃波动）

这个文件是干嘛的？
    你可以把它理解成“实盘机器人启动器”：
    - 负责连接交易所（下单/撤单/查账户）
    - 负责连 WebSocket（长连接：像电话不挂断，交易所会实时推送成交/行情）
    - 负责把“1分钟K线已收盘”的事件喂给策略逻辑，然后把策略输出变成真实挂单

本策略的核心思想（用人话讲）：
    目标长期维持 50% 币 + 50% 现金（CPRP：Constant Proportion Rebalancing Portfolio，固定比例组合）
    但实盘不做“收盘瞬移调仓”，而是用多层限价单被动挂着，等价格波动来“撞到你的单”才成交，
    这样才能吃到 Maker 0 手续费的优势，并且避免频繁吃滑点。
"""
import time
import os
import asyncio
import logging
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import deque

import argparse

# ============================================================
# 环境变量加载（解决“明明有 Key 但读不到”）
# ============================================================
# 你的 `.env` 在 `Quant_Unified/.env`，而这个脚本在更深的目录里。
# 如果不主动加载，就只能读到“系统环境变量”(export 的那种)，导致 Key 为空。
try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


def _加载环境变量文件() -> list[Path]:
    if load_dotenv is None:
        return []

    当前文件 = Path(__file__).resolve()
    策略目录 = 当前文件.parent

    候选路径: list[Path] = []

    策略env = 策略目录 / ".env"
    if 策略env.is_file():
        候选路径.append(策略env)

    # 向上查找最近的 .env（通常就是 Quant_Unified/.env）
    for 上级目录 in 策略目录.parents:
        上级env = 上级目录 / ".env"
        if 上级env.is_file() and 上级env not in 候选路径:
            候选路径.append(上级env)
            break

    for 路径 in 候选路径:
        load_dotenv(dotenv_path=路径, override=False)

    return 候选路径


try:
    from common_core.utils.env_kit import 加载_env文件
except Exception:  # pragma: no cover
    加载_env文件 = None

已加载_env路径列表 = 加载_env文件(__file__) if 加载_env文件 else _加载环境变量文件()
if 已加载_env路径列表:
    print(f"✅ 已加载环境变量文件: {' , '.join(str(p) for p in 已加载_env路径列表)}")
else:
    print("⚠️ 未找到任何 .env 文件：将只能读取系统环境变量（export 的那种）")

# 自动计算项目根目录 (Quant_Unified)
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]

# 将项目子目录加入搜索路径
for folder in ['基础库', '服务', '策略仓库', '应用']:
    p = PROJECT_ROOT / folder
    if p.exists() and str(p) not in sys.path:
        sys.path.append(str(p))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# ============================================================
# 安全启动检查 (在导入 API 前设置环境变量)
# ============================================================
# 导入策略依赖
from 策略仓库.八号香农策略.config_live import strategy_config as cfg

# ============================================================
# 安全启动检查
# ============================================================
use_real = getattr(cfg, 'USE_REAL_TRADING', False)

if use_real:
    print("\n" + "!"*50)
    print("⚠️  警告: 配置文件显示 [USE_REAL_TRADING=True]")
    print("⚠️  即将连接到币安【实盘】 (Production)！")
    print("!"*50 + "\n")
    try:
        if os.getenv("可以跳过确认") != "yes":
            confirm = input("请输入 'yes' 确认启动实盘: ")
            if confirm != 'yes':
                print("❌ 已取消启动。")
                exit(0)
    except EOFError:
        pass 
    
    os.environ["BINANCE_TESTNET"] = "false"
    print("🚀以此启动: 实盘模式 (Production)")
else:
    os.environ["BINANCE_TESTNET"] = "true"
    os.environ["BINANCE_WS_SSL_VERIFY"] = "false"
    print("🧪以此启动: 测试网模式 (Demo Trading)")
from 策略仓库.八号香农策略.api import binance_raw as api  # 使用原生 requests 版本
from 策略仓库.八号香农策略.api.ws_manager import BinanceWsManager
from 策略仓库.八号香农策略.program.volatility import VolatilityEngine
from 策略仓库.八号香农策略.program.cprp import CPRPEngine
from 策略仓库.八号香农策略.program.leverage_model import resolve_leverage_spec, available_balance
from supabase import create_client, Client

# ==========================================
# 精准盈亏计算 (FIFO)
# ==========================================
class TradeMatcher:
    def __init__(self):
        # 买单队列: [(price, qty), ...]
        self.buy_queue = deque()
        self.total_cost = 0.0
        self.total_qty = 0.0
        
    def add_buy(self, price, qty, *, quiet: bool = False):
        """记录买单"""
        self.buy_queue.append({'price': price, 'qty': qty})
        self.total_qty += qty
        self.total_cost += price * qty
        if not quiet:
            logger.info(f"➕ 记账: 买入 {qty:.4f} @ {price:.2f} (库存: {self.total_qty:.4f})")
        
    def process_sell(self, sell_price, sell_qty, *, quiet: bool = False):
        """处理卖单，计算精准利润 (FIFO)"""
        remaining_sell_qty = sell_qty
        total_profit = 0.0
        matched_cost = 0.0
        
        # 1. 优先匹配队列中的买单
        while remaining_sell_qty > 0 and self.buy_queue:
            buy_order = self.buy_queue[0] # 查看队首
            match_qty = min(remaining_sell_qty, buy_order['qty'])
            
            # 计算这部分的利润
            profit = (sell_price - buy_order['price']) * match_qty
            total_profit += profit
            matched_cost += buy_order['price'] * match_qty
            
            # 更新状态
            remaining_sell_qty -= match_qty
            buy_order['qty'] -= match_qty
            self.total_qty -= match_qty
            self.total_cost -= (buy_order['price'] * match_qty)
            
            # 如果该买单耗尽，移除
            if buy_order['qty'] <= 1e-8:
                self.buy_queue.popleft()
                
        # 2. 如果队列空了还有剩余卖出的量 (说明是底仓或以前的库存)
        # 使用当前持仓均价估算剩余部分
        if remaining_sell_qty > 0:
            if not quiet:
                logger.warning(f"⚠️ 库存不足全额匹配 (缺 {remaining_sell_qty:.4f})，剩余部分无法精准计算")
            
        if not quiet:
            logger.info(f"➖ 记账: 卖出 {sell_qty:.4f} @ {sell_price:.2f} | 匹配成本: {matched_cost:.2f} | 利润: {total_profit:.4f}")
        return total_profit


# ============================================================
# 用户配置区
# ============================================================
INITIAL_CAPITAL = float(getattr(cfg, 'initial_capital', 5000.0))  # 初始本金 (单位需与净值计价币一致)
# ============================================================

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Shannon_Strategy_8")

class ShannonProphet:
    """
    8号香农策略 - 主控类
    """
    def __init__(self):
        self.config = cfg
        self.symbol = self.config.symbol
        self.equity_asset = self._resolve_equity_asset()
        self.leverage_spec = None
        
        # 核心算子
        self.vol_engine = VolatilityEngine(self.config)
        self.cprp_engine = CPRPEngine(self.config)
        
        # 状态缓存
        self.current_price = 0.0
        self.equity_cache = 0.0
        self.available_balance_cache = 0.0
        self.position_cache = 0.0 # 纯数量
        
        # 订单缓存 (Buy, Sell)
        self.active_orders = {'BUY': None, 'SELL': None} # {'id': '...', 'price': 100, 'qty': 0.1}
        
        # 迟滞更新状态
        self.last_grid_width = 0.0
        
        # 控制锁
        self._lock = asyncio.Lock()

        # ============================================================
        # 1m K线收盘驱动（WebSocket）
        # ============================================================
        # 你可以把它理解成“收盘铃声”：
        # - 每一分钟结束，交易所会推送一条“这根 1m K 线已收盘”的消息
        # - 我们用它来喂波动率引擎，并且触发下一分钟的挂单计算
        self._kline_close_queue: asyncio.Queue[tuple[int, float]] = asyncio.Queue(maxsize=10)
        self._last_kline_close_time_ms: int = 0
        
        # Supabase 客户端
        self.supabase: Client = None
        self._init_supabase()
        
        # 缓存持仓均价 (用于计算盈亏)
        self.entry_price_cache = 0.0
        
        # 初始化交易匹配器 (精准盈亏计算)
        self.trade_matcher = TradeMatcher()

        # ============================================================
        # 成交账本（持久化到本地文件）
        # ============================================================
        # 目的：脚本重启后也能“从真实成交历史”重建 FIFO 队列，保证利润提示不丢失。
        self._ledger_path: Path = Path(__file__).resolve().parent / f"成交账本_{self.symbol}.jsonl"
        self._ledger_last_trade_id: int = 0
        self._ledger_lock = asyncio.Lock()

    def _init_supabase(self):
        """初始化 Supabase 客户端"""
        try:
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
            if url and key:
                self.supabase = create_client(url, key)
                logger.info("✅ Supabase 连接成功")
            else:
                logger.warning("⚠️ 未配置 Supabase URL/KEY，将无法上报数据")
        except Exception as e:
            logger.error(f"Supabase 初始化失败: {e}")

    async def _log_to_supabase(self, regime, width):
        """上报策略状态到 Supabase"""
        if not self.supabase:
            return
            
        try:
            # 构造数据
            data = {
                "timestamp": datetime.now().isoformat(),
                "symbol": self.symbol,
                "price": self.current_price,
                "equity": self.equity_cache, # 净值 (包含未实现盈亏)
                "available": self.available_balance_cache,
                "position": self.position_cache,
                "regime": regime,
                "grid_width": width,
                "leverage_real": self.leverage_spec.position_leverage if self.leverage_spec else 0,
                "roi": (self.equity_cache - INITIAL_CAPITAL) / INITIAL_CAPITAL if INITIAL_CAPITAL else 0
            }
            
            # 异步写入 (使用 asyncio.to_thread 避免阻塞主循环)
            # 目标表: strategy_logs (如果没有这个表需要用户创建)
            await asyncio.to_thread(
                lambda: self.supabase.table("strategy_logs").insert(data).execute()
            )
            # logger.info("☁️ 数据已上报 Supabase")
        except Exception as e:
            logger.warning(f"数据上报 Supabase 失败: {e}")

    # ============================================================
    # 成交账本 & FIFO 重建
    # ============================================================

    def _读取成交账本最后trade_id(self) -> int:
        """
        读取本地成交账本最后一个 trade id（用于“增量补齐”）。

        trade id 可以理解成“流水号”：越大越新。
        """
        路径 = self._ledger_path
        if not 路径.exists():
            return 0

        last_id = 0
        try:
            with 路径.open("r", encoding="utf-8") as f:
                for line in f:
                    line = (line or "").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        tid = int(obj.get("id", 0))
                        if tid > last_id:
                            last_id = tid
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"读取成交账本失败: {e}")
            return 0
        return last_id

    async def _追加成交到账本(self, trade: dict):
        """把单笔成交追加到本地账本（JSONL：一行一个 JSON）。"""
        if not isinstance(trade, dict):
            return
        tid = int(trade.get("id", 0) or 0)
        if tid <= 0:
            return

        line = json.dumps(trade, ensure_ascii=False)
        路径 = self._ledger_path
        try:
            async with self._ledger_lock:
                if tid <= self._ledger_last_trade_id:
                    return
                路径.parent.mkdir(parents=True, exist_ok=True)

                def _写一行():
                    with 路径.open("a", encoding="utf-8") as f:
                        f.write(line + "\n")

                await asyncio.to_thread(_写一行)
                self._ledger_last_trade_id = tid
        except Exception as e:
            logger.warning(f"写入成交账本失败: {e}")

    async def _首次回溯成交账本(self):
        """
        第一次运行且当前有持仓时：尽量回溯足够久的历史成交，避免 FIFO “缺底仓”。
        """
        target_qty = abs(float(self.position_cache))
        if target_qty <= 1e-12:
            return

        logger.info(f"📒 成交账本初始化: 检测到持仓 {self.position_cache:.4f}，开始回溯历史成交...")

        lookback_days_list = [7, 30, 90, 365, 2000]

        for days in lookback_days_list:
            start_ms = int((datetime.now() - timedelta(days=int(days))).timestamp() * 1000)

            all_trades: list[dict] = []
            from_id: int | None = None

            for _ in range(200):  # 安全上限：最多翻 200 页
                if from_id is None:
                    page = await asyncio.to_thread(api.fetch_user_trades, self.symbol, start_time_ms=start_ms, limit=1000)
                else:
                    page = await asyncio.to_thread(api.fetch_user_trades, self.symbol, from_id=from_id, start_time_ms=start_ms, limit=1000)

                if not page:
                    break

                all_trades.extend(page)
                if len(page) < 1000:
                    break
                from_id = int(page[-1].get("id", 0) or 0) + 1

            if not all_trades:
                continue

            all_trades.sort(key=lambda x: int(x.get("id", 0) or 0))

            # 用“净买入数量”判断这段历史是否足够覆盖当前持仓（粗但实用）
            net_qty = 0.0
            for t in all_trades:
                if str(t.get("positionSide", "BOTH")).upper() == "SHORT":
                    continue
                side = str(t.get("side", "")).upper()
                qty = float(t.get("qty", 0) or 0)
                if qty <= 0:
                    continue
                if side == "BUY":
                    net_qty += qty
                elif side == "SELL":
                    net_qty -= qty

            logger.info(f"📒 回溯{days}天成交: trades={len(all_trades)} | net_qty≈{net_qty:.4f} | pos≈{target_qty:.4f}")

            # 写入/覆盖账本（首次回溯，用“覆盖写”更干净）
            路径 = self._ledger_path
            路径.parent.mkdir(parents=True, exist_ok=True)

            def _覆盖写入():
                with 路径.open("w", encoding="utf-8") as f:
                    for t in all_trades:
                        f.write(json.dumps(t, ensure_ascii=False) + "\n")

            await asyncio.to_thread(_覆盖写入)

            self._ledger_last_trade_id = int(all_trades[-1].get("id", 0) or 0)

            # 如果 net_qty 已经能覆盖当前持仓，通常就够用；否则继续往更久回溯
            if net_qty >= target_qty * 0.98:
                logger.info(f"✅ 成交账本回溯完成：最近 {days} 天已覆盖当前持仓")
                return

        logger.warning("⚠️ 成交账本回溯可能仍不完整：FIFO 利润提示可能会偏差（不影响实际交易）")

    async def _补齐成交账本并重建FIFO(self):
        """
        启动时执行：
        1) 从交易所拉取缺失成交（增量补齐本地账本）
        2) 用账本重建 FIFO 队列（TradeMatcher），避免重启后利润提示“失忆”
        """
        # 1) 先读本地账本最后 id
        self._ledger_last_trade_id = self._读取成交账本最后trade_id()

        # 2) 如果账本不存在且当前无持仓：不必回溯历史（从现在开始记就行）
        if self._ledger_last_trade_id == 0 and abs(float(self.position_cache)) <= 1e-12:
            try:
                self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
                self._ledger_path.touch(exist_ok=True)
            except Exception:
                pass
            logger.info("📒 成交账本初始化: 当前无持仓，跳过历史回溯")
            self.trade_matcher = TradeMatcher()
            return

        # 2.1 第一次运行且当前有持仓：先尽量回溯，避免 FIFO 缺底仓
        if self._ledger_last_trade_id == 0 and abs(float(self.position_cache)) > 1e-12:
            await self._首次回溯成交账本()

        # 3) 增量补齐：从 last_id+1 开始拉
        async def _批量追加(trades: list[dict]):
            if not trades:
                return
            路径 = self._ledger_path
            lines = [json.dumps(t, ensure_ascii=False) + "\n" for t in trades]
            def _追加多行():
                with 路径.open("a", encoding="utf-8") as f:
                    f.writelines(lines)
            await asyncio.to_thread(_追加多行)

        try:
            from_id = self._ledger_last_trade_id + 1 if self._ledger_last_trade_id > 0 else None
            拉取次数 = 0
            while True:
                拉取次数 += 1
                if 拉取次数 > 50:
                    logger.warning("⚠️ 补齐成交账本分页过多，已中止（请检查是否存在异常交易量）")
                    break

                if from_id is None:
                    break

                trades = await asyncio.to_thread(api.fetch_user_trades, self.symbol, from_id=from_id, limit=1000)

                if not trades:
                    break

                # 过滤掉重复（保险）
                trades = [t for t in trades if int(t.get("id", 0) or 0) > self._ledger_last_trade_id]
                if not trades:
                    break

                await _批量追加(trades)
                self._ledger_last_trade_id = int(trades[-1]["id"])
                from_id = self._ledger_last_trade_id + 1

            # 4) 用账本重建 FIFO
            self._从账本重建FIFO()
        except Exception as e:
            logger.warning(f"补齐成交账本失败: {e}")
            # 即使失败，也不影响策略运行；只是利润提示可能不准

    def _从账本重建FIFO(self):
        """用本地成交账本重建 FIFO（静默模式，避免启动时刷屏）。"""
        路径 = self._ledger_path
        if not 路径.exists():
            logger.warning("⚠️ 未找到成交账本文件，无法重建 FIFO")
            return

        matcher = TradeMatcher()
        buy_sum = 0.0
        sell_sum = 0.0
        count = 0

        try:
            with 路径.open("r", encoding="utf-8") as f:
                for line in f:
                    line = (line or "").strip()
                    if not line:
                        continue
                    try:
                        t = json.loads(line)
                    except Exception:
                        continue

                    if t.get("symbol") != self.symbol:
                        continue

                    # hedge 模式下可能会有 SHORT，这里默认只用 LONG/BOTH 来做 FIFO（你当前配置是单向）
                    if str(t.get("positionSide", "BOTH")).upper() == "SHORT":
                        continue

                    side = str(t.get("side", "")).upper()
                    price = float(t.get("price", 0) or 0)
                    qty = float(t.get("qty", 0) or 0)
                    if price <= 0 or qty <= 0:
                        continue

                    if side == "BUY":
                        matcher.add_buy(price, qty, quiet=True)
                        buy_sum += qty
                        count += 1
                    elif side == "SELL":
                        matcher.process_sell(price, qty, quiet=True)
                        sell_sum += qty
                        count += 1
        except Exception as e:
            logger.warning(f"重建 FIFO 失败: {e}")
            return

        self.trade_matcher = matcher
        logger.info(
            f"✅ FIFO 重建完成 | trades={count} | buy={buy_sum:.4f} | sell={sell_sum:.4f} | "
            f"FIFO库存≈{matcher.total_qty:.4f} | 当前持仓≈{self.position_cache:.4f}"
        )

        # 如果偏差很大，给出提示（不影响运行）
        if abs(abs(float(self.position_cache)) - matcher.total_qty) > max(1e-6, abs(float(self.position_cache)) * 0.05):
            logger.warning("⚠️ FIFO库存 与 当前持仓差异较大：可能账本不完整（建议首次运行时让脚本跑一段时间自动补齐）")

        
    async def initialize(self):
        """初始化"""
        logger.info(f"[{self.symbol}] 正在启动 8号香农策略...")
        logger.info(f"净值计价币: {self.equity_asset} | 初始本金: {INITIAL_CAPITAL:.2f}")

        # 0. 解析杠杆配置（策略口径：X=持仓名义，Y=空闲余额）
        self.leverage_spec = resolve_leverage_spec(
            self.config,
            target_ratio=float(getattr(self.config, 'target_ratio', 0.5)),
            max_position_leverage=getattr(self.config, 'max_position_leverage', None),
        )
        logger.info(
            f"杠杆配置 | 名义W={self.leverage_spec.nominal_leverage:.4f} | "
            f"逐笔Z={self.leverage_spec.position_leverage:.2f}x"
        )

        # 0.1 （可选）自动设置交易所参数（建议先在测试网开启）
        if getattr(self.config, 'auto_set_exchange_settings', False):
            try:
                z_int = int(round(self.leverage_spec.position_leverage))
                z_int = max(1, z_int)
                if abs(z_int - self.leverage_spec.position_leverage) > 1e-9:
                    logger.warning(f"逐笔杠杆需为整数，已四舍五入: {self.leverage_spec.position_leverage} -> {z_int}")
                await asyncio.to_thread(api.set_margin_type, self.symbol, "CROSSED")
                await asyncio.to_thread(api.set_leverage, self.symbol, z_int)
            except Exception as e:
                logger.warning(f"自动设置交易所杠杆/保证金模式失败: {e}")
        
        # 1. 获取初始价格
        price = api.fetch_symbol_price(self.symbol)
        if price > 0:
            self.current_price = price
            logger.info(f"初始价格: {price}")
            
            # 预热波动率引擎 (通常需要历史数据，这里简化，尝试获取最近 1000 根 K 线)
            # 实盘中，更好的是从数据库加载，这里尝试从 API 拉取
            await self._preload_volatility()
        
        # 2. 同步账户状态
        await self._sync_account()

        # 3. 用“真实成交历史”补齐账本，并重建 FIFO（脚本重启不失忆）
        await self._补齐成交账本并重建FIFO()
        
    async def _preload_volatility(self):
        """预加载 K 线数据以初始化波动率"""
        try:
            now = datetime.now()
            # 动态读取 Long Window 配置，只拉取必要数量的 K 线
            需要条数 = getattr(self.config, 'vol_long_window', 1440)
            logger.info(f"正在预加载 {需要条数} 条 K 线数据 (基于 vol_long_window 配置)...")
            
            df = api.fetch_candle_data(self.symbol, now, interval='1m', limit=需要条数)
            if df is not None and not df.empty:
                # 保险：最后一根可能是“正在走的 K 线”，不一定收盘，先丢掉
                df_closed = df.iloc[:-1].copy() if len(df) > 1 else df
                prices = df_closed['close'].values
                for p in prices:
                    self.vol_engine.add_price(p)

                # 记录最后一根“已收盘 K 线”的 close_time，避免 WS 重复推同一根导致重复喂数据
                try:
                    self._last_kline_close_time_ms = int(df_closed['close_time'].iloc[-1])
                except Exception:
                    pass

                logger.info(f"已预加载 {len(prices)} 条 K 线数据。当前状态: {self.vol_engine.get_market_status()}")
        except Exception as e:
            logger.warning(f"预加载波动率数据失败: {e}")

    async def _sync_account(self):
        """同步账户权益和持仓 (API 优化版: 单次请求)"""
        try:
            # 1. 混合查询 (权益 + 持仓)
            # 权重: 5 (以前是 account(5) + position(5) = 10)
            assets_to_try = []
            for asset in [self.equity_asset, 'USDT', 'USDC']:
                asset = str(asset).upper().strip()
                if asset and asset not in assets_to_try:
                    assets_to_try.append(asset)

            data = None
            for asset in assets_to_try:
                data = await asyncio.to_thread(api.fetch_account_status, asset, self.symbol)
                if data:
                    break
            
            if data:
                # 解包数据
                wb = data['wallet_balance']
                upnl = data['unrealized_pnl']
                mb = data['margin_balance']
                ab = data['available_balance']
                
                pos_amt = data.get('position_amt', 0.0)
                pos_entry = data.get('position_entry', 0.0)
                
                # 更新缓存
                self.equity_cache = mb 
                self.available_balance_cache = ab
                self.position_cache = pos_amt
                if pos_entry > 0:
                    self.entry_price_cache = pos_entry
                
                # 计算实盘收益率 (ROI) = (当前净值 - 初始本金) / 初始本金
                # 这是最真实的战绩，无论你中间怎么折腾，都看最后剩多少钱 vs 投入多少钱
                roi = (mb - INITIAL_CAPITAL) / INITIAL_CAPITAL if INITIAL_CAPITAL else 0.0
                
                logger.info(
                    f"账户状态 | "
                    f"净值({data.get('asset', self.equity_asset)}): {mb:.2f} | "
                    f"ROI: {roi:.2%} | "
                    f"持仓: {pos_amt:.4f} (@{pos_entry:.1f})"
                )

                # 杠杆/口径一致性检查（忽略维持保证金/资金费等差异）
                if self.current_price > 0 and self.leverage_spec:
                    notional = abs(pos_amt) * float(self.current_price)
                    ratio = notional / (notional + ab) if (notional + ab) > 1e-12 else 0.0
                    y_model = available_balance(mb, notional, self.leverage_spec.position_leverage)
                    logger.info(
                        f"口径检查 | X(名义)={notional:.2f} | Y(空闲)={ab:.2f} | "
                        f"X/(X+Y)={ratio:.2%} (target={getattr(self.config,'target_ratio',0.5):.0%}) | "
                        f"Y_model≈{y_model:.2f}"
                    )
            else:
                logger.warning("账户同步: 获取失败")
            
        except Exception as e:
            logger.error(f"账户同步失败: {e}")

    def _resolve_equity_asset(self) -> str:
        """确定账户净值计价币：优先读配置，其次从交易对尾缀推断。"""
        configured = (
            getattr(self.config, 'equity_asset', None)
            or getattr(self.config, 'margin_asset', None)
            or getattr(self.config, 'account_asset', None)
        )
        if configured:
            return str(configured).upper().strip()

        symbol = str(getattr(self.config, 'symbol', '') or '').upper().strip()
        if not symbol:
            return 'USDT'

        # 常见计价币尾缀（按长度降序，避免误匹配）
        common_quotes = ['FDUSD', 'USDT', 'USDC', 'BUSD', 'TUSD', 'USDP', 'DAI', 'USD']
        common_quotes.sort(key=len, reverse=True)
        for quote in common_quotes:
            if symbol.endswith(quote):
                return quote

        return 'USDT'

    async def on_price_update(self, price: float):
        """
        价格更新回调 (每分钟或实时)
        这里我们假设是 1s 一次或者 WebSocket 推送
        """
        if price <= 0: return
        self.current_price = price
        
        async with self._lock:
            # 1. 更新波动率
            # 注意: VolEngine 是基于 min-bar returns 的。如果传入的是 tick，需要 resample
            # 简化起见：我们记录每一笔 tick ? 不，标准差会失真。
            # 应该每分钟调用一次 add_price，或者 VolEngine 内部处理。
            # 这里我们让外部循环控制频率，或者简单地每 60s 采样一次。
            # 为了自适应，我们在主循环做定时采样。这里只更新缓存。
            pass

    async def 推送_1m收盘K线(self, close_price: float, close_time_ms: int):
        """
        WebSocket 收到 1 分钟 K 线“收盘”事件时调用。

        close_time_ms：毫秒时间戳（交易所给的时间，最权威）
        """
        if close_price <= 0:
            return
        if close_time_ms <= 0:
            return
        if close_time_ms <= self._last_kline_close_time_ms:
            return

        self._last_kline_close_time_ms = close_time_ms

        # 队列满了就丢掉最旧的一根（策略只关心最新的收盘）
        if self._kline_close_queue.full():
            try:
                self._kline_close_queue.get_nowait()
            except Exception:
                pass

        await self._kline_close_queue.put((close_time_ms, float(close_price)))

    async def logic_loop(self):
        """
        主逻辑循环（由 1m K线收盘事件驱动）

        解释一下为什么不用 `sleep(60)`：
        - `sleep(60)` 像是“闹钟”，时间会漂移（网络卡一下就错过节拍）
        - K线收盘推送像是“学校下课铃”，每分钟准时响一次，更贴近真实行情节奏
        """
        async def _rest补一根已收盘K线() -> tuple[int, float]:
            """
            兜底：如果 WS 卡住了，用 REST 拉最近 2 根 1m K 线，取倒数第 2 根（已收盘）。

            这样做的原因（人话）：
            - WS 像“电话”，极少数时候会断线/静音
            - REST 像“短信”，虽然慢一点，但可以当备用
            """
            try:
                now = datetime.now()
                df = await asyncio.to_thread(api.fetch_candle_data, self.symbol, now, interval="1m", limit=2)
                if df is None or df.empty or len(df) < 2:
                    return 0, 0.0
                row = df.iloc[-2]
                close_price = float(row["close"])
                close_time_ms = int(row["close_time"])
                if close_time_ms <= self._last_kline_close_time_ms:
                    return 0, 0.0
                return close_time_ms, close_price
            except Exception as e:
                logger.warning(f"REST 补 K 线失败: {e}")
                return 0, 0.0

        while True:
            try:
                # 1) 等待下一根“1m K线收盘”
                try:
                    close_time_ms, close_price = await asyncio.wait_for(self._kline_close_queue.get(), timeout=90)
                except asyncio.TimeoutError:
                    logger.warning("⚠️ 90秒未收到 1m K线收盘推送，尝试用 REST 补一根...")
                    close_time_ms, close_price = await _rest补一根已收盘K线()
                    if close_price <= 0:
                        continue

                self.current_price = close_price

                # 2) 用“收盘价”喂波动率引擎（这是你想要的对齐口径）
                self.vol_engine.add_price(close_price, close_time_ms / 1000.0)

                # 3) 获取市场状态 & 网格宽度
                status = self.vol_engine.get_market_status()
                current_width_pct = status["final_width"]
                regime = status["regime"]

                # 4) 同步最新账户状态（权益可能变化）
                await self._sync_account()

                # 4.1 上报数据到 Supabase（每分钟）
                await self._log_to_supabase(regime, current_width_pct)

                # 5) 计算理想挂单（用中心价减少噪音）
                center_price = self._get_center_price()
                buy_order, sell_order = self.cprp_engine.calculate_rebalance(
                    center_price,
                    self.position_cache,
                    self.equity_cache,
                    current_width_pct,
                )

                # 6) 迟滞更新判断（避免频繁撤单）
                should_update = False

                # 6.1 成交后立刻补单（用“仓位变化”判断）
                if hasattr(self, "last_position") and self.position_cache != self.last_position:
                    logger.info(f"触发更新: 仓位变化 {self.last_position:.4f} -> {self.position_cache:.4f} (有成交!)")
                    should_update = True
                self.last_position = self.position_cache

                # 6.2 网格宽度变化过大
                width_diff_ratio = 0.0
                if self.last_grid_width > 0:
                    width_diff_ratio = abs(current_width_pct - self.last_grid_width) / self.last_grid_width

                update_thresh = getattr(self.config, "update_threshold_ratio", 0.2)
                if not should_update and width_diff_ratio > update_thresh:
                    logger.info(f"触发更新: 网格宽度变化 {width_diff_ratio:.2%} > {update_thresh:.2%}")
                    should_update = True
                elif not should_update and regime == "SPIKE" and self.last_grid_width != current_width_pct:
                    logger.info("触发更新: SPIKE 状态积极风控")
                    should_update = True
                elif not should_update and not self.active_orders["BUY"] and buy_order:
                    logger.info("触发更新: 缺少买单")
                    should_update = True
                elif not should_update and not self.active_orders["SELL"] and sell_order:
                    logger.info("触发更新: 缺少卖单")
                    should_update = True

                # 6.3 价格偏离检测（用交易所当前挂单 vs 理想挂单对比）
                if not should_update:
                    try:
                        current_orders = await asyncio.to_thread(api.fetch_open_orders, self.symbol)
                        ideal_buy_price = buy_order[0]["price"] if buy_order else None
                        ideal_sell_price = sell_order[0]["price"] if sell_order else None
                        for order in current_orders:
                            order_price = order["price"]
                            if order["side"] == "BUY" and ideal_buy_price:
                                deviation = abs(order_price - ideal_buy_price) / ideal_buy_price
                                if deviation > 0.5:
                                    logger.info(f"触发更新: 买单价格偏离过大 {deviation:.2%}")
                                    should_update = True
                                    break
                            elif order["side"] == "SELL" and ideal_sell_price:
                                deviation = abs(order_price - ideal_sell_price) / ideal_sell_price
                                if deviation > 0.5:
                                    logger.info(f"触发更新: 卖单价格偏离过大 {deviation:.2%}")
                                    should_update = True
                                    break
                    except Exception as e:
                        logger.warning(f"价格偏离检测失败: {e}")

                if should_update:
                    await self.execute_orders(buy_order, sell_order)
                    self.last_grid_width = current_width_pct
                else:
                    logger.info(f"保持静默 | Regime: {regime} | Width: {current_width_pct:.4%} | Pos: {self.position_cache}")

            except Exception as e:
                logger.error(f"逻辑循环异常: {e}")

    def _get_center_price(self):
        """
        计算中心价 (平滑处理)
        P_center = 0.5 * P_last + 0.5 * P_ewma
        """
        if self.vol_engine.ewma_price > 0:
            return 0.5 * self.current_price + 0.5 * self.vol_engine.ewma_price
        return self.current_price

    async def _check_depth_and_place(self, side, price, quantity, depth_cache=None):
        """
        下单逻辑 (已禁用拆单/冰山订单)
        :param side: 'BUY' or 'SELL'
        :param price: Base Price
        :param quantity: Total Quantity
        :param depth_cache: (已弃用)
        """
        if quantity <= 0:
            return

        # 用户明确要求禁用盘口检测和拆单
        # Reason: "我就这么点资金完全用不到冰山订单"
        split_orders = False
        
        # 直接执行单笔下单
        # 读取配置：post_only=False 表示普通限价单（可能以Taker成交）
        #          post_only=True  表示只做Maker（越过盘口会拒单报错 -5022）
        post_only = getattr(self.config, 'post_only', False)
        try:
            hedge_mode = getattr(self.config, 'hedge_mode', False)
            if hedge_mode:
                pos_side = 'LONG' if side == 'BUY' else 'SHORT'
                await asyncio.to_thread(api.place_limit_order, self.symbol, side, price, quantity, position_side=pos_side, post_only=post_only)
            else:
                await asyncio.to_thread(api.place_limit_order, self.symbol, side, price, quantity, post_only=post_only)
            logger.info(f"挂单成功: {side} {price:.2f} x {quantity:.4f}")
        except Exception as e:
            错误信息 = str(e)
            if "-5022" in 错误信息:
                logger.warning(f"挂单被拒 (Post-Only模式): 价格越过盘口，无法作为Maker成交。可在 config_live.py 设置 post_only=False 使用普通限价单。")
            elif "-1007" in 错误信息:
                logger.error(f"挂单失败 (币安服务端响应超时，非本机问题): {e}")
            else:
                logger.error(f"挂单失败: {e}")

    async def execute_orders(self, ideal_buy_list, ideal_sell_list):
        """执行订单更新 (撤销旧单 -> 挂新单) - 支持多层挂单"""
        logger.info(">>> 开始调整挂单...")
        
        try:
            # 撤销所有订单 (PAPI/FAPI)
            await asyncio.to_thread(api.cancel_all_orders, self.symbol)
            self.active_orders['BUY'] = None
            self.active_orders['SELL'] = None
        except Exception as e:
            logger.error(f"撤单失败: {e}")
            return

        # 挂新单 (循环处理多层)
        # 兼容处理: 如果传入的是单个 dict (旧逻辑残留)，转为 list
        if isinstance(ideal_buy_list, dict): ideal_buy_list = [ideal_buy_list]
        if isinstance(ideal_sell_list, dict): ideal_sell_list = [ideal_sell_list]
        
        # 记录第一层订单作为主要参考 (用于后续的 diff check)
        # 注意: active_orders['BUY'] 仅用于逻辑判断"是否挂了单"，存第一层足矣
        
        if ideal_buy_list:
            for order in ideal_buy_list:
                await self._check_depth_and_place('BUY', order['price'], order['qty'])
            self.active_orders['BUY'] = ideal_buy_list[0]

        if ideal_sell_list:
            for order in ideal_sell_list:
                await self._check_depth_and_place('SELL', order['price'], order['qty'])
            self.active_orders['SELL'] = ideal_sell_list[0]

async def main():
    trader = ShannonProphet()
    await trader.initialize()
    
    # 启动 WebSocket 管理器
    # - 用户数据流：订单/成交推送（ORDER_TRADE_UPDATE）
    # - 行情流：1m K线收盘推送（kline_1m），用来驱动波动率与决策
    ws_manager = BinanceWsManager(symbols=[trader.symbol], market_stream_kind="kline_1m")
    
    # 定义 WS 回调处理函数
    async def handle_ws_message(msg):
        """
        处理 WS 消息
        """
        try:
            if not isinstance(msg, dict):
                return
            
            # 跳过非行情消息 (Account Update 仍跳过，但 ORDER_TRADE_UPDATE 要处理)
            event_type = msg.get('e', '')
            
            if event_type == 'kline':
                # 1m K线更新（只在“收盘”时触发策略）
                k = msg.get('k', {}) or {}
                is_closed = bool(k.get('x', False))
                if is_closed:
                    try:
                        close_price = float(k.get('c', 0))
                        close_time_ms = int(k.get('T', 0))
                    except (ValueError, TypeError):
                        return
                    await trader.推送_1m收盘K线(close_price, close_time_ms)
                return

            if event_type == 'ORDER_TRADE_UPDATE':
                # 处理订单成交回报
                order_data = msg.get('o', {})
                if order_data.get('x') == 'TRADE': # 只关心成交事件
                    symbol = order_data.get('s')
                    side = order_data.get('S')
                    price = float(order_data.get('L', 0))
                    qty = float(order_data.get('l', 0))
                    realized_profit = float(order_data.get('rp', 0)) # 只有平仓才有 realized profit

                    # 1) 把“真实成交”写入本地账本（脚本重启也不丢）
                    try:
                        trade_id = int(order_data.get("t", 0) or 0)
                        trade_time_ms = int(order_data.get("T", 0) or 0)
                        order_id = int(order_data.get("i", 0) or 0)
                        position_side = str(order_data.get("ps", "BOTH") or "BOTH")
                        commission = float(order_data.get("n", 0) or 0)
                        commission_asset = str(order_data.get("N", "") or "")
                        is_maker = bool(order_data.get("m", False))
                        await trader._追加成交到账本(
                            {
                                "id": trade_id,
                                "time": trade_time_ms,
                                "orderId": order_id,
                                "symbol": symbol,
                                "side": side,
                                "positionSide": position_side,
                                "price": price,
                                "qty": qty,
                                "realizedPnl": float(order_data.get("rp", 0) or 0),
                                "commission": commission,
                                "commissionAsset": commission_asset,
                                "maker": is_maker,
                            }
                        )
                    except Exception as e:
                        logger.debug(f"写入成交账本失败(可忽略): {e}")
                    
                    # [精准] 本地 FIFO 盈亏计算
                    # 优先记录买单，卖出时进行队列匹配
                    if side == 'BUY':
                        trader.trade_matcher.add_buy(price, qty)
                    elif side == 'SELL':
                        if realized_profit <= 0:
                            # 即使 API 返回 0，我们也尝试用 FIFO 计算精准网格利润
                            realized_profit = trader.trade_matcher.process_sell(price, qty)
                    
                    profit_msg = ""
                    if realized_profit > 0:
                        profit_msg = f" | 💰 盈利: {realized_profit:.4f} U"
                    elif realized_profit < 0:
                        profit_msg = f" | ⚠️ 亏损: {abs(realized_profit):.4f} U"
                    
                    logger.info(f"⚡️ 订单成交: {side} {symbol} {qty} @ {price}{profit_msg}")
                    
                    # 如果是卖单，通常意味着网格套利成功，可以打印更显眼的提示
                    if side == 'SELL' and realized_profit > 0:
                        logger.info(f"🎉 网格套利成功! 落袋为安: {realized_profit:.4f} U")
                return

            if event_type in ['ACCOUNT_UPDATE', 'listenKeyExpired']:
                # 这些是用户数据推送，不是行情，跳过
                return
        except Exception as e:
            logger.error(f"WS 消息处理异常: {e}")

    ws_manager.add_listener(handle_ws_message)
    
    # 启动 WS
    ws_task = asyncio.create_task(ws_manager.start())
    
    # 启动主逻辑循环
    logic_task = asyncio.create_task(trader.logic_loop())
    
    logger.info("策略主循环与 WebSocket 数据流已启动")
    
    try:
        await asyncio.gather(ws_task, logic_task)
    except Exception as e:
        logger.error(f"主程序异常: {e}")
    finally:
        await ws_manager.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("策略已停止")
