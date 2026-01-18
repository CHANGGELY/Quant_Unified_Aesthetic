"""
Market Making Strategy (适配真实 LightGBM 模型)
---------------------------------------------
在这个版本中，我们接入了真实的 .pkl 模型文件。
"""

from __future__ import annotations

import sys
import math
import pandas as pd
import joblib
import numpy as np
from dataclasses import dataclass, asdict
from typing import Dict, Optional, Tuple

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import QuoteTick, TradeTick
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from feature_engineering import FeatureSnapshot, RollingFeatureEngine
from glft_logic import GlftParams, geometric_spacings, glft_quotes

# ----------------------------------------------------
# 关键：把 Quant_Unified 路径加进去，否则 pickle 加载不了自定义类
# ----------------------------------------------------
QUANT_PATH = "/Users/chuan/Desktop/xiangmu/客户端/Quant_Unified"
if QUANT_PATH not in sys.path:
    sys.path.append(QUANT_PATH)

MODEL_PATH = "/Users/chuan/Desktop/xiangmu/客户端/models/BTCUSDC_executable_h30.pkl"


class LightGBMSignalEngine:
    """
    真实的信号引擎。
    从 .pkl 加载模型，并进行推理。
    """
    def __init__(self, model_path: str) -> None:
        print(f"正在加载模型: {model_path} ...")
        # 直接使用 joblib 加载
        self.artifact = joblib.load(model_path)
        self.model = self.artifact.calibrated_model
        
        # Monkey-patch: Fix sklearn version incompatibility
        # 'LogisticRegression' missing 'multi_class' attribute
        if hasattr(self.model, '_calibrators'):
            for cal in self.model._calibrators:
                if not hasattr(cal, 'multi_class'):
                    cal.multi_class = 'ovr'

        self.feature_names = self.artifact.feature_names
        print(f"模型加载成功! 需要特征: {self.feature_names}")
        
    def fair_price(self, features: FeatureSnapshot) -> float:
        """
        利用模型预测公允价。
        模型是 OneVsRestProbCalibrator (3分类: 0=Down, 1=Neutral, 2=Up).
        """
        data = asdict(features)
        try:
            row = {name: data[name] for name in self.feature_names}
        except KeyError as e:
            # print(f"Error: 特征缺失 {e}")
            return features.mid_price

        # Fix: Use DataFrame to suppress Sklearn warnings and ensure feature mapping
        X = pd.DataFrame([row], columns=self.feature_names)
        
        # 3分类概率: [P_down, P_neutral, P_up]
        probs = self.model.predict_proba(X)[0]
        p_down = probs[0]
        # p_neutral = probs[1]
        p_up = probs[2]
        
        # 信号强度 (-1 到 1)
        signal = p_up - p_down
        
        # 将信号转换为预期收益率
        # 假设 30s 典型波动为 5bps (0.0005)
        # drift = signal * scaling_factor
        drift = signal * 0.0005
        
        fair = features.mid_price * (1.0 + drift)
        return fair


# @dataclass(frozen=True)  <-- Removed because StrategyConfig is a msgspec.Struct
class MarketMakerConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    order_size: float = 0.001       # 0.001 BTC
    max_inventory: float = 0.05     # 最大 0.05 BTC
    max_drawdown_pct: float = 0.05
    window_sec: float = 10.0        # 特征窗口设大一点
    grid_levels: int = 5
    base_spacing_bps: float = 5.0   # 稍微宽一点
    spacing_growth: float = 1.5
    reprice_threshold_bps: float = 2.0
    reprice_cooldown_ms: int = 100
    glft_gamma: float = 50.0        # 风险厌恶加大
    glft_kappa: float = 5.0
    glft_horizon_sec: float = 30.0
    
    # SOTA Params
    sigmoid_beta: float = 5.0       # Sigmoid 激进系数
    bailout_hold_time_sec: int = 60 # 最大持仓时间 60s
    bailout_loss_factor: float = 3.0 # 亏损 > 3倍 Spread 时止损


@dataclass
class GridOrder:
    order_id: object
    side: OrderSide
    level: int
    price: float
    size: float


