"""
2号网格策略 - 实盘交易脚本 (多币种并行版)
Real Trading Script for Grid Strategy No.2 (Multi-Symbol Support)

功能：
1. 同时运行多个网格策略（支持不同币种、不同方向、不同参数）
2. 共享一个 WebSocket 连接，高效监听所有订单
3. 自动同步账户资金与持仓
4. 支持复利模式
5. 具备断网重连与状态自动恢复功能

使用前请确保环境变量中包含：
export BINANCE_API_KEY="your_api_key"
export BINANCE_SECRET_KEY="your_secret_key"
"""

import time
import os
import json
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path

# 自动计算项目根目录 (Quant_Unified)
# 结构: Quant_Unified/策略仓库/二号网格策略/real_trading.py
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]

# 将项目子目录加入搜索路径，确保中文模块导入正常
for folder in ['基础库', '服务', '策略仓库', '应用']:
    p = PROJECT_ROOT / folder
    if p.exists() and str(p) not in sys.path:
        sys.path.append(str(p))
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.append(str(PROJECT_ROOT))

# 导入配置列表
from 策略仓库.二号网格策略.config_live import live_strategies, TOTAL_CAPITAL_CONFIG
from 策略仓库.二号网格策略.program.step2_strategy import GridStrategy
from 策略仓库.二号网格策略.api import binance as api
from 策略仓库.二号网格策略.api.ws_manager import BinanceWsManager

