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

import argparse

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
        
        # 核心算子
        self.vol_engine = VolatilityEngine(self.config)
        self.cprp_engine = CPRPEngine(self.config)
        
        # 状态缓存
        self.current_price = 0.0
        self.equity_cache = 0.0
        self.position_cache = 0.0 # 纯数量
        
        # 订单缓存 (Buy, Sell)
        self.active_orders = {'BUY': None, 'SELL': None} # {'id': '...', 'price': 100, 'qty': 0.1}
        
        # 迟滞更新状态
        self.last_grid_width = 0.0
        
        # 控制锁
        self._lock = asyncio.Lock()
        
    async def initialize(self):
        """初始化"""
        logger.info(f"[{self.symbol}] 正在启动 8号香农策略...")
        logger.info(f"净值计价币: {self.equity_asset} | 初始本金: {INITIAL_CAPITAL:.2f}")
        
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
            # 获取最近 1440 分钟数据 (满足 Long Window)
            df = api.fetch_candle_data(self.symbol, now, interval='1m', limit=1440)
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
                self.position_cache = pos_amt
                
                # 计算实盘收益率 (ROI) = (当前净值 - 初始本金) / 初始本金
                # 这是最真实的战绩，无论你中间怎么折腾，都看最后剩多少钱 vs 投入多少钱
                roi = (mb - INITIAL_CAPITAL) / INITIAL_CAPITAL if INITIAL_CAPITAL else 0.0
                
                logger.info(
                    f"账户状态 | "
                    f"净值({data.get('asset', self.equity_asset)}): {mb:.2f} | "
                    f"ROI: {roi:.2%} | "
                    f"持仓: {pos_amt:.4f} (@{pos_entry:.1f})"
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
        try:
            hedge_mode = getattr(self.config, 'hedge_mode', False)
            if hedge_mode:
                pos_side = 'LONG' if side == 'BUY' else 'SHORT'
                await asyncio.to_thread(api.place_limit_order, self.symbol, side, price, quantity, position_side=pos_side, post_only=True)
            else:
                await asyncio.to_thread(api.place_limit_order, self.symbol, side, price, quantity, post_only=True)
            logger.info(f"挂单成功: {side} {price:.2f} x {quantity:.4f}")
        except Exception as e:
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
            
            # 跳过非行情消息 (如订单更新、账户更新等)
            event_type = msg.get('e', '')
            if event_type in ['ORDER_TRADE_UPDATE', 'ACCOUNT_UPDATE', 'listenKeyExpired']:
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
