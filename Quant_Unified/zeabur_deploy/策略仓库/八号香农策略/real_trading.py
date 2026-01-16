# -*- coding: utf-8 -*-
"""
8号香农策略 - 自适应被动 Maker CPRP
Quant_Unified/策略仓库/八号香农策略/real_trading.py
"""
import time
import os
import asyncio
import logging
import sys
from pathlib import Path
from datetime import datetime
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


已加载_env路径列表 = _加载环境变量文件()
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
        
    def add_buy(self, price, qty):
        """记录买单"""
        self.buy_queue.append({'price': price, 'qty': qty})
        self.total_qty += qty
        self.total_cost += price * qty
        logger.info(f"➕ 记账: 买入 {qty:.4f} @ {price:.2f} (库存: {self.total_qty:.4f})")
        
    def process_sell(self, sell_price, sell_qty):
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
            logger.warning(f"⚠️ 库存不足全额匹配 (缺 {remaining_sell_qty:.4f})，剩余部分无法精准计算")
            
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
        
        # Supabase 客户端
        self.supabase: Client = None
        self._init_supabase()
        
        # 缓存持仓均价 (用于计算盈亏)
        self.entry_price_cache = 0.0
        
        # 初始化交易匹配器 (精准盈亏计算)
        self.trade_matcher = TradeMatcher()

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
        
    async def _preload_volatility(self):
        """预加载 K 线数据以初始化波动率"""
        try:
            now = datetime.now()
            # 动态读取 Long Window 配置，只拉取必要数量的 K 线
            需要条数 = getattr(self.config, 'vol_long_window', 1440)
            logger.info(f"正在预加载 {需要条数} 条 K 线数据 (基于 vol_long_window 配置)...")
            
            df = api.fetch_candle_data(self.symbol, now, interval='1m', limit=需要条数)
            if df is not None and not df.empty:
                prices = df['close'].values
                for p in prices:
                    self.vol_engine.add_price(p)
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

    async def logic_loop(self):
        """
        主逻辑循环 (每分钟执行一次决策)
        """
        while True:
            try:
                # 1. 通过 REST API 获取最新价格 (Weight 1, 每分钟一次)
                # 已移除行情 WS 订阅，改用 REST API 省流量
                try:
                    self.current_price = await asyncio.to_thread(api.fetch_symbol_price, self.symbol)
                except Exception as e:
                    logger.warning(f"获取价格失败: {e}")
                
                # 2. 采样价格并更新波动率
                if self.current_price > 0:
                     self.vol_engine.add_price(self.current_price, time.time())
                
                # 2. 获取市场状态 & 网格宽度
                status = self.vol_engine.get_market_status()
                current_width_pct = status['final_width']
                regime = status['regime']
                
                # 3. 同步最新账户状态 (权益可能变化)
                await self._sync_account()

                # 3.1 上报数据到 Supabase (每分钟)
                await self._log_to_supabase(regime, current_width_pct)
                
                # 4. 计算理想挂单
                # 使用中心价 (P_center) 而非实时 P_market 以减少噪音跟踪
                center_price = self._get_center_price()
                
                buy_order, sell_order = self.cprp_engine.calculate_rebalance(
                    center_price,
                    self.position_cache,
                    self.equity_cache,
                    current_width_pct
                )
                
                # 5. 迟滞更新判断 (Hysteresis)
                # 规则: 
                # (A) 宽度变化 > 20%
                # (B) Regime 突变 (尤其是 Spike)
                # (C) 价格大幅偏离导致订单远离盘口 (Implicitly covered by recalculation?)
                # 我们的策略是：一直挂单。如果新计算的价格/数量和当前挂单差距不大，就不动。
                
                should_update = False
                
                # ====== 新增：仓位变化检测 (最重要！成交后立即补单) ======
                if hasattr(self, 'last_position') and self.position_cache != self.last_position:
                    logger.info(f"触发更新: 仓位变化 {self.last_position:.4f} -> {self.position_cache:.4f} (有成交!)")
                    should_update = True
                self.last_position = self.position_cache
                
                # 检查宽度变化
                width_diff_ratio = 0.0
                if self.last_grid_width > 0:
                    width_diff_ratio = abs(current_width_pct - self.last_grid_width) / self.last_grid_width
                
                update_thresh = getattr(self.config, 'update_threshold_ratio', 0.2)
                
                if not should_update and width_diff_ratio > update_thresh:
                    logger.info(f"触发更新: 网格宽度变化 {width_diff_ratio:.2%} > {update_thresh:.2%}")
                    should_update = True
                elif not should_update and regime == 'SPIKE' and self.last_grid_width != current_width_pct:
                    # SPIKE 状态下稍微变动就立即更新 (防穿仓)
                    logger.info("触发更新: SPIKE 状态积极风控")
                    should_update = True
                elif not should_update and not self.active_orders['BUY'] and buy_order:
                    # 缺单补单
                    logger.info("触发更新: 缺少买单")
                    should_update = True
                elif not should_update and not self.active_orders['SELL'] and sell_order:
                    logger.info("触发更新: 缺少卖单")
                    should_update = True
                
                # ====== 新增：价格偏离检测 ======
                # 如果当前挂单价格与理想价格偏差过大，强制更新
                if not should_update:
                    try:
                        current_orders = await asyncio.to_thread(api.fetch_open_orders, self.symbol)
                        # buy_order / sell_order 现在是列表，取第一层做偏离对比
                        ideal_buy_price = buy_order[0]['price'] if buy_order else None
                        ideal_sell_price = sell_order[0]['price'] if sell_order else None
                        
                        for order in current_orders:
                            order_price = order['price']
                            if order['side'] == 'BUY' and ideal_buy_price:
                                deviation = abs(order_price - ideal_buy_price) / ideal_buy_price
                                if deviation > 0.5:  # 偏差超过 50% 就强制更新
                                    logger.info(f"触发更新: 买单价格偏离过大 {deviation:.2%}")
                                    should_update = True
                                    break
                            elif order['side'] == 'SELL' and ideal_sell_price:
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
            
            # 等待 1 分钟 (标准香农策略不需要高频，利用分钟级波动)
            # 也可以改为 10s，视用户偏好。Prompt 中提到 "每分钟计算一次"。
            await asyncio.sleep(60)

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
    ws_manager = BinanceWsManager(symbols=[trader.symbol])
    
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
            
            if event_type == 'ORDER_TRADE_UPDATE':
                # 处理订单成交回报
                order_data = msg.get('o', {})
                if order_data.get('x') == 'TRADE': # 只关心成交事件
                    symbol = order_data.get('s')
                    side = order_data.get('S')
                    price = float(order_data.get('L', 0))
                    qty = float(order_data.get('l', 0))
                    realized_profit = float(order_data.get('rp', 0)) # 只有平仓才有 realized profit
                    
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
            
            # 兼容 ticker 和 bookTicker
            price = 0.0
            if 'b' in msg and 'a' in msg: # bookTicker
                try:
                    bid = float(msg['b'])
                    ask = float(msg['a'])
                    if bid > 0 and ask > 0:
                        price = (bid + ask) / 2
                except (ValueError, TypeError):
                    return  # 无法解析，跳过
            elif 'c' in msg: # miniTicker / ticker
                try:
                    price = float(msg['c'])
                except (ValueError, TypeError):
                    return
            
            if price > 0:
                await trader.on_price_update(price)
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