class MarketMakerStrategy(Strategy):
    def __init__(self, config: MarketMakerConfig) -> None:
        super().__init__(config)

        self.instrument_id = config.instrument_id
        
        # 初始化真实模型引擎
        try:
            self.signal_engine = LightGBMSignalEngine(MODEL_PATH)
        except Exception as e:
            print(f"模型加载失败: {e}，将使用 Dummy 模式")
            self.signal_engine = None
            
        self.feature_engine = RollingFeatureEngine(window_ns=int(config.window_sec * 1e9))
        
        self.glft_params = GlftParams(
            gamma=config.glft_gamma,
            kappa=config.glft_kappa,
            horizon_sec=config.glft_horizon_sec,
        )
        
        self._grid_orders: Dict[Tuple[OrderSide, int], GridOrder] = {}
        self._last_fair: Optional[float] = None
        self._last_spread: Optional[float] = None
        self._last_reprice_ns = 0
        self._inventory = 0.0
        self._equity_peak = 0.0
        self._halted = False
        self._instrument = None
        
        # SOTA State
        self._inventory_entry_ns = 0
        self._inventory_avg_cost = 0.0
        self._bailout_triggered = False
        
        # Optimization: Throttle predictions
        self._last_predict_ns = 0
        self._predict_interval_ns = 100_000_000 # 100ms
        self._cached_drift = 0.0

    def on_start(self) -> None:
        self.subscribe_quote_ticks(self.instrument_id)
        if hasattr(self, "cache"):
            self._instrument = self.cache.instrument(self.instrument_id)

    def on_quote_tick(self, quote: QuoteTick) -> None:
        if self._halted:
            return

        ts_ns = int(quote.ts_event)
        
        # 提取动态挂载的深度数据
        depth = getattr(quote, "depth_snapshot", None)

        self.feature_engine.update_quote(
            self._to_float(quote.bid_price),
            self._to_float(quote.ask_price),
            self._to_float(quote.bid_size),
            self._to_float(quote.ask_size),
            ts_ns,
            depth=depth
        )
        features = self.feature_engine.snapshot()
        
        if features.mid_price <= 0.0:
            return

        # 预测 (带节流)
        if self.signal_engine:
            if ts_ns - self._last_predict_ns >= self._predict_interval_ns:
                # Time to predict
                fair_price_snapshot = self.signal_engine.fair_price(features)
                # Calculate drift from this snapshot
                if features.mid_price > 0:
                     self._cached_drift = (fair_price_snapshot / features.mid_price) - 1.0
                else:
                     self._cached_drift = 0.0
                self._last_predict_ns = ts_ns
            
            # Apply cached drift to CURRENT mid price
            fair_price = features.mid_price * (1.0 + self._cached_drift)
        else:
            fair_price = features.mid_price

        # 风控 (包括 Bailout)
        if not self._risk_check(features, ts_ns):
            # 如果触发了 Bailout 或其他风控，这里可能已经处理了（比如平仓）
            # _risk_check 返回 False 表示暂停挂单
            self.cancel_all_orders(self.instrument_id)
            # self._halted = True # Bailout 不一定要 halt，可能是暂避
            return

        inventory = self._get_inventory()
        
        # --- 1. 计算 Alpha 驱动的目标库存 (q_target) ---
        # 公式: Q_target = Q_max * (2 / (1 + e^(-beta * (p - 0.5))) - 1)
        # 获取上涨概率 (从 cached drift 反推，或者直接存 prob)
        # 由于 signal_engine 算的是 drift，我们反推一个近似的 "prob_score"
        # 简单处理：drift > 0 implies p > 0.5. 
        # 我们直接用 signal_strength 映射。
        # 这里为了演示，我们假设 drift = (2p - 1) * scale
        # 所以 normalized_signal = drift / scale. 
        # 让我们直接用 cached_drift 作为一个线性指标传入 sigmoid
        # q_target = Q_max * tanh(beta * drift * 1000) ? 
        # 还是严格按照用户公式？ 用户公式需要 p。
        # 我们 modify feature_engineering/signal_engine to return p? 
        # 为了不改动太多，我们用 cached_drift (approx 5bps drift ~ high confidence)
        # normalized_p = 0.5 + self._cached_drift / 0.001 (假设 0.1% drift 是极大信心)
        
        norm_p = 0.5 + (self._cached_drift * 500.0) # drift 0.0005 -> p=0.75
        norm_p = max(0.0, min(1.0, norm_p))
        
        q_target = self.config.max_inventory * (
            (2.0 / (1.0 + math.exp(-self.config.sigmoid_beta * (norm_p - 0.5)))) - 1.0
        )
        
        # 有效库存 (Effective Inventory)
        q_eff = inventory - q_target

        # --- 2. GLFT ---
        bid_px, ask_px, spread, _ = glft_quotes(
            fair_price,
            q_eff, # 使用有效库存
            0.0,   # sigma 不再单独使用
            features.vol_down,
            features.vol_up,
            features.toxicity,
            self.glft_params,
        )

        if not self._should_reprice(ts_ns, fair_price, spread):
            return

        self._sync_grid(bid_px, ask_px, fair_price, inventory, ts_ns)
        
        self._last_fair = fair_price
        self._last_spread = spread
        self._last_reprice_ns = ts_ns

    # ... (Rest of logic: _sync_grid, _risk_check, etc. same as before)
    # Copying essential methods to ensure functionality

    def _sync_grid(self, bid_c, ask_c, fair, inv, ts):
        base_space = fair * self.config.base_spacing_bps / 10000.0
        spacings = geometric_spacings(base_space, self.config.spacing_growth, self.config.grid_levels)
        bid_sc, ask_sc = self._inventory_scales(inv)
        
        desired = {}
        for lvl, sp in enumerate(spacings, 1):
            bp = bid_c - sp
            ap = ask_c + sp
            desired[(OrderSide.BUY, lvl)] = (bp, self.config.order_size * bid_sc)
            desired[(OrderSide.SELL, lvl)] = (ap, self.config.order_size * ask_sc)

        threshold = self.config.reprice_threshold_bps / 10000.0
        for k, o in list(self._grid_orders.items()):
            tgt = desired.get(k)
            if not tgt:
                ord_obj = self.cache.order(o.order_id)
                if ord_obj: self.cancel_order(ord_obj)
                self._grid_orders.pop(k)
                continue
            np, ns = tgt
            if o.price <= 0: replace = True
            else: replace = abs(np - o.price)/o.price > threshold
            if replace:
                ord_obj = self.cache.order(o.order_id)
                if ord_obj: self.cancel_order(ord_obj)
                self._grid_orders.pop(k)

        for k, (p, s) in desired.items():
            if k in self._grid_orders: continue
            order = self._make_post_only_order(k[0], p, s)
            if order:
                self.submit_order(order)
                self._grid_orders[k] = GridOrder(order.client_order_id, k[0], k[1], p, s)

    def _make_post_only_order(self, side, p, s):
        q = self._make_qty(s)
        px = self._make_price(p)
        if not q or not px: return None
        kwargs = dict(instrument_id=self.instrument_id, order_side=side, quantity=q, price=px, time_in_force=TimeInForce.GTC, post_only=True)
        try: return self.order_factory.limit(**kwargs)
        except: 
            kwargs.pop('post_only')
            return self.order_factory.limit(**kwargs)

    def _inventory_scales(self, inv):
        max_inv = self.config.max_inventory
        if max_inv <= 0: return 1.0, 1.0
        curr = max(-max_inv, min(max_inv, inv))
        if curr >= 0: return max(0.0, 1.0 - curr/max_inv), 1.0
        else: return 1.0, max(0.0, 1.0 - abs(curr)/max_inv)

    def _should_reprice(self, ts, fair, spr):
        if not self._last_fair or not self._last_spread: return True
        if ts - self._last_reprice_ns < self.config.reprice_cooldown_ms * 1e6: return False
        fm = abs(fair - self._last_fair)/self._last_fair
        sm = abs(spr - self._last_spread)/self._last_spread
        th = self.config.reprice_threshold_bps/10000.0
        return fm > th or sm > th

    def _risk_check(self, features: FeatureSnapshot, ts_ns: int):
        inv = self._get_inventory()
        abs_inv = abs(inv)

        # 1. 基础硬风控
        if abs_inv > self.config.max_inventory * 2: return False
        
        eq = self._current_equity()
        if eq is not None:
             if self._equity_peak <= 0: self._equity_peak = eq
             self._equity_peak = max(self._equity_peak, eq)
             dd_pct = (self._equity_peak - eq)/self._equity_peak
             if dd_pct > self.config.max_drawdown_pct: return False
        
        # 2. Taker Bailout Logic (被动止损)
        if abs_inv > self.config.order_size * 0.1: # 有持仓
            # 时间止损
            hold_time_sec = (ts_ns - self._inventory_entry_ns) / 1e9
            
            # 价格止损 (Per Unit Loss)
            # Long: (Mid - Cost) 
            # Short: (Cost - Mid)
            pnl_per_unit = (features.mid_price - self._inventory_avg_cost) if inv > 0 else (self._inventory_avg_cost - features.mid_price)
            
            # 估算 Spread (用当前的 mid * 5bps 近似作为基准 spread profit)
            spread_bench = features.mid_price * 0.0005 
            loss_threshold = -spread_bench * self.config.bailout_loss_factor
            
            is_time_out = hold_time_sec > self.config.bailout_hold_time_sec
            is_stop_loss = pnl_per_unit < loss_threshold
            
            if is_time_out or is_stop_loss:
                # 触发止损
                if not self._bailout_triggered:
                    print(f"BAILOUT Triggered! Inv={inv:.4f}, Hold={hold_time_sec:.1f}s, PnL={pnl_per_unit:.2f}, Reason={'Time' if is_time_out else 'Loss'}")
                    self.cancel_all_orders(self.instrument_id)
                    
                    # 发送 Taker 单平仓
                    side = OrderSide.SELL if inv > 0 else OrderSide.BUY
                    qty = self._make_qty(abs_inv)
                    # 必须保证 instrument 存在
                    if self._instrument and qty > 0:
                        order = self.order_factory.market(
                            instrument_id=self.instrument_id,
                            order_side=side,
                            quantity=qty,
                        )
                        self.submit_order(order)
                        self._bailout_triggered = True # 标记已触发，防止重复发单
                return False # 暂停挂 Maker 单
        
        # Reset bailout flag if inventory cleared
        if abs_inv < self.config.order_size * 0.1:
            self._bailout_triggered = False

        return True

    def _current_equity(self):
        p = getattr(self, "portfolio", None)
        if hasattr(self, 'cache'): p = getattr(self.cache, 'portfolio', p)
        if not p: return None
        
        try:
             return float(p.net_value)
        except AttributeError:
             try:
                 acct = p.account(self.instrument_id.venue)
                 return float(acct.balance_total(acct.base_currency))
             except Exception as e:
                 # Log error but try to continue or return None
                 print(f"Error calculating equity: {e}")
                 return None

    def _get_inventory(self):
        if hasattr(self, 'cache'):
            # cache.position expects PositionId, so we iterate to find by InstrumentId
            positions = self.cache.positions()
            for p in positions:
                if p.instrument_id == self.instrument_id:
                    return float(p.quantity)
        return self._inventory

    def _make_price(self, p):
        return self._instrument.make_price(p) if self._instrument else p
    def _make_qty(self, q):
        return self._instrument.make_qty(q) if self._instrument else q
    def _to_float(self, v):
        try: return float(v)
        except: return 0.0

    # Add empty event handlers to satisfy abstract methods if any
    def on_trade_tick(self, tick: TradeTick): 
        # 记录 Trade 用于计算 Toxicity
        self.feature_engine.update_trade(tick.last_qty, tick.order_side, tick.ts_event)
 
    def on_order_filled(self, event):
        side = getattr(event, "order_side", None)
        filled_qty = self._to_float(getattr(event, "last_qty", 0.0))
        filled_px = self._to_float(getattr(event, "last_px", 0.0))
        
        if filled_qty <= 0: return

        # 更新库存成本
        old_inv = self._inventory
        new_inv = old_inv + filled_qty if side == OrderSide.BUY else old_inv - filled_qty
        
        # 判定是否开新仓/加仓/减仓/反手
        # 简单加权平均逻辑
        
        # Case 1: 从 0 开仓
        if abs(old_inv) < 1e-9:
             self._inventory_avg_cost = filled_px
             self._inventory_entry_ns = event.ts_event
        # Case 2: 同向加仓
        elif (old_inv > 0 and side == OrderSide.BUY) or (old_inv < 0 and side == OrderSide.SELL):
             total_cost = abs(old_inv) * self._inventory_avg_cost + filled_qty * filled_px
             self._inventory_avg_cost = total_cost / (abs(old_inv) + filled_qty)
             # Entry time 不变 (以第一笔为准) 或者 更新？通常 Bailout 针对"这一坨"持仓。保留最早 entry 比较保守。
        # Case 3: 减仓/平仓
        elif (old_inv > 0 and side == OrderSide.SELL) or (old_inv < 0 and side == OrderSide.BUY):
             # 成本不变，只是数量减少
             # 如果反手了 (new_inv 符号变了)
             if new_inv * old_inv < 0:
                 self._inventory_avg_cost = filled_px
                 self._inventory_entry_ns = event.ts_event
        
        self._inventory = new_inv

    def on_reset(self) -> None:
        """
        Reset strategy state when the engine is reset.
        Implemented to suppress warning: 
        'The Strategy.on_reset handler was called when not overridden'
        """
        self._grid_orders.clear()
        self._last_fair = None
        self._last_spread = None
        self._inventory = 0.0
        self._equity_peak = 0.0
        self._halted = False
        # Reset prediction throttle state
        self._last_predict_ns = 0
        self._cached_drift = 0.0

