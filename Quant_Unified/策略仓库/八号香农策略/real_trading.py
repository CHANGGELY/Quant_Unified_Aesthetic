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

# 导入策略依赖
from 策略仓库.八号香农策略.config_live import strategy_config as cfg
from 策略仓库.八号香农策略.api import binance as api
from 策略仓库.八号香农策略.api.ws_manager import BinanceWsManager
from 策略仓库.八号香农策略.program.volatility import VolatilityEngine
from 策略仓库.八号香农策略.program.cprp import CPRPEngine

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
        """同步账户权益和持仓"""
        try:
            # 获取权益 (USDT/USDC)
            # 注意: 这里假设是单币种本位，或者统一账户
            equity = api.fetch_account_equity('USDC') # 优先 USDC，因为是 ETH/USDC
            if equity <= 0: 
                equity = api.fetch_account_equity('USDT')
            
            self.equity_cache = equity
            
            # 获取持仓
            pos_data = api.fetch_position(self.symbol)
            self.position_cache = pos_data['amount']
            
            logger.info(f"账户同步 | 净值: {self.equity_cache:.2f} | 持仓: {self.position_cache:.4f} ETH")
        except Exception as e:
            logger.error(f"账户同步失败: {e}")

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
                # 1. 采样价格并更新波动率
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
                
                # 检查宽度变化
                width_diff_ratio = 0.0
                if self.last_grid_width > 0:
                    width_diff_ratio = abs(current_width_pct - self.last_grid_width) / self.last_grid_width
                
                update_thresh = getattr(self.config, 'update_threshold_ratio', 0.2)
                
                if width_diff_ratio > update_thresh:
                    logger.info(f"触发更新: 网格宽度变化 {width_diff_ratio:.2%} > {update_thresh:.2%}")
                    should_update = True
                elif regime == 'SPIKE' and self.last_grid_width != current_width_pct:
                    # SPIKE 状态下稍微变动就立即更新 (防穿仓)
                    logger.info("触发更新: SPIKE 状态积极风控")
                    should_update = True
                elif not self.active_orders['BUY'] and buy_order:
                    # 缺单补单
                    should_update = True
                elif not self.active_orders['SELL'] and sell_order:
                    should_update = True
                
                # 还可以检查价格偏离度 (如果当前挂单价格和理想价格差太远)
                # ... 暂时省略，依赖宽度变化
                
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

    async def _check_depth_and_place(self, side, price, quantity):
        """
        检查盘口深度并下单 (拆单逻辑)
        :param side: 'BUY' or 'SELL'
        :param price: Base Price
        :param quantity: Total Quantity
        """
        if quantity <= 0:
            return

        # 1. 获取盘口深度 (Top 5)
        try:
            depth = await asyncio.to_thread(api.exchange.fetch_order_book, self.symbol, 5)
        except Exception as e:
            logger.warning(f"获取盘口深度失败: {e}，将采用单笔挂单")
            depth = None

        split_orders = False
        top_qty = 0.0
        
        if depth:
            if side == 'BUY':
                # 挂买单，参考卖盘深度(防止吃单)还是买盘深度(防止墙太厚)?
                # 用户说: "如果你想买10个ETH，但现在卖一价上只有1个..." -> 指的是 Taker 吃单风险
                # 但我们是 Maker。
                # "盘口深度监测：挂单前检查当前盘口 P_ask / P_bid 位置的深度"
                # "若挂单量 > 深度的 50%，则拆分挂单"
                # 解释: 如果我在 Best Bid 挂单，而 Best Bid 只有 1 个 ETH，我挂 10 个，我变成了一个巨型墙 (Iceberg needed)。
                # 或者: 我挂单价格如果是 P_bid，我应该检查 P_bid 这一档的深度？
                # 用户意图应该是：不要制造巨大的 Buy Wall 或 Sell Wall，也不要试图一次性吞噬(如果误操作成Taker)。
                # 这里我们检查同方向的 Best 深度。
                bids = depth.get('bids', [])
                if bids:
                    top_qty = bids[0][1] # [Price, Qty]
            else:
                asks = depth.get('asks', [])
                if asks:
                    top_qty = asks[0][1]

            if top_qty > 0 and quantity > 0.5 * top_qty:
                split_orders = True
                logger.info(f"[{side}] 挂单量 {quantity:.4f} > 50% 盘口首层 {top_qty:.4f}，触发拆单")

        # 2. 执行下单
        tick_size = 0.01  # 需从 exchange info 获取，这里简化假设或从 config 读
        # 正确做法: api._get_filters (需暴露或再次获取)
        tick, _, _ = api._get_filters(self.symbol)
        if tick: tick_size = float(tick)

        if split_orders:
            # 拆分 3 笔: 30%, 30%, 40%
            # 价格递减 (Buy) 或 递增 (Sell) 以分散压力
            q1 = quantity * 0.3
            q2 = quantity * 0.3
            q3 = quantity - q1 - q2
            
            orders_to_place = []
            if side == 'BUY':
                # 买单向下铺: P, P-Tick, P-2Tick
                orders_to_place.append((price, q1))
                orders_to_place.append((price - tick_size, q2))
                orders_to_place.append((price - 2 * tick_size, q3))
            else:
                # 卖单向上铺: P, P+Tick, P+2Tick
                orders_to_place.append((price, q1))
                orders_to_place.append((price + tick_size, q2))
                orders_to_place.append((price + 2 * tick_size, q3))
            
            for p, q in orders_to_place:
                try:
                    await asyncio.to_thread(api.place_limit_order, self.symbol, side, p, q, post_only=True)
                    logger.info(f"  -> 拆单成功: {side} {p:.2f} x {q:.4f}")
                except Exception as e:
                    logger.error(f"  -> 拆单失败: {e}")
        else:
            # 单笔
            try:
                await asyncio.to_thread(api.place_limit_order, self.symbol, side, price, quantity, post_only=True)
                logger.info(f"挂单成功: {side} {price:.2f} x {quantity:.4f}")
            except Exception as e:
                logger.error(f"挂单失败: {e}")

    async def execute_orders(self, ideal_buy, ideal_sell):
        """执行订单更新 (撤销旧单 -> 挂新单)"""
        logger.info(">>> 开始调整挂单...")
        
        try:
            # 撤销所有订单 (PAPI/FAPI)
            await asyncio.to_thread(api.cancel_all_orders, self.symbol)
            self.active_orders['BUY'] = None
            self.active_orders['SELL'] = None
        except Exception as e:
            logger.error(f"撤单失败: {e}")
            # 继续尝试挂单，或者直接返回? 为了安全建议返回
            return

        # 挂新单 (带深度检查)
        if ideal_buy:
             await self._check_depth_and_place('BUY', ideal_buy['price'], ideal_buy['qty'])
             self.active_orders['BUY'] = ideal_buy # 记录主要信息

        if ideal_sell:
             await self._check_depth_and_place('SELL', ideal_sell['price'], ideal_sell['qty'])
             self.active_orders['SELL'] = ideal_sell

async def main():
    trader = ShannonProphet()
    await trader.initialize()
    
    # 启动 WS (可选，用于实时更新价格，这里为了简化先只用 Polling 或者 Logic Loop 内的 Sample)
    # 按照设计 logic_loop 每分钟跑一次并 update volatility
    # 但我们需要实时价格来计算 calculate_rebalance? No, rebalance is also minutely.
    # 所以简单的 Loop 足够。
    
    # 如果要更实时的价格，可以开一个 task 持续 fetch price
    async def price_updater():
        while True:
            try:
                p = api.fetch_symbol_price(trader.symbol)
                await trader.on_price_update(p)
            except Exception:
                pass
            await asyncio.sleep(5) # 5秒更新一次价格用于显示

    task1 = asyncio.create_task(trader.logic_loop())
    task2 = asyncio.create_task(price_updater())
    
    await asyncio.gather(task1, task2)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("策略已停止")