class _CompatLogger:
    def __init__(self, base_logger):
        self._base = base_logger

    def debug(self, msg, *args, **kwargs):
        return self._base.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        return self._base.info(msg, *args, **kwargs)

    def ok(self, msg, *args, **kwargs):
        return self._base.warning(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        return self._base.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        return self._base.error(msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        return self._base.critical(msg, *args, **kwargs)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
qlogger = _CompatLogger(logger)

POSITION_TOLERANCE_RATIO = float(os.getenv("GRID_POSITION_TOLERANCE_RATIO", "0.01"))
PNL_REPORT_INTERVAL_SECONDS = float(os.getenv("GRID_PNL_REPORT_INTERVAL", "180"))

logs_dir = PROJECT_ROOT / '系统日志'
logs_dir.mkdir(exist_ok=True)
log_file = logs_dir / 'grid_strategy_live.log'

file_handler = RotatingFileHandler(
    str(log_file),
    maxBytes=10 * 1024 * 1024,
    backupCount=3,
    encoding='utf-8',
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

class SingleSymbolTrader:
    """
    单个交易对的网格执行器
    """
    def __init__(self, config, price_cache=None):
        self.config = config
        self.symbol = config.symbol
        self.strategy = GridStrategy(config)
        self.strategy.is_live = True # 开启实盘模式，避免 update_price 产生逻辑成交
        self.price_cache = price_cache if price_cache is not None else {}

        self._global_compound_enabled = bool(getattr(self.config, 'enable_compound', False))
        if self._global_compound_enabled:
            self.strategy.enable_compound = False
        
        # 订单状态跟踪
        self.active_orders = {
            'BUY': {'id': None, 'price': 0, 'qty': 0},
            'SELL': {'id': None, 'price': 0, 'qty': 0}
        }
        self.orders_per_side = int(getattr(self.config, 'orders_per_side', 1) or 1)
        self.reject_counts = {'BUY': 0, 'SELL': 0}
        self._place_lock = asyncio.Lock()
        self._initialize_lock = asyncio.Lock()
        self.expected_orders = {'BUY': True, 'SELL': True}
        self.health_check_needed = True
        self.last_rebuild_ts = 0.0
        self.last_order_op_ts = 0.0
        self.initialized = False
        
        logger.info(f"[{self.symbol}] 策略初始化完成 | 模式: {self.config.direction_mode} | 资金: {self.config.money}")

    @property
    def state_file_path(self):
        # 确保目录存在
        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, 'data')
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        return os.path.join(data_dir, f"{self.symbol}_state.json")

    def save_state(self):
        try:
            state = self.strategy.export_state()
            state['timestamp'] = time.time()
            with open(self.state_file_path, 'w') as f:
                json.dump(state, f, ensure_ascii=False, indent=4, default=str)
        except Exception as e:
            logger.error(f"[{self.symbol}] 保存状态失败: {e}")

    def load_state(self):
        """从文件加载策略状态"""
        try:
            if not os.path.exists(self.state_file_path):
                return False
            
            with open(self.state_file_path, 'r') as f:
                state = json.load(f)
            
            success = self.strategy.import_state(state)
            if success:
                logger.info(f"[{self.symbol}] 成功恢复历史状态 (上次保存: {datetime.fromtimestamp(state.get('timestamp', 0))})")
            return success
        except Exception as e:
            logger.error(f"[{self.symbol}] 加载状态失败: {e}")
            return False

    async def _place_market_like_limit_order(self, side: str, quantity: float, ref_price: float, position_side: str = None):
        loop = asyncio.get_running_loop()

        try:
            maker_bps = float(getattr(self.config, 'market_like_maker_bps', 5) or 5)
        except Exception:
            maker_bps = 5.0
        try:
            aggressive_bps = float(getattr(self.config, 'market_like_aggressive_bps', 5) or 5)
        except Exception:
            aggressive_bps = 5.0
        try:
            maker_timeout_sec = float(getattr(self.config, 'market_like_maker_timeout_sec', 2.0) or 2.0)
        except Exception:
            maker_timeout_sec = 2.0
        try:
            poll_interval_sec = float(getattr(self.config, 'market_like_poll_interval_sec', 0.4) or 0.4)
        except Exception:
            poll_interval_sec = 0.4

        maker_ratio = max(0.0, maker_bps) / 10000.0
        aggressive_ratio = max(0.0, aggressive_bps) / 10000.0

        side_u = (side or '').upper()
        if side_u not in ('BUY', 'SELL'):
            raise ValueError(f"非法 side: {side}")
        if ref_price <= 0 or quantity <= 0:
            raise ValueError(f"非法 ref_price/quantity: price={ref_price}, qty={quantity}")

        prefer_maker = bool(getattr(self.config, 'prefer_maker_for_market_like', True))

        if side_u == 'BUY':
            maker_price = ref_price * (1 - maker_ratio)
            aggressive_price = ref_price * (1 + aggressive_ratio)
        else:
            maker_price = ref_price * (1 + maker_ratio)
            aggressive_price = ref_price * (1 - aggressive_ratio)

        remaining = float(quantity)
        if prefer_maker and maker_timeout_sec > 0:
            try:
                res = await loop.run_in_executor(
                    None,
                    lambda s=self.symbol, sd=side_u, p=maker_price, q=remaining, ps=position_side: api.place_limit_order(
                        s,
                        sd,
                        p,
                        q,
                        position_side=ps,
                        post_only=True,
                    ),
                )
                oid = None
                if isinstance(res, dict):
                    oid = res.get('orderId') or res.get('id')
                if oid:
                    deadline = time.time() + maker_timeout_sec
                    while time.time() < deadline:
                        await asyncio.sleep(poll_interval_sec)
                        try:
                            od = await loop.run_in_executor(None, lambda s=self.symbol, i=str(oid): api.fetch_order(s, i))
                        except Exception:
                            break
                        status = str((od or {}).get('status') or '').lower()
                        try:
                            filled = float((od or {}).get('filled') or 0.0)
                        except Exception:
                            filled = 0.0
                        if status in ('closed', 'filled'):
                            return
                        remaining = max(0.0, float(quantity) - filled)
                        if remaining <= max(1e-10, float(quantity) * 0.001):
                            return

                    try:
                        await loop.run_in_executor(None, lambda s=self.symbol, i=str(oid): api.cancel_order(s, i))
                    except Exception:
                        pass

                    try:
                        od = await loop.run_in_executor(None, lambda s=self.symbol, i=str(oid): api.fetch_order(s, i))
                        try:
                            filled = float((od or {}).get('filled') or 0.0)
                        except Exception:
                            filled = 0.0
                        remaining = max(0.0, float(quantity) - filled)
                    except Exception:
                        remaining = float(quantity)
            except Exception:
                remaining = float(quantity)

        if remaining <= max(1e-10, float(quantity) * 0.001):
            return

        await loop.run_in_executor(
            None,
            lambda s=self.symbol, sd=side_u, p=aggressive_price, q=remaining, ps=position_side: api.place_limit_order(
                s,
                sd,
                p,
                q,
                position_side=ps,
                post_only=False,
            ),
        )

    async def initialize(self):
        """
        初始化/重置：同步持仓，重置网格，清理旧单，挂新单
        此方法在启动时和断线重连后调用
        """
        async with self._initialize_lock:
            logger.info(f"[{self.symbol}] 正在初始化/同步状态...")
            loop = asyncio.get_running_loop()
            try:
                current_price = self.price_cache.get(self.symbol)
                ws_enabled = (os.getenv('BINANCE_WS_ENABLED', 'true').lower() == 'true')
                if not current_price:
                    if ws_enabled:
                        for _ in range(5):
                            if self.symbol in self.price_cache:
                                current_price = self.price_cache[self.symbol]
                                break
                            await asyncio.sleep(1)
                    if not current_price:
                        sp = await loop.run_in_executor(None, lambda: api.fetch_symbol_price(self.symbol))
                        current_price = float(sp or 0)
                        if current_price == 0:
                            tickers = await loop.run_in_executor(None, api.fetch_ticker_price)
                            current_price = float(tickers.get(self.symbol, 0))
                            if current_price == 0:
                                for k, v in tickers.items():
                                    if k.replace('/', '') == self.symbol:
                                        current_price = float(v)
                                        break

                if not current_price:
                    raise ValueError(f"无法获取 {self.symbol} 的当前价格")

                position_data = await loop.run_in_executor(None, lambda: api.fetch_position(self.symbol))

                real_pos_qty = position_data['amount']
                real_entry_price = position_data['entryPrice']

                is_restored = False
                if not self.initialized:
                    is_restored = self.load_state()

                if is_restored:
                    self.strategy.account_dict['positions_qty'] = real_pos_qty
                    if abs(real_pos_qty) > 0:
                        self.strategy.account_dict['avg_price'] = real_entry_price
                    logger.info(f"[{self.symbol}] 历史盈亏数据已恢复 (配对利润: {self.strategy.account_dict.get('pair_profit', 0):.2f})")
                else:
                    self.strategy.account_dict['positions_qty'] = real_pos_qty
                    if abs(real_pos_qty) > 0:
                        self.strategy.account_dict['avg_price'] = real_entry_price

                logger.info(f"[{self.symbol}] 状态同步完成 -> 价格: {current_price} | 持仓: {real_pos_qty} | 均价: {real_entry_price}")

                self.strategy.curr_price = current_price
                self.strategy.init()

                try:
                    one_grid_qty = float(self.strategy.grid_dict.get('one_grid_quantity', 0.0) or 0.0)
                except Exception:
                    one_grid_qty = 0.0
                if one_grid_qty > 0:
                    try:
                        est_grids = int(round(float(real_pos_qty) / one_grid_qty))
                    except Exception:
                        est_grids = 0
                    self.strategy.account_dict['positions_grids'] = est_grids
                else:
                    self.strategy.account_dict['positions_grids'] = 0

                try:
                    rate = self.strategy.get_expected_profit_rate()
                    amt = self.strategy.get_expected_profit_amount()
                    logger.info(f"[{self.symbol}] 预计每格利润率: {rate:.2%} | 金额: {amt:.2f}")
                except Exception:
                    pass

                self.initialized = True

                if self.config.direction_mode == "long" and getattr(self.config, 'auto_build_position', True):
                    if abs(real_pos_qty) < self.strategy.grid_dict['one_grid_quantity'] * 0.5:
                        target_qty = self.strategy.grid_dict['one_grid_quantity']
                        logger.info(f"[{self.symbol}] 检测到持仓不足 (实际: {real_pos_qty:.4f})")
                        logger.info(f"[{self.symbol}] >>> 正在自动市价买入底仓 (1个单位): {target_qty:.4f} ...")
                        try:
                            pos_side = 'LONG' if self.config.direction_mode == 'long' else ('SHORT' if self.config.direction_mode == 'short' else None)
                            await self._place_market_like_limit_order('BUY', target_qty, current_price, position_side=pos_side)
                            logger.info(f"[{self.symbol}] ✅ 底仓补单已发送!")
                            await asyncio.sleep(2)
                        except Exception as e:
                            logger.error(f"[{self.symbol}] 补底仓失败: {e}")

                logger.info(f"[{self.symbol}] 正在同步交易所挂单 (无损模式)...")
                await self.sync_orders_incremental()

                self.last_order_op_ts = time.time()
                self.health_check_needed = True

            except Exception as e:
                logger.error(f"[{self.symbol}] 初始化严重失败: {e}")
                logger.error(">>> 请检查 API Key 权限、IP 白名单或网络连接！策略无法继续运行。")
                raise e

    async def on_order_filled(self, side, fill_price, order_id, filled_qty=None):
        """
        订单成交回调
        """
        async with self._initialize_lock:
            before_pair_profit = float(self.strategy.account_dict.get('pair_profit', 0.0) or 0.0)
            before_pairing_count = int(self.strategy.account_dict.get('pairing_count', 0) or 0)
            fill_msg = f"[成交][{self.symbol}] 订单 {order_id} | {side} 价格 {fill_price} 数量 {filled_qty}"
            qlogger.ok(fill_msg)
            print(fill_msg, flush=True)
            ts = datetime.now()
            self.strategy.curr_price = fill_price
            self.strategy.update_order(ts, fill_price, side, actual_qty=filled_qty)

            after_pair_profit = float(self.strategy.account_dict.get('pair_profit', 0.0) or 0.0)
            after_pairing_count = int(self.strategy.account_dict.get('pairing_count', 0) or 0)
            delta_pair_profit = after_pair_profit - before_pair_profit
            if after_pairing_count > before_pairing_count or abs(delta_pair_profit) > 1e-12:
                msg = (
                    f"[配对成功][{self.symbol}] !!! 本次 {delta_pair_profit:+.4f} | 累计 {after_pair_profit:.4f} | 次数 {after_pairing_count} | 订单 {order_id} | {side} {fill_price:.4f} x {filled_qty}"
                )
                qlogger.ok(msg)
                print(
                    "\n" + "=" * 22 + " 配对成功 " + "=" * 22 + "\n" + msg + "\n" + "=" * 52 + "\n",
                    flush=True,
                )
            else:
                msg = (
                    f"[成交未配对][{self.symbol}] 本次未形成完整配对 | 配对利润 {after_pair_profit:.4f} | 次数 {after_pairing_count} | 订单 {order_id} | {side} {fill_price:.4f} x {filled_qty}"
                )
                qlogger.info(msg)
                print(msg, flush=True)

            if side == 'BUY':
                self.active_orders['BUY'] = {'id': None, 'price': 0}
            else:
                self.active_orders['SELL'] = {'id': None, 'price': 0}

            await self.sync_orders_incremental()

            logger.info(f"[{self.symbol}] 当前持仓: {self.strategy.account_dict['positions_grids']} 格 / 数量: {self.strategy.account_dict['positions_qty']} / 均价: {self.strategy.account_dict['avg_price']:.2f}")
            self.save_state()

    @staticmethod
    def _build_side_orders_from_open_orders(orders):
        side_orders = {'BUY': [], 'SELL': []}
        for o in (orders or []):
            side_val = (o.get('side') or '').upper()
            if side_val not in ('BUY', 'SELL'):
                continue
            try:
                price_val = float(o.get('price') or 0.0)
            except Exception:
                price_val = 0.0
            side_orders[side_val].append({'order': o, 'price': price_val})
        return side_orders

    async def _sync_orders_from_snapshot(self, side_orders, cancel_excess: bool, log_profit: bool = False):
        loop = asyncio.get_running_loop()

        self.update_expected_orders()
        need_buy = self.expected_orders.get('BUY', False)
        need_sell = self.expected_orders.get('SELL', False)
        desired_layers = int(getattr(self.config, 'orders_per_side', 1) or getattr(self, 'orders_per_side', 1) or 1)
        if desired_layers <= 0:
            return False

        interval = self.strategy.grid_dict.get('interval', 0.0)
        mode = getattr(self.strategy, 'interval_mode', None)
        mode_val = getattr(mode, 'value', None) if mode is not None else None
        use_gs = bool(mode_val == 'geometric_sequence')

        tick, _, _ = api._get_filters(self.symbol)
        try:
            tick_size = float(tick) if tick else float(getattr(self.config, 'tick_size', 0.01))
        except Exception:
            tick_size = float(getattr(self.config, 'tick_size', 0.01))

        post_only_flag = getattr(self.config, 'post_only', True)

        if log_profit:
            try:
                rate_est_cached = self.strategy.get_expected_profit_rate()
                amt_est_cached = self.strategy.get_expected_profit_amount()
            except Exception:
                rate_est_cached = 0.0
                amt_est_cached = 0.0
        else:
            rate_est_cached = 0.0
            amt_est_cached = 0.0

        changed = False
        async with self._place_lock:
            for side in ('BUY', 'SELL'):
                need_flag = need_buy if side == 'BUY' else need_sell
                if not need_flag:
                    continue

                existing = side_orders.get(side) or []

                if cancel_excess and len(existing) > desired_layers:
                    descending = side == 'SELL'
                    existing_sorted = sorted(existing, key=lambda x: x['price'], reverse=descending)
                    excess_count = len(existing_sorted) - desired_layers
                    to_cancel = existing_sorted[:excess_count]
                    to_keep = existing_sorted[excess_count:]

                    logger.info(f"[{self.symbol}] 发现多余{side}单: 现有 {len(existing)} > 目标 {desired_layers}，准备撤销 {excess_count} 个远端订单")
                    qlogger.warning(f"[挂单健康][{self.symbol}] 发现多余{side}单: 现有 {len(existing)} > 目标 {desired_layers}，准备撤销 {excess_count} 个远端订单")

                    for item in to_cancel:
                        o = item.get('order') or {}
                        try:
                            oid = o.get('id') or o.get('orderId')
                            if not oid:
                                continue

                            is_conditional = False
                            raw_type = str(o.get('info', {}).get('type', '')).upper()
                            ccxt_type = str(o.get('type', '')).upper()
                            conditional_types = [
                                'STOP', 'STOP_MARKET', 'TAKE_PROFIT', 'TAKE_PROFIT_MARKET',
                                'TRAILING_STOP_MARKET', 'STOP_LOSS', 'STOP_LOSS_LIMIT',
                                'TAKE_PROFIT_LIMIT',
                            ]
                            if raw_type in conditional_types or ccxt_type in conditional_types:
                                is_conditional = True

                            await loop.run_in_executor(None, lambda s=self.symbol, i=oid, c=is_conditional: api.cancel_order(s, i, is_conditional=c))
                            logger.info(f"[{self.symbol}] 已撤销多余单 ({'条件单' if is_conditional else '普通单'}): ID {oid} 价格 {item.get('price')}")
                            changed = True
                        except Exception as e:
                            logger.error(f"[{self.symbol}] 撤销多余单失败: {e}")

                    side_orders[side] = to_keep
                    continue

                if len(existing) >= desired_layers:
                    continue

                descending = side == 'SELL'
                if not existing:
                    if side == 'BUY':
                        base_price = self.strategy.account_dict.get('down_price')
                    else:
                        base_price = self.strategy.account_dict.get('up_price')
                    if not base_price or base_price <= 0:
                        continue
                    existing_sorted = []
                    if use_gs and interval > 0:
                        if side == 'BUY':
                            current_base = base_price * (1 + interval)
                        else:
                            current_base = base_price / (1 + interval)
                    else:
                        if side == 'BUY':
                            current_base = base_price + interval
                        else:
                            current_base = base_price - interval
                else:
                    existing_sorted = sorted(existing, key=lambda x: x['price'], reverse=descending)
                    base_price = existing_sorted[0]['price']
                    current_base = base_price

                missing = desired_layers - len(existing_sorted)
                for _ in range(missing):
                    if use_gs and interval > 0:
                        if side == 'BUY':
                            grid_price = current_base / (1 + interval)
                        else:
                            grid_price = current_base * (1 + interval)
                    else:
                        if side == 'BUY':
                            grid_price = current_base - interval
                        else:
                            grid_price = current_base + interval

                    extra = 1 if self.reject_counts[side] >= int(getattr(self.config, 'post_only_reject_retry_limit', 2)) else 0
                    offset_attr = 'post_only_tick_offset_buy' if side == 'BUY' else 'post_only_tick_offset_sell'
                    eff_offset = int(getattr(self.config, offset_attr, 1)) + extra
                    if post_only_flag:
                        if side == 'BUY':
                            price_new = grid_price - tick_size * eff_offset
                        else:
                            price_new = grid_price + tick_size * eff_offset
                    else:
                        price_new = grid_price

                    all_prices = [e['price'] for e in existing_sorted]
                    if any(abs(price_new - p) < tick_size * 0.5 for p in all_prices):
                        current_base = grid_price
                        continue

                    try:
                        qty = self.strategy.get_current_trade_qty(grid_price)
                    except Exception:
                        qty = 0.0
                    if qty <= 0:
                        current_base = grid_price
                        continue

                    if self.config.direction_mode == 'short' and side == 'BUY':
                        pos_qty = abs(self.strategy.account_dict.get('positions_qty', 0) or 0)
                        if pos_qty > 0:
                            qty = min(qty, pos_qty)
                    if self.config.direction_mode == 'long' and side == 'SELL':
                        pos_qty = abs(self.strategy.account_dict.get('positions_qty', 0) or 0)
                        if pos_qty > 0:
                            qty = min(qty, pos_qty)
                    if qty <= 0:
                        current_base = grid_price
                        continue

                    try:
                        if log_profit:
                            logger.info(f"[{self.symbol}] 额外挂出{side}单: {price_new:.2f} / 数量: {qty:.4f} | 预计每格利润率: {rate_est_cached:.4%} 金额: {amt_est_cached:.2f}")
                        else:
                            logger.info(f"[{self.symbol}] 额外挂出{side}单: {price_new:.2f} / 数量: {qty:.4f}")

                        pos_side = 'LONG' if self.config.direction_mode == 'long' else ('SHORT' if self.config.direction_mode == 'short' else None)
                        await loop.run_in_executor(None, lambda s=self.symbol, p=price_new, q=qty, sd=side, ps=pos_side: api.place_limit_order(s, sd, p, q, position_side=ps, post_only=post_only_flag))
                        existing_sorted.append({'order': None, 'price': price_new})
                        changed = True
                    except Exception as e:
                        msg = str(e)
                        if "-2019" in msg or "Margin is insufficient" in msg:
                            logger.warning(f"[{self.symbol}] ⚠️ 保证金不足 (Code -2019) - 可能是资金被占用或余额不足。")
                        elif "-5022" in msg or "Order would immediately match" in msg:
                            logger.warning(f"[{self.symbol}] ⚠️ 挂单失败 (Post Only): 价格离市场太近，会被判定为吃单。")
                            self.reject_counts[side] += 1
                        logger.error(f"[{self.symbol}] 额外挂{side}单失败: {e}")
                        self.health_check_needed = True
                    current_base = grid_price

        if changed:
            self.last_order_op_ts = time.time()

        return changed

    async def sync_orders_incremental(self):
        loop = asyncio.get_running_loop()
        try:
            orders = await loop.run_in_executor(None, lambda: api.fetch_open_orders(self.symbol))
        except Exception as e:
            logger.error(f"[{self.symbol}] 同步挂单失败: {e}")
            self.health_check_needed = True
            return

        side_orders = self._build_side_orders_from_open_orders(orders)
        changed = await self._sync_orders_from_snapshot(side_orders, cancel_excess=True, log_profit=False)
        self.health_check_needed = bool(changed)

    def update_expected_orders(self):
        down_price = self.strategy.account_dict.get('down_price', 0)
        up_price = self.strategy.account_dict.get('up_price', 0)
        qty_buy = 0.0
        qty_sell = 0.0
        try:
            if down_price > 0:
                qty_buy = float(self.strategy.get_current_trade_qty(down_price))
        except Exception:
            qty_buy = 0.0
        try:
            if up_price > 0:
                qty_sell = float(self.strategy.get_current_trade_qty(up_price))
        except Exception:
            qty_sell = 0.0
        pos_qty = float(self.strategy.account_dict.get('positions_qty', 0.0) or 0.0)
        need_buy = True
        need_sell = True
        if self.config.direction_mode == 'short' and abs(pos_qty) <= 0:
            need_buy = False
        if self.config.direction_mode == 'long' and abs(pos_qty) <= 0:
            need_sell = False
        if qty_buy <= 0:
            need_buy = False
        if qty_sell <= 0:
            need_sell = False
        self.expected_orders['BUY'] = need_buy
        self.expected_orders['SELL'] = need_sell

    async def rebuild_orders(self):
        async with self._initialize_lock:
            loop = asyncio.get_running_loop()
            self.last_rebuild_ts = time.time()
            logger.info(f"[{self.symbol}] 开始执行网格重建...")
            try:
                await loop.run_in_executor(None, lambda: api.cancel_all_orders(self.symbol))
            except Exception as e:
                logger.error(f"[{self.symbol}] 重建网格前撤单失败: {e}")
                self.health_check_needed = True
            self.active_orders['BUY'] = {'id': None, 'price': 0, 'qty': 0}
            self.active_orders['SELL'] = {'id': None, 'price': 0, 'qty': 0}
            self.reject_counts['BUY'] = 0
            self.reject_counts['SELL'] = 0
            try:
                await self.place_orders(strict=True)
                logger.info(f"[{self.symbol}] 网格重建完成")
                qlogger.ok(f"[网格重建][{self.symbol}] 网格重建完成")
                self.last_order_op_ts = time.time()
                self.health_check_needed = True
            except Exception as e:
                logger.error(f"[{self.symbol}] 网格重建失败: {e}")
                self.health_check_needed = True

    async def place_orders(self, strict: bool = False):
        """
        挂出完整的网格单 (Buy & Sell 各 orders_per_side 层)
        """
        target_down = self.strategy.account_dict['down_price']
        target_up = self.strategy.account_dict['up_price']
        
        # 获取网格参数
        desired_layers = int(getattr(self.config, 'orders_per_side', 4) or 4)
        interval = self.strategy.grid_dict.get('interval', 0.0)
        mode = getattr(self.strategy, 'interval_mode', None)
        mode_val = getattr(mode, 'value', None) if mode is not None else None
        use_gs = bool(mode_val == 'geometric_sequence')
        
        loop = asyncio.get_running_loop()

        async with self._place_lock:
            self.update_expected_orders()
            # 统计每个方向实际成功挂出的订单数量，用于 strict 模式下判断是否真正重建成功
            success_counts = {'BUY': 0, 'SELL': 0}

            # 获取当前持仓数量，用于控制平仓单总量 (防止 PAPI -2022 ReduceOnly Rejected)
            current_pos_qty = abs(float(self.strategy.account_dict.get('positions_qty', 0.0) or 0.0))
            remaining_pos_qty_for_close = current_pos_qty
            
            # --- 批量挂买单 ---
            # 只有当允许做多，或者空头平仓需求时才挂买单
            # (简化逻辑: 只要 strategy 说 need_buy 就挂)
            if self.expected_orders['BUY']:
                # 清空本地记录，重新填充
                # 注意: 这里假设调用 place_orders 前已经 cancel_all 了
                
                current_price = target_down
                for i in range(desired_layers):
                    # 计算当前层价格
                    # 第0层就是 target_down
                    # 后续层向下递减
                    if i > 0:
                        if use_gs and interval > 0:
                            current_price = current_price / (1 + interval)
                        else:
                            current_price = current_price - interval
                    
                    if current_price <= 0:
                        break
                        
                    # 计算数量
                    qty = self.strategy.get_current_trade_qty(current_price)
                    if self.config.direction_mode == 'short':
                        if remaining_pos_qty_for_close <= 1e-8:
                            # 剩余持仓不足，跳过后续所有平空单
                            break
                        if qty > remaining_pos_qty_for_close:
                            qty = remaining_pos_qty_for_close
                        remaining_pos_qty_for_close -= qty
                    
                    # 挂单参数
                    tick, _, _ = api._get_filters(self.symbol)
                    try:
                        tick_size = float(tick) if tick else float(getattr(self.config, 'tick_size', 0.01))
                    except Exception:
                        tick_size = float(getattr(self.config, 'tick_size', 0.01))
                        
                    # Post Only 处理 (仅对第0层做特殊 offset 防止吃单，深层网格通常不需要)
                    # 但为了统一，都应用 _adjust_order，这里主要是价格微调
                    # 如果是第0层，且非常接近市价，可能需要 offset
                    price_buy = current_price
                    if i == 0:
                        extra = 1 if self.reject_counts['BUY'] >= int(getattr(self.config, 'post_only_reject_retry_limit', 2)) else 0
                        eff_offset = int(getattr(self.config, 'post_only_tick_offset_buy', 1)) + extra
                        price_buy = price_buy - tick_size * eff_offset

                    # 执行挂单
                    try:
                        precision = getattr(self.config, 'qty_precision', None)
                        if isinstance(precision, int) and precision >= 0:
                            qty_display = f"{qty:.{precision}f}"
                        else:
                            qty_display = f"{qty:.4f}"
                        logger.info(f"[{self.symbol}] 挂买单 #{i+1}: {price_buy:.2f} / 数量: {qty_display}")
                    except Exception:
                        pass
                        
                    try:
                        pos_side = 'LONG' if self.config.direction_mode == 'long' else ('SHORT' if self.config.direction_mode == 'short' else None)
                        res = await loop.run_in_executor(None, lambda p=price_buy, q=qty: api.place_limit_order(self.symbol, 'BUY', p, q, position_side=pos_side, post_only=getattr(self.config, 'post_only', True)))
                        
                        if res and 'orderId' in res:
                            # 记录第一层订单ID用于快速状态检查 (兼容旧逻辑)
                            if i == 0:
                                self.active_orders['BUY'] = {
                                    'id': str(res['orderId']),
                                    'price': price_buy,
                                    'qty': qty
                                }
                            self.reject_counts['BUY'] = 0
                            success_counts['BUY'] += 1
                    except Exception as e:
                        if "-2019" in str(e) or "Margin is insufficient" in str(e):
                            logger.warning(f"[{self.symbol}] ⚠️ 保证金不足 (Code -2019)")
                        elif "-5022" in str(e) or "Order would immediately match" in str(e):
                            logger.warning(f"[{self.symbol}] ⚠️ 挂单失败 (Post Only): 价格离市场太近")
                            if i == 0:
                                self.reject_counts['BUY'] += 1
                        logger.error(f"[{self.symbol}] 挂买单 #{i+1} 失败: {e}")
                        # 不中断循环，尝试挂后续层

            # --- 批量挂卖单 ---
            if self.expected_orders['SELL']:
                current_price = target_up
                for i in range(desired_layers):
                    # 第0层就是 target_up
                    # 后续层向上递增
                    if i > 0:
                        if use_gs and interval > 0:
                            current_price = current_price * (1 + interval)
                        else:
                            current_price = current_price + interval
                            
                    # 计算数量
                    qty = self.strategy.get_current_trade_qty(current_price)
                    if self.config.direction_mode == 'long':
                        if remaining_pos_qty_for_close <= 1e-8:
                            # 剩余持仓不足，跳过后续所有平多单
                            break
                        if qty > remaining_pos_qty_for_close:
                            qty = remaining_pos_qty_for_close
                        remaining_pos_qty_for_close -= qty

                    tick, _, _ = api._get_filters(self.symbol)
                    try:
                        tick_size = float(tick) if tick else float(getattr(self.config, 'tick_size', 0.01))
                    except Exception:
                        tick_size = float(getattr(self.config, 'tick_size', 0.01))

                    price_sell = current_price
                    if i == 0:
                        extra = 1 if self.reject_counts['SELL'] >= int(getattr(self.config, 'post_only_reject_retry_limit', 2)) else 0
                        eff_offset = int(getattr(self.config, 'post_only_tick_offset_sell', 1)) + extra
                        price_sell = price_sell + tick_size * eff_offset

                    try:
                        precision = getattr(self.config, 'qty_precision', None)
                        if isinstance(precision, int) and precision >= 0:
                            qty_display = f"{qty:.{precision}f}"
                        else:
                            qty_display = f"{qty:.4f}"
                        logger.info(f"[{self.symbol}] 挂卖单 #{i+1}: {price_sell:.2f} / 数量: {qty_display}")
                        pos_side = 'LONG' if self.config.direction_mode == 'long' else ('SHORT' if self.config.direction_mode == 'short' else None)
                        res = await loop.run_in_executor(None, lambda p=price_sell, q=qty: api.place_limit_order(self.symbol, 'SELL', p, q, position_side=pos_side, post_only=getattr(self.config, 'post_only', True)))
                        
                        if res and 'orderId' in res:
                            if i == 0:
                                self.active_orders['SELL'] = {
                                    'id': str(res['orderId']),
                                    'price': price_sell,
                                    'qty': qty
                                }
                            self.reject_counts['SELL'] = 0
                            success_counts['SELL'] += 1
                    except Exception as e:
                        if "-2019" in str(e) or "Margin is insufficient" in str(e):
                            logger.warning(f"[{self.symbol}] ⚠️ 保证金不足 (Code -2019)")
                        elif "-5022" in str(e) or "Order would immediately match" in str(e):
                            logger.warning(f"[{self.symbol}] ⚠️ 挂单失败 (Post Only): 价格离市场太近")
                            if i == 0: self.reject_counts['SELL'] += 1
                        logger.error(f"[{self.symbol}] 挂卖单 #{i+1} 失败: {e}")

            # 严格模式下，如果某一侧预期需要挂单但一单未成，则认为本次挂单整体失败
            if strict:
                failed_sides = []
                for side_key in ('BUY', 'SELL'):
                    if self.expected_orders.get(side_key) and success_counts.get(side_key, 0) <= 0:
                        failed_sides.append(side_key)
                if failed_sides:
                    raise RuntimeError(f"place_orders strict 模式失败，以下方向全部挂单失败: {','.join(failed_sides)}")

class MultiSymbolTradingSystem:
    def __init__(self, configs):
        logger.info(">>> 正在初始化多币种实盘交易系统...")
        
        # 验证 API 连接，并计算本次实盘总投入资金与各策略资金分配
        try:
            total_equity = api.fetch_account_equity()
            logger.info(f"账户总净值(含未实现盈亏): {total_equity:.2f}")

            total_config = TOTAL_CAPITAL_CONFIG
            total_capital = 0.0
            if isinstance(total_config, str) and total_config.endswith('%'):
                try:
                    ratio = float(total_config.strip('%')) / 100.0
                except Exception:
                    ratio = 1.0
                total_capital = max(0.0, total_equity * ratio)
            else:
                try:
                    total_capital = float(total_config)
                except Exception:
                    total_capital = 0.0
            if total_capital <= 0:
                total_capital = total_equity

            weight_sum = 0.0
            for cfg in configs:
                w = float(getattr(cfg, 'capital_weight', 1.0) or 0.0)
                if w > 0:
                    weight_sum += w
            if weight_sum <= 0:
                weight_sum = float(len(configs))

            for cfg in configs:
                w = float(getattr(cfg, 'capital_weight', 1.0) or 0.0)
                if w <= 0:
                    continue
                share = total_capital * (w / weight_sum)
                cfg.money = round(share, 2)
                logger.info(f"[{cfg.symbol}] 本次策略分配资金: {cfg.money:.2f}")
        except Exception as e:
            logger.error(f"API 连接或资金分配失败，请检查配置: {e}")
            sys.exit(1)
            
        # 创建交易器实例
        self.traders = {}
        self.latest_prices = {} # 全局价格缓存
        self.last_price_ts = {}
        self.last_rest_fetch_ts = {}
        
        # 收集所有需要监听的 symbols
        active_symbols = []
        
        for cfg in configs:
            if cfg.symbol in self.traders:
                logger.warning(f"重复的配置: {cfg.symbol}，将跳过重复项")
                continue
            self.traders[cfg.symbol] = SingleSymbolTrader(cfg, self.latest_prices)
            active_symbols.append(cfg.symbol)
            
        self.ws_enabled = (os.getenv('BINANCE_WS_ENABLED', 'true').lower() == 'true')
        self.ws_manager = None
        if self.ws_enabled:
            self.ws_manager = BinanceWsManager(symbols=active_symbols)
            self.ws_manager.add_listener(self.dispatch_event)
            self.ws_manager.add_connected_listener(self.on_ws_connected)
        self.symbol_order = list(active_symbols)
        self.strategy_index = {s: i + 1 for i, s in enumerate(self.symbol_order)}

    async def on_ws_connected(self):
        """
        WebSocket 连接成功/重连成功后的回调
        触发所有策略的状态同步
        """
        logger.info(">>> WebSocket 连接建立，触发全策略状态同步...")
        # 重新初始化所有策略 (同步持仓、价格、挂单)
        # 必须并发执行，否则一个阻塞会影响其他
        await asyncio.gather(*(t.initialize() for t in self.traders.values()))

    async def _equity_sync_loop(self):
        """
        后台循环：定期同步账户总净值，并动态调整每个策略的资金分配 (复利模式)
        """
        loop = asyncio.get_running_loop()
        while True:
            try:
                # 1. 获取账户总净值 (Equity)
                total_equity = await loop.run_in_executor(None, api.fetch_account_equity)
                
                if total_equity > 0 and self.traders:
                    total_config = TOTAL_CAPITAL_CONFIG
                    if isinstance(total_config, str) and total_config.endswith('%'):
                        try:
                            ratio = float(total_config.strip('%')) / 100.0
                        except Exception:
                            ratio = 1.0
                        total_capital = max(0.0, total_equity * ratio)
                    else:
                        try:
                            total_capital = float(total_config)
                        except Exception:
                            total_capital = 0.0
                    if total_capital <= 0:
                        total_capital = total_equity

                    weight_sum = 0.0
                    for t in self.traders.values():
                        w = float(getattr(t.config, 'capital_weight', 1.0) or 0.0)
                        if w > 0:
                            weight_sum += w
                    if weight_sum <= 0:
                        weight_sum = float(len(self.traders))

                    for symbol, trader in self.traders.items():
                        if not getattr(trader.config, 'enable_compound', False):
                            continue
                        if getattr(trader, '_initialize_lock', None) and trader._initialize_lock.locked():
                            continue
                        w = float(getattr(trader.config, 'capital_weight', 1.0) or 0.0)
                        if w <= 0:
                            continue
                        allocated_money = round(total_capital * (w / weight_sum), 2)
                        async with trader._place_lock:
                            old_money = float(trader.strategy.money or 0.0)
                            trader.config.money = allocated_money
                            trader.strategy.money = allocated_money
                            if trader.strategy.curr_price > 0:
                                new_qty = trader.strategy.get_one_grid_quantity()
                                trader.strategy.grid_dict["one_grid_quantity"] = new_qty
                                if old_money > 0 and abs(allocated_money - old_money) / old_money > 0.01:
                                    logger.info(f"[{symbol}] 💰 复利资金调整: 总权益 {total_equity:.2f} -> 分配 {allocated_money:.2f} (单格: {new_qty:.4f})")
            
            except Exception as e:
                logger.error(f"同步账户净值失败: {e}")
            
            # 每 60 秒同步一次
            await asyncio.sleep(60)

    async def start(self):
        if not self.traders:
            logger.error("没有有效的策略配置，退出。")
            return

        logger.info(f"=== 启动 {len(self.traders)} 个交易策略 ===")
        
        # 1. 启动 WebSocket 监听 (先行启动，以便接收行情)
        # 启动后，WS 连接成功会再次触发 initialize (状态同步)
        if self.ws_manager:
            asyncio.create_task(self.ws_manager.start())
        asyncio.create_task(self._rest_price_fallback_loop())
        asyncio.create_task(self._order_status_fallback_loop())
        asyncio.create_task(self._equity_sync_loop())
        asyncio.create_task(self._pnl_report_loop())
        asyncio.create_task(self._grid_health_check_loop())
        
        # 2. 初始化所有交易器 (并发)
        # 这里的初始化会尝试利用 WS 推送的价格；如果 WS 尚未就绪，会回退到 REST API
        await asyncio.gather(*(t.initialize() for t in self.traders.values()))
        
        # 3. 保持运行
        while True:
            await asyncio.sleep(60)
            logger.info("--- 系统心跳 ---")
            for symbol, trader in self.traders.items():
                logger.info(f"[{symbol}] 运行中 | 持仓: {trader.strategy.account_dict['positions_grids']} 格")

    async def dispatch_event(self, event):
        """
        分发 WebSocket 事件到对应的交易器
        """
        event_type = event.get('e')
        
        # 1. 处理行情更新 (Ticker)
        if event_type == '24hrTicker':
            symbol = event.get('s')
            last_price = float(event.get('c', 0))
            if symbol and last_price > 0:
                # 更新全局价格缓存
                self.latest_prices[symbol] = last_price
                self.last_price_ts[symbol] = time.time()
                
                # [核心修复] 驱动策略价格更新，以便策略能够感知价格变动并更新网格边界 (up_price/down_price)
                trader = self.traders.get(symbol)
                if trader and trader.initialized:
                    trader.strategy.update_price(datetime.now(), last_price)
            return

        # 2. 处理订单更新 (Order Update)
        if event_type == 'ORDER_TRADE_UPDATE':
            order_data = event.get('o', {})
            symbol = order_data.get('s')
            status = order_data.get('X')
            side = order_data.get('S')
            order_id = str(order_data.get('i'))

            status_u = str(status or '').upper()
            side_u = str(side or '').upper()

            try:
                avg_price = float(order_data.get('ap', 0) or 0)
            except Exception:
                avg_price = 0.0
            try:
                last_fill_price = float(order_data.get('L', 0) or 0)
            except Exception:
                last_fill_price = 0.0

            try:
                cum_filled_qty = float(order_data.get('z', 0) or 0)
            except Exception:
                cum_filled_qty = 0.0
            try:
                orig_qty = float(order_data.get('q', 0) or 0)
            except Exception:
                orig_qty = 0.0
            try:
                last_filled_qty = float(order_data.get('l', 0) or 0)
            except Exception:
                last_filled_qty = 0.0

            # 找到对应的交易器
            trader = self.traders.get(symbol)
            if not trader:
                return

            if status_u == 'FILLED':
                fill_price = avg_price if avg_price > 0 else last_fill_price
                filled_qty = cum_filled_qty if cum_filled_qty > 0 else orig_qty
                if fill_price > 0 and filled_qty > 0:
                    await trader.on_order_filled(side_u, fill_price, order_id, filled_qty)
                return

            if status_u == 'PARTIALLY_FILLED':
                fill_price = last_fill_price if last_fill_price > 0 else avg_price
                qty = last_filled_qty if last_filled_qty > 0 else 0.0
                if fill_price > 0 and qty > 0:
                    msg = f"[部分成交][{symbol}] {side_u} 价格 {fill_price} 数量 {qty} (累计 {cum_filled_qty}/{orig_qty})"
                    qlogger.warning(msg)
                    print(msg, flush=True)
                return

    async def _rest_price_fallback_loop(self):
        loop = asyncio.get_running_loop()
        stale_threshold = 3.0
        interval_healthy = 5.0
        interval_stale = 1.0
        while True:
            now = time.time()
            tasks = []
            to_fetch = []
            for symbol in list(self.traders.keys()):
                last_ws = self.last_price_ts.get(symbol, 0)
                last_rest = self.last_rest_fetch_ts.get(symbol, 0)
                if now - last_ws > stale_threshold:
                    if now - last_rest >= interval_stale:
                        self.last_rest_fetch_ts[symbol] = now
                        to_fetch.append(symbol)
                        tasks.append(loop.run_in_executor(None, lambda s=symbol: api.fetch_symbol_price(s)))
                else:
                    # WS健康时降低频率，仍做温和轮询以填充首次启动价格
                    if symbol not in self.latest_prices and now - last_rest >= interval_healthy:
                        self.last_rest_fetch_ts[symbol] = now
                        to_fetch.append(symbol)
                        tasks.append(loop.run_in_executor(None, lambda s=symbol: api.fetch_symbol_price(s)))
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for symbol, price in zip(to_fetch, results):
                    if isinstance(price, Exception):
                        continue
                    if isinstance(price, (int, float)) and price > 0:
                        self.latest_prices[symbol] = float(price)
                        self.last_price_ts[symbol] = time.time()
                        
                        # [核心修复] REST 价格回退时也驱动策略更新
                        trader = self.traders.get(symbol)
                        if trader and trader.initialized:
                            trader.strategy.update_price(datetime.now(), float(price))
            await asyncio.sleep(1.0)

    async def _order_status_fallback_loop(self):
        loop = asyncio.get_running_loop()
        while True:
            tasks = []
            meta = []
            for symbol, trader in self.traders.items():
                for side in ('BUY', 'SELL'):
                    oid = trader.active_orders.get(side, {}).get('id')
                    if oid:
                        tasks.append(loop.run_in_executor(None, lambda s=symbol, o=oid: api.fetch_order(s, o)))
                        meta.append((symbol, trader, side, oid))
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for (symbol, trader, side, oid), order in zip(meta, results):
                    if isinstance(order, Exception):
                        continue
                    status = (order.get('status') or '').lower()
                    if status in ('closed', 'filled'):
                        avg = order.get('average') or order.get('price') or 0
                        info = order.get('info') or {}
                        ap = info.get('avgPrice') or info.get('ap') or avg
                        price = float(ap) if ap else float(order.get('price', 0) or 0)
                        filled_qty = float(order.get('filled', 0) or order.get('amount', 0) or 0)
                        if price > 0:
                            await trader.on_order_filled(side, price, str(oid), filled_qty)
            await asyncio.sleep(1.0)

    async def _grid_health_check_loop(self):
        loop = asyncio.get_running_loop()
        while True:
            try:
                tasks = []
                meta = []
                for symbol, trader in self.traders.items():
                    if not trader.initialized:
                        continue
                    if getattr(trader, '_initialize_lock', None) and trader._initialize_lock.locked():
                        continue
                    now_ts = time.time()
                    last_rebuild = getattr(trader, 'last_rebuild_ts', 0.0) or 0.0
                    last_op = getattr(trader, 'last_order_op_ts', 0.0) or 0.0
                    last_activity = max(last_rebuild, last_op)
                    if last_activity and now_ts - last_activity < 3.0:
                        continue
                    tasks.append(loop.run_in_executor(None, lambda s=symbol: api.fetch_open_orders(s)))
                    meta.append((symbol, trader))
                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for (symbol, trader), orders in zip(meta, results):
                        if isinstance(orders, Exception):
                            continue
                        side_orders = trader._build_side_orders_from_open_orders(orders)
                        trader.update_expected_orders()
                        need_buy = trader.expected_orders.get('BUY', False)
                        need_sell = trader.expected_orders.get('SELL', False)
                        desired_layers = int(getattr(trader.config, 'orders_per_side', 1) or getattr(trader, 'orders_per_side', 1) or 1)
                        if need_buy and not side_orders['BUY']:
                            logger.warning(f"[{symbol}] 健康检查发现缺少买单: 需要BUY, 实际BUY=0, SELL={len(side_orders['SELL'])}")
                            qlogger.warning(f"[挂单健康][{symbol}] 缺少买单: 需要BUY, 实际BUY=0, SELL={len(side_orders['SELL'])}")
                        if need_sell and not side_orders['SELL']:
                            logger.warning(f"[{symbol}] 健康检查发现缺少卖单: 需要SELL, 实际SELL=0, BUY={len(side_orders['BUY'])}")
                            qlogger.warning(f"[挂单健康][{symbol}] 缺少卖单: 需要SELL, 实际SELL=0, BUY={len(side_orders['BUY'])}")
                        if desired_layers > 0:
                            changed = await trader._sync_orders_from_snapshot(side_orders, cancel_excess=False, log_profit=True)
                            trader.health_check_needed = bool(changed)
                        else:
                            trader.health_check_needed = False
            except Exception as e:
                logger.error(f"网格健康检查失败: {e}")
            await asyncio.sleep(5)

    async def _pnl_report_loop(self):
        loop = asyncio.get_running_loop()
        while True:
            try:
                total_realized = 0.0
                total_unrealized = 0.0
                for s in self.symbol_order:
                    t = self.traders.get(s)
                    if not t or not t.initialized:
                        continue
                    realized = float(t.strategy.account_dict.get('pair_profit', 0.0) or 0.0)
                    pos = await loop.run_in_executor(None, lambda sym=s: api.fetch_position(sym))
                    real_qty = float(pos.get('amount', 0.0) or 0.0)
                    logical_qty = float(t.strategy.account_dict.get('positions_qty', 0.0) or 0.0)
                    if t.config.direction_mode == 'short':
                        logical_effective = abs(logical_qty)
                        real_effective = abs(real_qty)
                    else:
                        logical_effective = logical_qty
                        real_effective = real_qty
                    diff = logical_effective - real_effective

                    base_for_ratio = max(abs(real_effective), 1e-8)
                    rel_error = abs(diff) / base_for_ratio if base_for_ratio > 0 else 0.0
                    if rel_error <= POSITION_TOLERANCE_RATIO:
                        t.strategy.account_dict['positions_qty'] = real_qty
                        diff = 0.0

                    symbol_rules = {
                        'ETHUSDC': {'min': 0.007, 'prec': 3},
                        'SOLUSDC': {'min': 0.04, 'prec': 2},
                        'BTCUSDC': {'min': 0.002, 'prec': 3},
                    }
                    rule = symbol_rules.get(s, {'min': 0.0, 'prec': None})

                    precision = getattr(t.config, 'qty_precision', None)
                    if rule['prec'] is not None:
                        precision = rule['prec']

                    if isinstance(precision, int) and precision >= 0:
                        diff = round(diff, precision)

                    display_precision = precision if isinstance(precision, int) and precision >= 0 else 3

                    min_qty = rule['min']
                    if abs(diff) > 0 and abs(diff) < min_qty:
                        diff = 0.0

                    if abs(diff) > 0:
                        if diff > 0:
                            diff_display = (
                                f"{diff:.{display_precision}f}" if isinstance(display_precision, int) and display_precision >= 0 else f"{diff:.4f}"
                            )
                            real_display = f"{real_qty:.{display_precision}f}"
                            logical_display = f"{logical_qty:.{display_precision}f}"
                            qlogger.warning(
                                f"[仓位校正][{s}] 仓位巡检发现实盘仓位 {real_display} 小于逻辑仓位 {logical_display}，准备补仓 {diff_display}"
                            )
                            price_ref = await loop.run_in_executor(None, lambda sym=s: api.fetch_symbol_price(sym))
                            try:
                                price_ref = float(price_ref or 0.0)
                            except Exception:
                                price_ref = 0.0
                            if price_ref > 0 and diff > 0:
                                pos_side = 'LONG' if t.config.direction_mode == 'long' else ('SHORT' if t.config.direction_mode == 'short' else None)
                                side_for_order = 'BUY' if t.config.direction_mode == 'long' else 'SELL'
                                try:
                                    corr_bps = float(getattr(t.config, 'position_correction_aggressive_bps', 5) or 5)
                                except Exception:
                                    corr_bps = 5.0
                                corr_ratio = max(0.0, corr_bps) / 10000.0
                                price_adj = price_ref * (1 + corr_ratio) if side_for_order == 'BUY' else price_ref * (1 - corr_ratio)
                                await loop.run_in_executor(None, lambda sym=s, p=price_adj, q=diff, ps=pos_side, sd=side_for_order: api.place_limit_order(sym, sd, p, q, position_side=ps, post_only=False))
                                qlogger.ok(f"[仓位校正][{s}] 巡检补仓委托已发送，目标补仓数量 {diff_display}")
                        else:
                            extra = -diff
                            extra_display = (
                                f"{extra:.{display_precision}f}" if isinstance(display_precision, int) and display_precision >= 0 else f"{extra:.4f}"
                            )
                            real_display = f"{real_qty:.{display_precision}f}"
                            logical_display = f"{logical_qty:.{display_precision}f}"
                            qlogger.warning(
                                f"[仓位校正][{s}] 仓位巡检发现实盘仓位 {real_display} 大于逻辑仓位 {logical_display}，准备减仓 {extra_display}"
                            )
                            price_ref = await loop.run_in_executor(None, lambda sym=s: api.fetch_symbol_price(sym))
                            try:
                                price_ref = float(price_ref or 0.0)
                            except Exception:
                                price_ref = 0.0
                            if price_ref > 0 and extra > 0:
                                pos_side = 'LONG' if t.config.direction_mode == 'long' else ('SHORT' if t.config.direction_mode == 'short' else None)
                                side_for_order = 'SELL' if t.config.direction_mode == 'long' else 'BUY'
                                try:
                                    corr_bps = float(getattr(t.config, 'position_correction_aggressive_bps', 5) or 5)
                                except Exception:
                                    corr_bps = 5.0
                                corr_ratio = max(0.0, corr_bps) / 10000.0
                                price_adj = price_ref * (1 - corr_ratio) if side_for_order == 'SELL' else price_ref * (1 + corr_ratio)
                                await loop.run_in_executor(None, lambda sym=s, p=price_adj, q=extra, ps=pos_side, sd=side_for_order: api.place_limit_order(sym, sd, p, q, position_side=ps, post_only=False))
                                qlogger.ok(f"[仓位校正][{s}] 巡检减仓委托已发送，目标减仓数量 {extra_display}")
                    unrealized = float(pos.get('unRealizedProfit', 0.0) or 0.0)
                    total = realized + unrealized
                    total_realized += realized
                    total_unrealized += unrealized
                    idx = self.strategy_index.get(s, 0)
                    logger.info(f"策略 {idx} [{s}] 已实现: {realized:.2f} | 未实现: {unrealized:.2f} | 合计: {total:.2f}")
                logger.info(f"组合汇总 已实现: {total_realized:.2f} | 未实现: {total_unrealized:.2f} | 合计: {(total_realized + total_unrealized):.2f}")
            except Exception as e:
                logger.error(f"PNL 报告失败: {e}")
                msg = str(e)
                if "-4164" in msg or "notional must be greater" in msg:
                    qlogger.error(f"[PNL错误] PNL 报告下单失败 (Code -4164): {msg}")
                    qlogger.error(f"[PNL错误] 💡 错误解释: 订单金额低于交易所最小限制 (通常为 5U 或 20U)。可能是因为网格太密导致单格金额过小，请尝试增加单格投入或调大网格间距。")
            await asyncio.sleep(PNL_REPORT_INTERVAL_SECONDS)

if __name__ == "__main__":
    if not live_strategies:
        logger.error("Config 中未定义 live_strategies，请先配置策略列表。")
        raise SystemExit(1)
        
    system = MultiSymbolTradingSystem(live_strategies)
    try:
        asyncio.run(system.start())
    except KeyboardInterrupt:
        logger.info("程序退出")
