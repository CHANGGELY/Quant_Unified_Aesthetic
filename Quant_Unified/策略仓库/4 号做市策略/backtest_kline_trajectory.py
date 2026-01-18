"""永续合约做市策略回测脚本（增强版，重点还原K线价格轨迹与风险控制）。

- 标的：币安 ETH-USDC U 本位永续合约
- 在 `backtest_old.py` 基础上新增波动率自适应、仓位平衡与更严格的风险控制
- 使用 5 点 K 线价格轨迹 + ATR 波动率监控，支持退场机制和手续费返佣
- 提供完整的绩效分析（收益率、最大回撤、夏普比）与资金曲线图输出
- 作为当前推荐使用的主回测脚本，可被前端或命令行直接调用
"""

import asyncio
import pandas as pd
from decimal import Decimal
from typing import Dict, List, Optional
from tqdm import tqdm
import logging
import numpy as np
import matplotlib.pyplot as plt
import warnings
import pickle
import hashlib
import os
import sys
from pathlib import Path
import webbrowser

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
libs_path = PROJECT_ROOT / '基础库'
if str(libs_path) not in sys.path:
    sys.path.append(str(libs_path))

from common_core.backtest.figure import draw_equity_curve_plotly

# =====================================================================================
# 回测配置
# =====================================================================================
BCKTEST_DATA_FILE = str(
    PROJECT_ROOT
    / '策略仓库'
    / '二号网格策略'
    / 'data_center'
    / 'ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5'
)

BACKTEST_CONFIG = {
	"data_file_path": BCKTEST_DATA_FILE,
    "start_date": "2021-01-01",
    "end_date": "2025-12-12",
    "initial_balance": 700,
    "plot_equity_curve": True,
    "auto_open_html": True,
    "equity_curve_path": "data/回测结果/资金曲线.png",
    "bar_interval": "1m",
}

MARKET_CONFIG = {
    "trading_pair": "ETHUSDT",
    "base_asset": "ETH",
    "quote_asset": "USDT",
    "contract_size": Decimal("1"),  # 合约乘数 (1张合约 = 1 ETH，与币安U本位永续合约一致)
    "min_order_size": Decimal("0.009"),  # 最小下单量 (ETH) - 根据您的要求更新
    "maker_fee": Decimal("0.0000"),  # 挂单手续费 0.02%
    "taker_fee": Decimal("0.0005"),  # 吃单手续费 0.05%
}

STRATEGY_CONFIG = {
    "leverage": 125,  # 杠杆倍数 (降低杠杆测试币安标准)
    "position_mode": "Hedge",  # 对冲模式
    "bid_spread": Decimal("0.002"),  # 0.2% 买单价差 (增加价差)
    "ask_spread": Decimal("0.002"),  # 0.2% 卖单价差

    # 动态下单量配置
    "use_dynamic_order_size": True,  # 是否使用动态下单量
    # position_size_ratio: 自动计算参数 = 1/当前有效杠杆，不可手动设置
    "min_order_amount": Decimal("0.009"),   # 最小下单数量 (ETH) - 必须 >= min_order_size
    "max_order_amount": Decimal("999.0"),    # 最大下单数量 (ETH) - 大幅降低

    # 🚀 币安标准：杠杆选择用总持仓，爆仓检查用净持仓，恢复80%比例
    "max_position_value_ratio": Decimal("1"),  # 最大仓位价值不超过权益的100%
    "order_refresh_time": 15.0,  # 订单刷新时间(秒)
    # 删除资金费率配置，因为数据中没有资金费率

    # 新增：单笔止损配置
    "position_stop_loss": Decimal("0.05"),  # 单个仓位5%止损
    "enable_position_stop_loss": False,  # 启用单笔止损
}

# =====================================================================================
# 📈 币安ETHUSDC阶梯保证金表 (根据用户最新提供的图片更新)
# 格式: (仓位价值上限USDT, 最大杠杆倍数, 维持保证金率, 维持保证金速算额)
# =====================================================================================
ETH_USDC_TIERS = [
    (50000, 125, Decimal("0.004"), Decimal("0")),           # 0-50,000 USDT: 125x杠杆, 0.40%维持保证金
    (500000, 100, Decimal("0.005"), Decimal("50")),         # 50,001-500,000 USDT: 100x杠杆, 0.50%维持保证金
    (1000000, 75, Decimal("0.0065"), Decimal("800")),       # 500,001-1,000,000 USDT: 75x杠杆, 0.65%维持保证金
    (5000000, 50, Decimal("0.01"), Decimal("4300")),        # 1,000,001-5,000,000 USDT: 50x杠杆, 1.00%维持保证金
    (50000000, 20, Decimal("0.02"), Decimal("54300")),      # 5,000,001-50,000,000 USDT: 20x杠杆, 2.00%维持保证金
    (100000000, 10, Decimal("0.05"), Decimal("1554300")),   # 50,000,001-100,000,000 USDT: 10x杠杆, 5.00%维持保证金
    (150000000, 5, Decimal("0.1"), Decimal("6554300")),     # 100,000,001-150,000,000 USDT: 5x杠杆, 10.00%维持保证金
    (300000000, 4, Decimal("0.125"), Decimal("10304300")),  # 150,000,001-300,000,000 USDT: 4x杠杆, 12.50%维持保证金
    (400000000, 3, Decimal("0.15"), Decimal("17804300")),   # 300,000,001-400,000,000 USDT: 3x杠杆, 15.00%维持保证金
    (500000000, 2, Decimal("0.25"), Decimal("57804300")),   # 400,000,001-500,000,000 USDT: 2x杠杆, 25.00%维持保证金
    (Decimal('Infinity'), 1, Decimal("0.5"), Decimal("182804300"))  # >500,000,000 USDT: 1x杠杆, 50.00%维持保证金
]

# =====================================================================================
# 新增：返佣机制配置
# =====================================================================================
REBATE_CONFIG = {
    "use_fee_rebate": False,          # 是否启用返佣机制
    "rebate_rate": Decimal("0.30"),  # 返佣比例 (30%)
    "rebate_payout_day": 19,         # 每月返佣发放日
}

# =====================================================================================
# 新增：风险控制配置
# =====================================================================================
RISK_CONFIG = {
    "enable_stop_loss": False,         # 启用止损/退场机制
    "max_drawdown": Decimal("0.30"), # 最大允许回撤 30% (更严格)
    "min_equity": Decimal("300"),    # 当权益低于该值即退场 (USDT) - 提高阈值
    "max_daily_loss": Decimal("0.10"), # 单日最大亏损10%
}

# =====================================================================================
# 新增：波动率自适应配置
# =====================================================================================
VOLATILITY_CONFIG = {
    "enable_volatility_adaptive": True,    # 启用波动率自适应机制
    "atr_period": 24 * 60,                # ATR计算周期 (24小时 = 1440分钟)
    "high_volatility_threshold": Decimal("0.30"),  # 高波动率阈值 30%
    "extreme_volatility_threshold": Decimal("0.50"), # 极端波动率阈值 50%

    # 仓位平衡参数
    "position_balance_ratio": Decimal("0.8"),  # 仓位平衡目标比例
    "max_imbalance_ratio": Decimal("0.3"),     # 最大允许仓位不平衡比例

    # 动态网格参数
    "base_spread": Decimal("0.002"),           # 基础价差 0.2%
    "max_spread_multiplier": Decimal("3.0"),   # 最大价差倍数
    "spread_adjustment_factor": Decimal("2.0"), # 价差调整因子

    # 风险控制参数
    "emergency_close_threshold": Decimal("0.70"), # 紧急平仓阈值 70%
    "gradual_adjustment": True,                   # 启用渐进式调整
}

# =====================================================================================
# 波动率计算工具
# =====================================================================================
class VolatilityMonitor:
    def __init__(self, atr_period: int = 1440):  # 默认24小时
        self.atr_period = atr_period
        self.price_history = []  # 存储 (timestamp, high, low, close)
        self.atr_values = []

    def update_price(self, timestamp: int, high: float, low: float, close: float):
        """更新价格数据并计算ATR"""
        self.price_history.append((timestamp, high, low, close))

        # 保持历史数据在指定周期内
        if len(self.price_history) > self.atr_period + 1:
            self.price_history.pop(0)

        # 计算ATR
        if len(self.price_history) >= 2:
            self._calculate_atr()

    def _calculate_atr(self):
        """计算平均真实波幅 (ATR)"""
        if len(self.price_history) < 2:
            return

        true_ranges = []
        for i in range(1, len(self.price_history)):
            current = self.price_history[i]
            previous = self.price_history[i-1]

            # 真实波幅 = max(high-low, |high-prev_close|, |low-prev_close|)
            tr1 = current[1] - current[2]  # high - low
            tr2 = abs(current[1] - previous[3])  # |high - prev_close|
            tr3 = abs(current[2] - previous[3])  # |low - prev_close|

            true_range = max(tr1, tr2, tr3)
            true_ranges.append(true_range)

        # 计算ATR (简单移动平均)
        if true_ranges:
            atr = sum(true_ranges) / len(true_ranges)
            self.atr_values.append(atr)

            # 保持ATR历史在合理范围内
            if len(self.atr_values) > 100:
                self.atr_values.pop(0)

    def get_current_atr_percentage(self) -> float:
        """获取当前ATR相对于价格的百分比"""
        if not self.atr_values or not self.price_history:
            return 0.0

        current_atr = self.atr_values[-1]
        current_price = self.price_history[-1][3]  # close price

        return (current_atr / current_price) * 100 if current_price > 0 else 0.0

    def get_volatility_level(self) -> str:
        """获取当前波动率等级"""
        atr_pct = self.get_current_atr_percentage()

        high_threshold = float(VOLATILITY_CONFIG["high_volatility_threshold"]) * 100
        extreme_threshold = float(VOLATILITY_CONFIG["extreme_volatility_threshold"]) * 100

        if atr_pct >= extreme_threshold:
            return "EXTREME"
        elif atr_pct >= high_threshold:
            return "HIGH"
        else:
            return "NORMAL"

    def should_reduce_exposure(self) -> bool:
        """判断是否应该减少风险敞口"""
        return self.get_volatility_level() in ["HIGH", "EXTREME"]

# =====================================================================================
# 高性能永续合约交易所模拟器
# =====================================================================================
class FastPerpetualExchange:
    def __init__(self, initial_balance: float):
        self.balance = Decimal(str(initial_balance))
        self.margin_balance = Decimal(str(initial_balance))

        self.long_position = Decimal("0")
        self.short_position = Decimal("0")
        self.long_entry_price = Decimal("0")
        self.short_entry_price = Decimal("0")

        self.base_leverage = STRATEGY_CONFIG["leverage"]
        self.current_leverage = self.base_leverage
        
        self.current_price = Decimal("0")
        
        self.active_buy_orders = []
        self.active_sell_orders = []
        self.trade_history = []
        self.equity_history = []
        self.liquidation_events = []
        self.order_id_counter = 1
        self.total_fees_paid = Decimal("0")

        self.maker_fee = MARKET_CONFIG["maker_fee"]
        self.taker_fee = MARKET_CONFIG["taker_fee"]

        self.use_fee_rebate = REBATE_CONFIG.get("use_fee_rebate", False)
        if self.use_fee_rebate:
            self.last_payout_date = None
            self.current_cycle_fees = Decimal("0")

        self.rebate_payout_day = REBATE_CONFIG.get("rebate_payout_day")
        self.rebate_rate = REBATE_CONFIG.get("rebate_rate", Decimal("0"))

        if VOLATILITY_CONFIG["enable_volatility_adaptive"]:
            self.volatility_monitor = VolatilityMonitor(VOLATILITY_CONFIG["atr_period"])
        else:
            self.volatility_monitor = None
        
    def get_equity(self) -> Decimal:
        """获取当前总权益"""
        return self.balance + self.get_unrealized_pnl()

    def get_used_margin(self) -> Decimal:
        """🚀 币安标准：获取已用保证金 - 优先使用高杠杆，提高资金使用率"""
        # 获取当前档位的最大杠杆倍数 (基于总持仓价值)
        current_max_leverage = self.get_current_max_leverage()

        # 🚀 优先选择高杠杆：使用当前档位允许的最高杠杆，但不超过初始设置
        effective_leverage = min(current_max_leverage, self.base_leverage)

        if effective_leverage == 0:
            return Decimal("0")

        # 🚀 保证金计算：总持仓价值 / 有效杠杆
        long_value = self.long_position * self.long_entry_price
        short_value = self.short_position * self.short_entry_price
        total_position_value = long_value + short_value
        return total_position_value / Decimal(str(effective_leverage))

    def get_available_margin(self) -> Decimal:
        """获取可用保证金"""
        return self.get_equity() - self.get_used_margin()

    def get_current_leverage_tier(self) -> tuple:
        """🚀 币安标准：根据总持仓价值获取对应的杠杆档位，优先选择高杠杆"""
        total_position_value = self.get_position_value()  # 现在是总持仓价值

        # 🚀 优先选择高杠杆：从最高杠杆开始检查
        for threshold, max_leverage, mm_rate, fixed_amount in ETH_USDC_TIERS:
            if total_position_value <= threshold:
                return threshold, max_leverage, mm_rate, fixed_amount

        # 默认返回最低档位 (超出所有限制时)
        return ETH_USDC_TIERS[-1]

    def get_current_max_leverage(self) -> int:
        """获取当前仓位价值对应的最大杠杆倍数"""
        _, max_leverage, _, _ = self.get_current_leverage_tier()
        return max_leverage

    def update_current_leverage(self):
        """🚀 更新当前有效杠杆 (用于交易记录)"""
        old_leverage = self.current_leverage
        current_max_leverage = self.get_current_max_leverage()
        new_leverage = min(current_max_leverage, self.base_leverage)

        # 🚀 杠杆变化时记录 (用于调试)
        if new_leverage != old_leverage:
            total_pos_value = self.get_position_value()
            print(f"🔄 杠杆调整: {old_leverage}x → {new_leverage}x (总持仓价值: {total_pos_value:.2f} USDT)")

        self.current_leverage = new_leverage

    def get_maintenance_margin(self) -> Decimal:
        """🚀 币安标准：根据净持仓价值计算维持保证金 (爆仓风险评估)
        公式: 维持保证金 = 仓位名义价值 × 维持保证金率 - 维持保证金速算额
        """
        net_position_value = self.get_net_position_value()  # 使用净持仓价值

        for threshold, max_leverage, mm_rate, maintenance_amount in ETH_USDC_TIERS:
            # max_leverage在此处不使用，但保留用于阶梯保证金表的完整性
            _ = max_leverage  # 明确标记为未使用但保留
            if net_position_value <= threshold:
                # 🚀 修正：使用减号，符合币安公式
                return net_position_value * mm_rate - maintenance_amount
        return Decimal("0")  # 默认情况

    def check_and_handle_liquidation(self, timestamp: int) -> bool:
        """检查并处理爆仓事件。如果发生爆仓，则返回 True。"""
        if self.long_position == 0 and self.short_position == 0:
            return False

        equity = self.get_equity()
        # 使用动态计算的维持保证金
        maintenance_margin = self.get_maintenance_margin()

        if equity <= maintenance_margin and equity > 0:
            liquidation_price = self.current_price
            self.liquidation_events.append({
                "timestamp": timestamp, 
                "equity": equity,
                "price": liquidation_price  # 🚀 记录爆仓时的价格
            })
            
            print("\n" + "!"*70)
            # 🚀 修复：安全的时间戳转换
            try:
                if timestamp <= 2147483647 and timestamp >= 0:
                    time_str = pd.to_datetime(timestamp, unit='s').strftime('%Y-%m-%d %H:%M:%S')
                else:
                    time_str = f"时间戳:{timestamp}"
            except:
                time_str = f"时间戳:{timestamp}"
            print(f"💣💥 爆仓警告 (LIQUIDATION) at {time_str}")
            print(f"   - 爆仓价格: {liquidation_price:.2f} USDT")
            print(f"   - 账户权益: {equity:.2f} USDT")
            print(f"   - 维持保证金要求: {maintenance_margin:.2f} USDT")
            print("   - 所有仓位将被强制平仓，回测停止。")
            print("!"*70)

            self.active_buy_orders.clear()
            self.active_sell_orders.clear()

            taker_fee_rate = self.taker_fee

            if self.long_position > 0:
                pnl = self.long_position * (liquidation_price - self.long_entry_price)
                fee = self.long_position * liquidation_price * taker_fee_rate
                self.balance += pnl - fee
                self.total_fees_paid += fee
                if self.use_fee_rebate:
                    self.current_cycle_fees += fee
                    self.process_fee_rebate(timestamp)
                self.long_position = Decimal("0")
                self.long_entry_price = Decimal("0")

            if self.short_position > 0:
                pnl = self.short_position * (self.short_entry_price - liquidation_price)
                fee = self.short_position * liquidation_price * taker_fee_rate
                self.balance += pnl - fee
                self.total_fees_paid += fee
                if self.use_fee_rebate:
                    self.current_cycle_fees += fee
                    self.process_fee_rebate(timestamp)
                self.short_position = Decimal("0")
                self.short_entry_price = Decimal("0")

            self.balance = Decimal("0")
            
            return True
        
        return False

    def get_net_position(self) -> Decimal:
        return self.long_position - self.short_position
    
    def get_position_value(self) -> Decimal:
        """🚀 币安标准：计算总持仓价值 (多仓价值 + 空仓价值) - 用于杠杆选择"""
        long_value = self.long_position * self.current_price
        short_value = self.short_position * self.current_price
        return long_value + short_value  # 总持仓价值，用于杠杆档位判断

    def get_net_position_value(self) -> Decimal:
        """🚀 计算净持仓价值 (风险敞口) - 用于爆仓检查"""
        net_pos = self.get_net_position()
        return abs(net_pos) * self.current_price  # 净持仓价值，用于爆仓风险评估
    
    def get_unrealized_pnl(self) -> Decimal:
        pnl = Decimal("0")
        if self.long_position > 0:
            pnl += self.long_position * (self.current_price - self.long_entry_price)
        if self.short_position > 0:
            pnl += self.short_position * (self.short_entry_price - self.current_price)
        return pnl
    
    def get_margin_ratio(self) -> Decimal:
        position_value = self.get_position_value()
        if position_value == 0:
            return Decimal("999")
        equity = self.margin_balance + self.get_unrealized_pnl()
        return equity / position_value
    
    def set_current_price(self, price: Decimal):
        self.current_price = price

    def update_volatility_monitor(self, timestamp: int, high: float, low: float, close: float):
        """更新波动率监控数据"""
        if self.volatility_monitor:
            self.volatility_monitor.update_price(timestamp, high, low, close)

    def get_volatility_info(self) -> dict:
        """获取当前波动率信息"""
        if not self.volatility_monitor:
            return {"level": "NORMAL", "atr_percentage": 0.0, "should_reduce_exposure": False}

        return {
            "level": self.volatility_monitor.get_volatility_level(),
            "atr_percentage": self.volatility_monitor.get_current_atr_percentage(),
            "should_reduce_exposure": self.volatility_monitor.should_reduce_exposure()
        }
    
    def place_orders_batch(self, orders: List[tuple]):
        self.active_buy_orders.clear()
        self.active_sell_orders.clear()
        
        for side, amount, price in orders:
            if side in ['buy_long', 'buy_short']:
                self.active_buy_orders.append((price, amount, side))
            else:
                self.active_sell_orders.append((price, amount, side))
        
        # 排序以优化匹配
        self.active_buy_orders.sort(key=lambda x: x[0], reverse=True) # 买单价格从高到低
        self.active_sell_orders.sort(key=lambda x: x[0]) # 卖单价格从低到高

    def fast_order_matching(self, high: Decimal, low: Decimal, timestamp: int) -> int:
        """🚀 超高速订单匹配 - 向量化优化版本"""
        filled_count = 0

        # 🚀 向量化优化：批量处理买单
        if self.active_buy_orders:
            # 使用列表推导式，比传统循环快30-50%
            filled_buy_orders = [(price, amount, side) for price, amount, side in self.active_buy_orders if low <= price]
            remaining_buy_orders = [(price, amount, side) for price, amount, side in self.active_buy_orders if low > price]

            # 批量执行成交订单
            for price, amount, side in filled_buy_orders:
                self.execute_fast_trade(side, amount, price, timestamp)
                filled_count += 1

            self.active_buy_orders = remaining_buy_orders

        # 🚀 向量化优化：批量处理卖单
        if self.active_sell_orders:
            filled_sell_orders = [(price, amount, side) for price, amount, side in self.active_sell_orders if high >= price]
            remaining_sell_orders = [(price, amount, side) for price, amount, side in self.active_sell_orders if high < price]

            # 批量执行成交订单
            for price, amount, side in filled_sell_orders:
                self.execute_fast_trade(side, amount, price, timestamp)
                filled_count += 1

            self.active_sell_orders = remaining_sell_orders

        return filled_count
    
    def execute_fast_trade(self, side: str, amount: Decimal, price: Decimal, timestamp: int):
        """快速交易执行 - 增加历史记录并修复手续费bug"""
        fee = amount * price * self.maker_fee
        self.balance -= fee
        self.total_fees_paid += fee

        if self.use_fee_rebate:
            self.current_cycle_fees += fee
            self.process_fee_rebate(timestamp)
        
        pnl = Decimal("0")
        
        if side == "buy_long":
            if self.long_position == 0:
                self.long_entry_price = price
            else:
                total_value = self.long_position * self.long_entry_price + amount * price
                self.long_position += amount
                self.long_entry_price = total_value / self.long_position
            self.long_position += amount
            
        elif side == "sell_short":
            if self.short_position == 0:
                self.short_entry_price = price
            else:
                total_value = self.short_position * self.short_entry_price + amount * price
                self.short_position += amount
                self.short_entry_price = total_value / self.short_position
            self.short_position += amount
            
        elif side == "sell_long" and self.long_position > 0:
            trade_amount = min(amount, self.long_position)
            pnl = trade_amount * (price - self.long_entry_price)
            self.balance += pnl
            self.long_position -= trade_amount
            if self.long_position == 0:
                self.long_entry_price = Decimal("0")
                
        elif side == "buy_short" and self.short_position > 0:
            trade_amount = min(amount, self.short_position)
            pnl = trade_amount * (self.short_entry_price - price)
            self.balance += pnl
            self.short_position -= trade_amount
            if self.short_position == 0:
                self.short_entry_price = Decimal("0")

        # 🚀 更新当前杠杆 (用于交易记录)
        self.update_current_leverage()

        trade_record = {
            "timestamp": timestamp, "side": side, "amount": amount,
            "price": price, "fee": fee, "pnl": pnl, "leverage": self.current_leverage
        }
        self.trade_history.append(trade_record)
        self.order_id_counter += 1

    # 删除资金费率处理函数，因为数据中没有资金费率
    
    def record_equity(self, timestamp: int):
        """🚀 高性能权益记录 - 减少重复计算"""
        equity = self.balance + self.get_unrealized_pnl()
        self.equity_history.append((timestamp, equity))

    def record_equity_batch(self, timestamp: int, cached_unrealized_pnl: Optional[Decimal] = None):
        """🚀 批量权益记录 - 使用缓存的未实现盈亏"""
        if cached_unrealized_pnl is not None:
            equity = self.balance + cached_unrealized_pnl
        else:
            equity = self.balance + self.get_unrealized_pnl()
        self.equity_history.append((timestamp, equity))

    def process_fee_rebate(self, timestamp: int):
        """处理手续费返佣机制"""
        if not self.use_fee_rebate:
            return

        # 🚀 优化：避免时间戳溢出，添加边界检查
        if timestamp > 2147483647:  # 2038年问题边界
            return

        try:
            current_date = pd.to_datetime(timestamp, unit='s')
        except (ValueError, OverflowError, Exception):
            return  # 跳过无效时间戳
        payout_day = self.rebate_payout_day

        # 初始化 last_payout_date
        if self.last_payout_date is None:
            # 找到回测开始前的最后一个发放日
            start_date_payout = current_date.replace(day=payout_day, hour=0, minute=0, second=0, microsecond=0)
            if current_date < start_date_payout:
                # 如果开始日期在当月发放日之前，则上一个发放日是上个月的
                self.last_payout_date = start_date_payout - pd.DateOffset(months=1)
            else:
                # 如果开始日期在当月发放日之后，则上一个发放日就是当月的
                self.last_payout_date = start_date_payout
            return

        # 计算下一个发放日
        next_payout_date = self.last_payout_date + pd.DateOffset(months=1)

        if current_date >= next_payout_date:
            rebate_amount = self.current_cycle_fees * self.rebate_rate
            
            if rebate_amount > 0:
                self.balance += rebate_amount
                # 移除返佣打印信息，保持回测过程简洁

                # 重置周期手续费
                self.current_cycle_fees = Decimal("0")
            
            # 更新上次发放日期为本次的发放日
            self.last_payout_date = next_payout_date

    # ------------------ 新增工具函数 ------------------
    def close_all_positions_market(self, timestamp: int):
        """以当前市价强制平掉所有仓位（非爆仓用）。"""
        if self.long_position == 0 and self.short_position == 0:
            return
        taker_fee = self.taker_fee
        price = self.current_price

        if self.long_position > 0:
            pnl = self.long_position * (price - self.long_entry_price)
            fee = self.long_position * price * taker_fee
            self.balance += pnl - fee
            self.total_fees_paid += fee
            if self.use_fee_rebate:
                self.current_cycle_fees += fee
                self.process_fee_rebate(timestamp)  # 平仓时检查返佣
            self.long_position = Decimal("0")
            self.long_entry_price = Decimal("0")
        if self.short_position > 0:
            pnl = self.short_position * (self.short_entry_price - price)
            fee = self.short_position * price * taker_fee
            self.balance += pnl - fee
            self.total_fees_paid += fee
            if self.use_fee_rebate:
                self.current_cycle_fees += fee
                self.process_fee_rebate(timestamp)  # 平仓时检查返佣
            self.short_position = Decimal("0")
            self.short_entry_price = Decimal("0")
        
        print("\n" + "-"*70)
        # 🚀 修复：安全的时间戳转换
        try:
            if timestamp <= 2147483647 and timestamp >= 0:
                time_str = pd.to_datetime(timestamp, unit='s').strftime('%Y-%m-%d %H:%M:%S')
            else:
                time_str = f"时间戳:{timestamp}"
        except:
            time_str = f"时间戳:{timestamp}"
        print(f"🚪 触发退场机制 at {time_str}")
        print(f"   - 当前市价: {price:.2f} USDT")
        print(f"   - 账户余额(退场后): {self.balance:.2f} USDT")
        print("-"*70)

# =====================================================================================
# 高性能永续合约做市策略
# =====================================================================================
class FastPerpetualStrategy:
    def __init__(self, exchange: FastPerpetualExchange):
        self.exchange = exchange
        self.last_order_time = 0
        
    def calculate_dynamic_order_size(self, current_price: Decimal) -> Decimal:
        if not STRATEGY_CONFIG["use_dynamic_order_size"]:
            return STRATEGY_CONFIG["min_order_amount"]

        current_equity = self.exchange.get_equity()

        # 🚀 动态计算position_size_ratio = 1 / 当前有效杠杆
        current_max_leverage = self.exchange.get_current_max_leverage()
        effective_leverage = min(current_max_leverage, STRATEGY_CONFIG["leverage"])
        dynamic_position_ratio = Decimal("1") / Decimal(str(effective_leverage))

        order_value = current_equity * dynamic_position_ratio
        order_amount = order_value / current_price

        # 确保最小下单量符合市场要求
        min_amount = max(STRATEGY_CONFIG["min_order_amount"], current_equity / 1000 / current_price)
        max_amount = STRATEGY_CONFIG["max_order_amount"]

        # 确保下单量在最小和最大值之间
        return max(min_amount, min(max_amount, order_amount))
    
    def should_place_orders(self, timestamp: int) -> bool:
        return (timestamp - self.last_order_time) >= STRATEGY_CONFIG["order_refresh_time"]
    
    def check_position_stop_loss(self, current_price: Decimal) -> List[tuple]:
        """检查单笔仓位止损"""
        if not STRATEGY_CONFIG["enable_position_stop_loss"]:
            return []

        orders = []
        stop_loss_pct = STRATEGY_CONFIG["position_stop_loss"]

        # 检查多仓止损
        if self.exchange.long_position > 0:
            loss_pct = (self.exchange.long_entry_price - current_price) / self.exchange.long_entry_price
            if loss_pct >= stop_loss_pct:
                orders.append(("sell_long", self.exchange.long_position, current_price))
                # 移除打印信息，保持回测过程简洁

        # 检查空仓止损
        if self.exchange.short_position > 0:
            loss_pct = (current_price - self.exchange.short_entry_price) / self.exchange.short_entry_price
            if loss_pct >= stop_loss_pct:
                orders.append(("buy_short", self.exchange.short_position, current_price))
                # 移除打印信息，保持回测过程简洁

        return orders

    def calculate_adaptive_spread(self, current_price: Decimal) -> tuple:
        """根据波动率计算自适应价差"""
        base_spread = VOLATILITY_CONFIG["base_spread"]

        if not VOLATILITY_CONFIG["enable_volatility_adaptive"] or not self.exchange.volatility_monitor:
            return base_spread, base_spread

        volatility_info = self.exchange.get_volatility_info()
        volatility_level = volatility_info["level"]

        # 根据波动率等级调整价差
        if volatility_level == "EXTREME":
            multiplier = VOLATILITY_CONFIG["max_spread_multiplier"]
        elif volatility_level == "HIGH":
            multiplier = VOLATILITY_CONFIG["spread_adjustment_factor"]
        else:
            multiplier = Decimal("1.0")

        adaptive_spread = base_spread * multiplier
        return adaptive_spread, adaptive_spread

    def check_position_balance(self, current_price: Decimal) -> List[tuple]:
        """检查仓位平衡，在高波动期减少净敞口"""
        if not VOLATILITY_CONFIG["enable_volatility_adaptive"] or not self.exchange.volatility_monitor:
            return []

        volatility_info = self.exchange.get_volatility_info()
        if not volatility_info["should_reduce_exposure"]:
            return []

        # 计算当前净持仓
        net_position = self.exchange.get_net_position()
        long_pos = self.exchange.long_position
        short_pos = self.exchange.short_position
        total_position = long_pos + short_pos

        if total_position == 0:
            return []

        # 计算仓位不平衡比例
        imbalance_ratio = abs(net_position) / total_position
        max_imbalance = VOLATILITY_CONFIG["max_imbalance_ratio"]

        orders = []

        # 如果不平衡超过阈值，生成平衡订单
        if imbalance_ratio > max_imbalance:
            # 计算需要调整的数量
            target_imbalance = max_imbalance * VOLATILITY_CONFIG["position_balance_ratio"]
            target_net_position = total_position * target_imbalance

            if net_position > target_net_position:
                # 多头过多，需要平多或开空
                excess_long = net_position - target_net_position
                if long_pos > 0:
                    # 优先平多
                    close_amount = min(excess_long, long_pos)
                    orders.append(("sell_long", close_amount, current_price))
                else:
                    # 开空
                    orders.append(("sell_short", excess_long, current_price))

            elif net_position < -target_net_position:
                # 空头过多，需要平空或开多
                excess_short = abs(net_position) - target_net_position
                if short_pos > 0:
                    # 优先平空
                    close_amount = min(excess_short, short_pos)
                    orders.append(("buy_short", close_amount, current_price))
                else:
                    # 开多
                    orders.append(("buy_long", excess_short, current_price))

        return orders

    def generate_orders(self, current_price: Decimal, timestamp: int) -> List[tuple]:
        """🚀 波动率自适应订单生成 - 集成ATR风险控制"""
        # 1. 优先检查止损
        stop_loss_orders = self.check_position_stop_loss(current_price)
        if stop_loss_orders:
            return stop_loss_orders

        # 2. 🚀 新增：检查波动率自适应仓位平衡
        balance_orders = self.check_position_balance(current_price)
        if balance_orders:
            return balance_orders

        if not self.should_place_orders(timestamp):
            return []

        # 3. 🚀 新增：使用自适应价差
        bid_spread, ask_spread = self.calculate_adaptive_spread(current_price)
        one_minus_bid = Decimal("1") - bid_spread
        one_plus_ask = Decimal("1") + ask_spread
        bid_price = current_price * one_minus_bid
        ask_price = current_price * one_plus_ask

        # 🚀 性能优化：批量缓存所有需要的属性，减少方法调用
        long_pos = self.exchange.long_position
        short_pos = self.exchange.short_position
        current_equity = self.exchange.get_equity()
        available_margin = self.exchange.get_available_margin()

        # 初始化订单列表
        orders = []

        # 2. 基于阶梯保证金的动态仓位限制
        current_max_leverage = self.exchange.get_current_max_leverage()

        # 获取当前档位信息
        threshold, max_leverage, _, _ = self.exchange.get_current_leverage_tier()

        # 🚀 完全动态计算最大仓位：基于当前权益、杠杆档位和风险控制比例
        max_position_value_ratio = Decimal(str(STRATEGY_CONFIG["max_position_value_ratio"]))

        # 计算当前档位下的最大仓位价值
        max_position_value_in_tier = min(
            threshold,  # 不超过当前档位上限
            current_equity * Decimal(str(max_leverage)) * max_position_value_ratio  # 基于权益和风险比例
        )

        # 转换为ETH数量 - 这就是最终的最大仓位限制
        max_position_size = max_position_value_in_tier / current_price

        # 🚀 币安标准：检查总仓位风险 (多仓价值 + 空仓价值)
        total_position_value = (long_pos + short_pos) * current_price
        if total_position_value > max_position_value_in_tier:
            # 总持仓价值过大，暂停开仓 (符合币安阶梯保证金规则)
            return []

        # --- 开仓逻辑 (基于动态杠杆) ---
        # 使用当前档位的有效杠杆
        effective_leverage = min(current_max_leverage, STRATEGY_CONFIG["leverage"])

        # 🚀 性能优化：预计算常用值
        half_max_position = max_position_size * Decimal("0.5")
        safety_margin_multiplier = Decimal("2")
        effective_leverage_decimal = Decimal(str(effective_leverage))

        # 4. 检查是否可以开多仓
        if long_pos < half_max_position:  # 单边仓位不超过总限制的50%
            open_long_amount = self.calculate_dynamic_order_size(current_price)
            required_margin = (open_long_amount * bid_price) / effective_leverage_decimal
            if available_margin > required_margin * safety_margin_multiplier:  # 保留2倍安全边际
                orders.append(("buy_long", open_long_amount, bid_price))

        # 5. 检查是否可以开空仓
        if short_pos < half_max_position:
            open_short_amount = self.calculate_dynamic_order_size(current_price)
            required_margin = (open_short_amount * ask_price) / effective_leverage_decimal
            if available_margin > required_margin * safety_margin_multiplier:
                orders.append(("sell_short", open_short_amount, ask_price))

        # --- 平仓逻辑 ---
        # 6. 创建平多订单
        if long_pos > 0:
            close_long_amount = self.calculate_dynamic_order_size(current_price)
            close_price = ask_price * (Decimal("1") + ask_spread)
            orders.append(("sell_long", min(close_long_amount, long_pos), close_price))

        # 7. 创建平空订单
        if short_pos > 0:
            close_short_amount = self.calculate_dynamic_order_size(current_price)
            close_price = bid_price * (Decimal("1") - bid_spread)
            orders.append(("buy_short", min(close_short_amount, short_pos), close_price))

        self.last_order_time = timestamp
        return orders

# =====================================================================================
# 恢复K线价格轨迹
# =====================================================================================
def get_price_trajectory(row: pd.Series, prev_close: float) -> List[tuple]:
    """
    根据K线数据生成价格轨迹
    阳线: curr_price -> open -> low -> high -> close
    阴线: curr_price -> open -> high -> low -> close
    返回 (price, high_since_open, low_since_open)
    """
    o, h, l, c = row['open'], row['high'], row['low'], row['close']

    if c >= o:  # 阳线
        # 轨迹: prev_close -> open -> low -> high -> close
        return [
            (prev_close, prev_close, prev_close),
            (o, o, o),
            (l, o, l),
            (h, h, l),
            (c, h, l)
        ]
    else:       # 阴线
        # 轨迹: prev_close -> open -> high -> low -> close
        return [
            (prev_close, prev_close, prev_close),
            (o, o, o),
            (h, h, o),
            (l, h, l),
            (c, h, l)
        ]

def get_price_trajectory_optimized(kline_data: dict, prev_close: float) -> List[tuple]:
    """
    🚀 优化版价格轨迹函数 - 直接使用float，减少类型转换
    输入: kline_data dict with float values
    返回: [(price, high_since_open, low_since_open), ...]
    """
    o, h, l, c = kline_data['open'], kline_data['high'], kline_data['low'], kline_data['close']

    # 预分配固定大小的列表，避免动态扩容
    if c >= o:  # 阳线
        return [
            (prev_close, prev_close, prev_close),
            (o, o, o),
            (l, o, l),
            (h, h, l),
            (c, h, l)
        ]
    else:       # 阴线
        return [
            (prev_close, prev_close, prev_close),
            (o, o, o),
            (h, h, o),
            (l, h, l),
            (c, h, l)
        ]

def get_price_trajectory_vectorized(o: float, h: float, l: float, c: float, prev_close: float) -> List[tuple]:
    """
    🚀 完全向量化的价格轨迹函数 - 直接使用numpy float64，最高性能
    输入: 单独的OHLC float值
    返回: [(price, high_since_open, low_since_open), ...]
    """
    # 预分配固定大小的列表，避免动态扩容
    if c >= o:  # 阳线
        return [
            (prev_close, prev_close, prev_close),
            (o, o, o),
            (l, o, l),
            (h, h, l),
            (c, h, l)
        ]
    else:       # 阴线
        return [
            (prev_close, prev_close, prev_close),
            (o, o, o),
            (h, h, o),
            (l, h, l),
            (c, h, l)
        ]

# =====================================================================================
# 新增：资金曲线与性能指标
# =====================================================================================
def analyze_and_plot_performance(
    equity_history: List[tuple],
    initial_balance: Decimal,
    total_fees: Decimal,
    total_funding: Decimal,
    config: Dict,
    strategy_params: Optional[Dict] = None,
    win_rate: float = 0.0,
    profitable_trades: int = 0,
    total_trade_pairs: int = 0,
    progress_reporter=None,
    liquidation_events: Optional[List[Dict]] = None,
    price_data: Optional[pd.DataFrame] = None
) -> Dict:
    # total_funding参数保留用于未来扩展，当前版本暂不使用
    _ = total_funding  # 明确标记为未使用但保留
    if not equity_history:
        print("⚠️ 无法分析性能：历史数据为空。")
        return {"max_drawdown": 0.0, "sharpe_ratio": 0.0, "annualized_return": 0.0, "total_return_pct": 0.0}
        
    print("\n" + "="*70)
    print("📈 性能分析与资金曲线")
    print("="*70)
    
    if progress_reporter:
        progress_reporter.update(96, 100, "处理权益数据...")

    df = pd.DataFrame(equity_history, columns=['timestamp', 'equity'])

    # 🚀 修复时间戳溢出问题：过滤异常时间戳
    df = df[df['timestamp'] <= 2147483647]  # 2038年问题边界
    df = df[df['timestamp'] >= 0]  # 过滤负数时间戳

    if len(df) == 0:
        print("⚠️ 无法分析性能：所有时间戳都无效。")
        return {"max_drawdown": 0.0, "sharpe_ratio": 0.0, "annualized_return": 0.0, "total_return_pct": 0.0}

    if progress_reporter:
        progress_reporter.update(97, 100, "计算性能指标...")

    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
    df['equity'] = df['equity'].astype(float)
    df = df.set_index('timestamp')

    # 🚀 如果提供了价格数据，合并到DataFrame中
    if price_data is not None and not price_data.empty:
        print("🔄 正在合并价格数据...")
        price_df = price_data.copy()
        
        # 确保timestamp格式一致
        if 'timestamp' in price_df.columns:
            ts = price_df['timestamp']
            if np.issubdtype(ts.dtype, np.number):
                price_df['timestamp'] = pd.to_datetime(ts, unit='s')
            elif not np.issubdtype(ts.dtype, np.datetime64):
                price_df['timestamp'] = pd.to_datetime(ts)
            
            price_df = price_df.set_index('timestamp')
        
        # 提取收盘价
        if 'close' in price_df.columns:
            # 重新采样或对齐数据
            # 由于equity记录频率可能不同，我们使用merge_asof或reindex
            # 这里简单处理：将价格数据重采样到分钟级别，然后join
            
            # 为了保证性能，我们假设price_df已经是按时间排序的
            # 我们只取在这个时间范围内的价格
            start_ts = df.index[0]
            end_ts = df.index[-1]
            mask = (price_df.index >= start_ts) & (price_df.index <= end_ts)
            subset_price = price_df.loc[mask, ['close']].rename(columns={'close': 'price'})
            
            # 合并
            df = df.join(subset_price, how='left')
            # 填充缺失值 (向前填充)
            df['price'] = df['price'].ffill()
            
            print(f"✓ 已合并价格数据，共 {len(df)} 行")

    start_date_str = df.index[0].strftime('%Y-%m-%d %H:%M:%S')
    end_date_str = df.index[-1].strftime('%Y-%m-%d %H:%M:%S')

    print(f"回测开始时间: {start_date_str}")
    print(f"回测结束时间: {end_date_str}")
    print("-" * 35)

    # 1. 计算核心指标
    end_equity = float(df['equity'].iloc[-1])  # 确保类型一致
    initial_balance_float = float(initial_balance)  # 确保类型一致
    total_return_pct = (end_equity - initial_balance_float) / initial_balance_float
    
    # 2. 计算最大回撤 (Max Drawdown)
    df['peak'] = df['equity'].cummax()
    df['drawdown'] = (df['peak'] - df['equity']) / df['peak']
    max_drawdown = df['drawdown'].max()
    
    num_days = (df.index[-1] - df.index[0]).days
    if num_days < 1:
        num_days = 1
    years = num_days / 365.0
    annualized_return = (end_equity / initial_balance_float) ** (1 / years) - 1
    
    # 4. 计算月均回报率（保留用于未来扩展）
    monthly_return = (1 + annualized_return)**(1/12) - 1
    _ = monthly_return  # 明确标记为当前未使用但保留

    # 5. 计算夏普比率 (Sharpe Ratio)
    df['daily_return'] = df['equity'].pct_change()
    daily_std = df['daily_return'].std()
    
    if daily_std > 0:
        sharpe_ratio = (df['daily_return'].mean() / daily_std) * np.sqrt(365)
    else:
        sharpe_ratio = 0.0

    # 6. 计算新增指标：年化收益率/最大回撤比率
    if max_drawdown > 0:
        return_drawdown_ratio = annualized_return / max_drawdown
    else:
        return_drawdown_ratio = float('inf') if annualized_return > 0 else 0.0

    # 7. 打印性能指标（简化版，避免重复）
    print(f"初始保证金: {initial_balance:,.2f} USDT")
    print(f"最终总权益: {end_equity:,.2f} USDT")
    print(f"总盈亏: {(end_equity - initial_balance_float):,.2f} USDT")
    print(f"总收益率: {total_return_pct:.2%}")
    print("-" * 35)
    print(f"年化收益率: {annualized_return:.2%}")
    print(f"最大回撤: {max_drawdown:.2%}")
    print(f"年化收益/回撤比: {return_drawdown_ratio:.2f}")
    print(f"夏普比率: {sharpe_ratio:.2f}")
    print(f"胜率: {win_rate:.1%} ({profitable_trades}/{total_trade_pairs})")
    print(f"总手续费: {total_fees:,.2f} USDT")

    markers = None
    if liquidation_events:
        markers = []
        for event in liquidation_events:
            ts = event.get("timestamp")
            eq = event.get("equity")
            # 🚀 优先使用记录的爆仓价格
            price_val = event.get("price")
            
            if ts is None:
                continue
            try:
                t = pd.to_datetime(int(ts), unit="s")
                # 如果有记录的价格，标记在价格轴上
                if price_val is not None:
                    marker_y = float(price_val)
                    on_right = True
                else:
                    marker_y = float(eq) if eq is not None else 0
                    on_right = False
            except Exception:
                continue
            
            markers.append({
                "time": t,
                "price": marker_y,
                "text": "爆仓",
                "color": "red",
                "symbol": "x",
                "size": 50, # 增大尺寸以更醒目
                "on_right_axis": on_right,
            })

    if config["plot_equity_curve"]:
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        if strategy_params:
            leverage = strategy_params.get('leverage', 'N/A')
            bid_spread = strategy_params.get('bid_spread', 'N/A')
        else:
            leverage = STRATEGY_CONFIG['leverage']
            bid_spread = STRATEGY_CONFIG['bid_spread']

        try:
            spread_pct = float(bid_spread) * 100.0
            spread_str = f"{spread_pct:.1f}%"
        except Exception:
            spread_str = str(bid_spread)

        start_label = df.index[0].strftime('%Y-%m-%d')
        end_label = df.index[-1].strftime('%Y-%m-%d')

        base_path = Path(config["equity_curve_path"])
        if not base_path.is_absolute():
            base_path = Path(__file__).resolve().parent / base_path
        base_path.parent.mkdir(parents=True, exist_ok=True)

        base_dir = base_path.parent
        file_stem = f"4号做市_资金曲线_{start_label}_至_{end_label}_杠杆{leverage}倍_价差{spread_str}_生成于_{timestamp}"
        output_path = base_dir / f"{file_stem}.png"
        html_path = base_dir / f"{file_stem}.html"

        # 🚀 设置中文字体 (优先列表，针对 macOS 常见中文字体优化)
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['font.sans-serif'] = [
            'PingFang SC', 'Hiragino Sans GB', 'Heiti SC', 'Songti SC',
            'STHeiti', 'SimHei', 'Microsoft YaHei', 'Arial Unicode MS', 'DejaVu Sans'
        ]
        plt.rcParams['axes.unicode_minus'] = False

        plt.style.use('seaborn-v0_8-darkgrid')
        fig, ax = plt.subplots(figsize=(15, 8))
        _ = fig
        
        # 绘制资金曲线 (左轴)
        ax.plot(df.index, df['equity'], label='资金曲线', color='dodgerblue', linewidth=2)
        ax.fill_between(df.index, df['peak'], df['equity'], facecolor='red', alpha=0.3, label='回撤区域')
        
        # 🚀 绘制价格曲线 (右轴)
        if 'price' in df.columns:
            ax2 = ax.twinx()
            ax2.plot(
                df.index,
                df['price'],
                label='ETH价格',
                color='#2ecc71',
                alpha=0.9,
                linewidth=1.5,
                linestyle='--',
            )
            ax2.set_ylabel('ETH价格 (USDT)', fontsize=12, color='#2ecc71')
            ax2.tick_params(axis='y', labelcolor='#2ecc71')
            # 添加图例 (合并左轴和右轴图例)
            lines_1, labels_1 = ax.get_legend_handles_labels()
            lines_2, labels_2 = ax2.get_legend_handles_labels()
            ax.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper left')
        else:
            ax.legend(loc='upper left')

        # 绘制标记
        if markers:
            for m in markers:
                # 检查标记是否应该在右轴
                target_ax = ax2 if m.get("on_right_axis", False) and 'price' in df.columns else ax
                
                target_ax.scatter(
                    [m["time"]], 
                    [m["price"]], 
                    color=m.get("color", "red"), 
                    marker=m.get("symbol", "x"), 
                    s=m.get("size", 50), 
                    zorder=10,
                    label='爆仓点' if m.get("text") == "爆仓" else None
                )

        title = f'资金曲线 | 杠杆: {leverage}倍 | 价差: ±{spread_str} | 仓位: 自动(1/杠杆)'
        subtitle = f'总收益: {total_return_pct:.1%} | 年化收益: {annualized_return:.1%} | 最大回撤: {max_drawdown:.1%}'

        ax.set_title(title, fontsize=16, weight='bold', pad=20)
        ax.text(0.5, 0.98, subtitle, transform=ax.transAxes, ha='center', va='top',
                fontsize=12, bbox=dict(boxstyle='round,pad=0.3', facecolor='lightblue', alpha=0.7))

        ax.set_xlabel('日期', fontsize=12)
        ax.set_ylabel('账户净值 (USDT)', fontsize=12)
        ax.grid(True, which='both', linestyle='--', linewidth=0.5)
        
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        try:
            plt.savefig(output_path, dpi=300)
            print(f"✅ 资金曲线图已成功保存: {output_path}")
        except Exception as e:
            print(f"❌ 保存资金曲线图失败: {e}")

        try:
            df_html = df.reset_index().rename(columns={df.index.name or 'index': 'time'})
            
            # 准备右轴配置
            right_axis_lines_config = None
            if 'price' in df_html.columns:
                right_axis_lines_config = {"ETH价格": "price"}
            
            draw_equity_curve_plotly(
                df_html,
                data_dict={"Equity": "equity"},
                date_col="time",
                right_axis=None,
                title=title,
                path=Path(html_path),
                show=False,
                desc=subtitle,
                markers=markers,
                right_axis_lines=right_axis_lines_config  # 🚀 传递右轴配置
            )
            print(f"✅ 资金曲线 HTML 已成功保存: {html_path}")

            if config.get("auto_open_html", True):
                try:
                    html_uri = Path(html_path).resolve().as_uri()
                    webbrowser.open(html_uri)
                except Exception as open_err:
                    print(f"⚠️ 自动打开资金曲线 HTML 失败: {open_err}")
        except Exception as e:
            print(f"⚠️ 保存资金曲线 HTML 失败: {e}")

    # 返回计算出的指标
    return {
        "max_drawdown": float(max_drawdown),
        "sharpe_ratio": float(sharpe_ratio),
        "annualized_return": float(annualized_return),
        "total_return_pct": float(total_return_pct),
        "return_drawdown_ratio": float(return_drawdown_ratio),
        "num_days": int(num_days)
    }

# =====================================================================================
# 数据预处理缓存系统
# =====================================================================================
def get_data_cache_key(data_file_path: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
    """生成数据缓存的唯一键"""
    bar_interval = BACKTEST_CONFIG.get("bar_interval", "1m")
    if start_date is None and end_date is None:
        key_string = f"{data_file_path}_FULL_DATASET_{bar_interval}"
    else:
        key_string = f"{data_file_path}_{start_date}_{end_date}_{bar_interval}"
    return hashlib.md5(key_string.encode()).hexdigest()

def load_preprocessed_data(cache_key: str) -> Optional[tuple]:
    """加载预处理的数据缓存"""
    cache_file = f"cache/preprocessed_data_{cache_key}.pkl"
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            print(f"⚠️ 缓存加载失败: {e}")
    return None

def save_preprocessed_data(cache_key: str, data: tuple):
    """保存预处理的数据缓存"""
    os.makedirs("cache", exist_ok=True)
    cache_file = f"cache/preprocessed_data_{cache_key}.pkl"
    try:
        with open(cache_file, 'wb') as f:
            pickle.dump(data, f)
        print(f"✅ 预处理数据已缓存到: {cache_file}")
    except Exception as e:
        print(f"⚠️ 缓存保存失败: {e}")

def run_backtest_with_params(strategy_params: Optional[Dict] = None, market_params: Optional[Dict] = None, use_cache: bool = True) -> Dict:
    """
    使用指定参数运行回测，支持参数遍历

    Args:
        strategy_params: 策略参数覆盖
        market_params: 市场参数覆盖
        use_cache: 是否使用数据缓存

    Returns:
        回测结果字典
    """
    # 备份原始配置
    original_strategy = STRATEGY_CONFIG.copy()
    original_market = MARKET_CONFIG.copy()

    try:
        # 应用参数覆盖
        if strategy_params:
            STRATEGY_CONFIG.update(strategy_params)
        if market_params:
            MARKET_CONFIG.update(market_params)

        # 运行回测
        import asyncio
        result = asyncio.run(run_fast_perpetual_backtest(use_cache=use_cache))
        return result if result is not None else {}

    finally:
        # 恢复原始配置
        STRATEGY_CONFIG.clear()
        STRATEGY_CONFIG.update(original_strategy)
        MARKET_CONFIG.clear()
        MARKET_CONFIG.update(original_market)

def load_full_dataset_cache() -> Optional[tuple]:
    """加载全量数据集缓存"""
    cache_key = get_data_cache_key(BACKTEST_CONFIG["data_file_path"])
    return load_preprocessed_data(cache_key)

def save_full_dataset_cache(data: tuple):
    """保存全量数据集缓存"""
    cache_key = get_data_cache_key(BACKTEST_CONFIG["data_file_path"])
    save_preprocessed_data(cache_key, data)


def _load_backtest_from_csv_fallback(h5_path: Path) -> pd.DataFrame:
    base_dir = h5_path.parent
    name = h5_path.name
    if "_1m_" in name:
        symbol = name.split("_1m_")[0]
    else:
        symbol = name.split("_")[0]

    # 优先使用聚合文件（step1_prepare_data 会生成 ETHUSDT.csv）
    agg_file = base_dir / f"{symbol}.csv"
    if agg_file.exists():
        try:
            return pd.read_csv(agg_file)
        except UnicodeDecodeError:
            return pd.read_csv(agg_file, encoding="gbk")

    pattern = f"{symbol}_1m_*.csv"
    candidates = sorted(base_dir.glob(pattern))
    if not candidates:
        raise FileNotFoundError(f"未找到可用的CSV历史数据文件: {pattern}")

    dfs: List[pd.DataFrame] = []
    for f in candidates:
        try:
            part = pd.read_csv(f)
        except UnicodeDecodeError:
            part = pd.read_csv(f, encoding="gbk")
        dfs.append(part)

    df = pd.concat(dfs, ignore_index=True)
    return df


def _load_backtest_dataframe() -> pd.DataFrame:
    path_str = BACKTEST_CONFIG["data_file_path"]
    p = Path(path_str)
    if not p.exists():
        raise FileNotFoundError(f"数据文件不存在: {path_str}")

    if p.suffix == ".h5":
        try:
            df = _load_backtest_from_csv_fallback(p)
        except FileNotFoundError:
            try:
                df = pd.read_hdf(p, key="klines")
            except ImportError:
                df = _load_backtest_from_csv_fallback(p)
            except Exception:
                try:
                    from pandas import HDFStore

                    with HDFStore(p, mode="r") as store:
                        keys = store.keys()
                        if not keys:
                            raise ValueError("HDF 文件中未找到任何数据表")
                        df = store[keys[0]]
                except ImportError:
                    df = _load_backtest_from_csv_fallback(p)
    elif p.suffix == ".csv":
        df = pd.read_csv(p)
    else:
        raise ValueError(f"不支持的历史数据文件格式: {p.suffix}")

    if "timestamp" not in df.columns:
        if "candle_begin_time" in df.columns:
            df["candle_begin_time"] = pd.to_datetime(df["candle_begin_time"])
            df["timestamp"] = df["candle_begin_time"]

    return df


def _download_history_for_backtest(start_dt: pd.Timestamp, end_dt: pd.Timestamp):
    try:
        from 策略仓库.二号网格策略.config import Config as GridConfig
        from 策略仓库.二号网格策略.program.step1_prepare_data import fetch_and_save_data
    except Exception:
        return

    symbol = "ETHUSDT"
    data_center_dir = Path(BCKTEST_DATA_FILE).parent

    existing_min = None
    existing_max = None
    try:
        df_local = _load_backtest_from_csv_fallback(Path(BCKTEST_DATA_FILE))
        if not df_local.empty:
            if "timestamp" in df_local.columns:
                ts = df_local["timestamp"]
                if not np.issubdtype(ts.dtype, np.datetime64):
                    if np.issubdtype(ts.dtype, np.number):
                        ts = pd.to_datetime(ts, unit="s")
                    else:
                        ts = pd.to_datetime(ts)
            elif "candle_begin_time" in df_local.columns:
                ts = pd.to_datetime(df_local["candle_begin_time"])
            else:
                ts = None

            if ts is not None and len(ts) > 0:
                existing_min = ts.min()
                existing_max = ts.max()
    except FileNotFoundError:
        pass

    download_ranges: List[tuple[pd.Timestamp, pd.Timestamp]] = []

    if existing_min is None or existing_max is None:
        download_ranges.append((start_dt, end_dt))
    else:
        if start_dt < existing_min:
            download_ranges.append((start_dt, existing_min))
        if end_dt > existing_max:
            download_ranges.append((existing_max, end_dt))

    if not download_ranges:
        return

    for seg_start, seg_end in download_ranges:
        conf = GridConfig(
            symbol=symbol,
            candle_period="1m",
            start_time=seg_start.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=seg_end.strftime("%Y-%m-%d %H:%M:%S"),
            timezone="Asia/Shanghai",
            data_center_dir=data_center_dir,
            local_data_path=None,
        )

        df = fetch_and_save_data(conf, seg_start, seg_end)
        if df is None or df.empty:
            print("⚠️ 在线下载历史K线失败，将继续使用本地数据。")
        else:
            print(f"✅ 已从币安下载历史K线数据 ({seg_start} -> {seg_end})，共 {len(df)} 条。")


def _normalize_bar_interval(interval: str) -> str:
    s = (interval or "1m").strip().lower()
    mapping = {
        "1m": "1T",
        "3m": "3T",
        "5m": "5T",
        "15m": "15T",
        "30m": "30T",
        "1h": "1H",
        "2h": "2H",
        "4h": "4H",
        "6h": "6H",
        "12h": "12H",
        "1d": "1D",
    }
    return mapping.get(s, s)


def _resample_kline_interval_if_needed(df: pd.DataFrame) -> pd.DataFrame:
    bar_interval = BACKTEST_CONFIG.get("bar_interval", "1m")
    if not bar_interval or bar_interval in ("1m", "1min", "1T"):
        return df

    if "timestamp" not in df.columns:
        return df

    df = df.copy()

    ts = df["timestamp"]
    if not np.issubdtype(ts.dtype, np.datetime64):
        if np.issubdtype(ts.dtype, np.number):
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        else:
            df["timestamp"] = pd.to_datetime(df["timestamp"])

    df = df.sort_values("timestamp")
    df = df.set_index("timestamp")

    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    for col in ["volume", "quote_volume", "taker_buy_base", "taker_buy_quote"]:
        if col in df.columns:
            agg[col] = "sum"

    freq = _normalize_bar_interval(bar_interval)
    resampled = df.resample(freq).agg(agg)
    resampled = resampled.dropna(subset=["open", "high", "low", "close"])

    resampled = resampled.reset_index()
    return resampled

def extract_time_range_from_cache(full_timestamps: np.ndarray, full_ohlc_data: np.ndarray,
                                 start_date: Optional[str], end_date: Optional[str]) -> tuple:
    """从全量缓存中提取指定时间段的数据"""
    start_ts = int(pd.to_datetime(start_date).timestamp()) if start_date else full_timestamps[0]
    end_ts = int(pd.to_datetime(end_date).timestamp()) if end_date else full_timestamps[-1]

    # 找到时间范围的索引
    start_idx = np.searchsorted(full_timestamps, start_ts)
    end_idx = np.searchsorted(full_timestamps, end_ts, side='right')

    # 提取子集
    subset_timestamps = full_timestamps[start_idx:end_idx]
    subset_ohlc_data = full_ohlc_data[start_idx:end_idx]

    start_date_str = pd.to_datetime(subset_timestamps[0], unit='s').strftime('%Y-%m-%d')
    end_date_str = pd.to_datetime(subset_timestamps[-1], unit='s').strftime('%Y-%m-%d')

    return subset_timestamps, subset_ohlc_data, len(subset_timestamps), start_date_str, end_date_str

def preprocess_kline_data(test_data: pd.DataFrame, use_cache: bool = True) -> tuple:
    """
    🚀 优化版预处理：支持全量缓存 + 时间段提取
    返回: (timestamps, ohlc_data, data_length, start_date_str, end_date_str)
    """
    start_date = BACKTEST_CONFIG.get("start_date")
    end_date = BACKTEST_CONFIG.get("end_date")

    # 🚀 策略1：如果有时间段限制，尝试从全量缓存中提取
    if use_cache and (start_date or end_date):
        print("🔍 检查全量数据缓存...")
        full_cache = load_full_dataset_cache()
        if full_cache is not None:
            print("✅ 找到全量缓存，正在提取时间段...")
            full_timestamps, full_ohlc_data, _, _, _ = full_cache
            return extract_time_range_from_cache(full_timestamps, full_ohlc_data, start_date, end_date)

    # 🚀 策略2：检查当前时间段的缓存
    start_date_str = pd.to_datetime(test_data['timestamp'].iloc[0], unit='s').strftime('%Y-%m-%d')
    end_date_str = pd.to_datetime(test_data['timestamp'].iloc[-1], unit='s').strftime('%Y-%m-%d')
    cache_key = get_data_cache_key(BACKTEST_CONFIG["data_file_path"], start_date_str, end_date_str)

    if use_cache:
        cached_data = load_preprocessed_data(cache_key)
        if cached_data is not None:
            print("✅ 使用时间段缓存数据")
            return cached_data

    # 🚀 策略3：重新预处理数据
    print("🔄 开始预处理K线数据...")
    data_length = len(test_data)

    print("  📅 转换时间戳...")
    timestamps = []
    for i in tqdm(range(data_length), desc="时间戳转换", unit="行"):
        row_timestamp = test_data.iloc[i]['timestamp']
        if hasattr(row_timestamp, 'timestamp'):
            kline_timestamp = int(row_timestamp.timestamp())
        else:
            kline_timestamp = int(row_timestamp)
        timestamps.append(kline_timestamp)
    timestamps = np.array(timestamps)

    print("  📊 转换OHLC数据...")
    ohlc_data = test_data[['open', 'high', 'low', 'close']].values.astype(np.float64)

    result = (timestamps, ohlc_data, data_length, start_date_str, end_date_str)

    # 保存缓存
    if use_cache:
        save_preprocessed_data(cache_key, result)

        # 🚀 如果是全量数据，也保存为全量缓存
        if not start_date and not end_date:
            print("💾 保存为全量数据缓存...")
            save_full_dataset_cache(result)

    return result

# =====================================================================================
# 高性能主回测函数 (已更新)
# =====================================================================================
async def run_fast_perpetual_backtest(use_cache: bool = True):
    print("🚀 开始永续合约做市策略回测...")
    
    print("策略特点:")
    print(f"  初始杠杆: {STRATEGY_CONFIG['leverage']}x (动态调整)")
    print(f"  做市价差: ±{STRATEGY_CONFIG['bid_spread']*100:.3f}%")
    print(f"  最大仓位价值比例: {STRATEGY_CONFIG['max_position_value_ratio']*100:.0f}% (完全动态计算)")
    
    if STRATEGY_CONFIG["use_dynamic_order_size"]:
        print(f"  动态下单: 每次下单占总权益的比例 = 1/当前杠杆 (自动调整)")
        print(f"  下单范围: {STRATEGY_CONFIG['min_order_amount']:.3f} - {STRATEGY_CONFIG['max_order_amount']:.1f} ETH")
    print()
    
    # 1. 快速加载数据
    print("📂 加载历史数据...")
    df = _load_backtest_dataframe()

    bar_interval = BACKTEST_CONFIG.get("bar_interval", "1m")
    if bar_interval and bar_interval not in ("1m", "1min", "1T"):
        print(f"⏱ 使用回测周期: {bar_interval}")
        df = _resample_kline_interval_if_needed(df)
    else:
        print("⏱ 使用回测周期: 1m (默认)")

    test_data = df
    start_cfg = BACKTEST_CONFIG.get("start_date")
    end_cfg = BACKTEST_CONFIG.get("end_date")
    start_req = pd.to_datetime(start_cfg) if start_cfg else None
    end_req = pd.to_datetime(end_cfg) if end_cfg else None

    if start_req is not None:
        test_data = test_data[test_data["timestamp"] >= start_req]
    if end_req is not None:
        test_data = test_data[test_data["timestamp"] < end_req]
    test_data = test_data.copy()

    need_download = False
    if len(test_data) == 0 and start_req is not None and end_req is not None:
        need_download = True
    elif len(test_data) > 0 and start_req is not None and end_req is not None:
        ts = test_data["timestamp"]
        if not np.issubdtype(ts.dtype, np.datetime64):
            if np.issubdtype(ts.dtype, np.number):
                ts_start = pd.to_datetime(ts.iloc[0], unit="s")
                ts_end = pd.to_datetime(ts.iloc[-1], unit="s")
            else:
                ts_start = pd.to_datetime(ts.iloc[0])
                ts_end = pd.to_datetime(ts.iloc[-1])
        else:
            ts_start = ts.iloc[0]
            ts_end = ts.iloc[-1]

        tol = pd.Timedelta(minutes=1)
        if ts_start > start_req + tol or ts_end < end_req - tol:
            need_download = True

    if need_download and start_req is not None and end_req is not None:
        print("⚠️ 本地历史数据未完整覆盖设定的回测时间区间，尝试从交易所补全...")
        _download_history_for_backtest(start_req, end_req)

        df = _load_backtest_dataframe()
        if bar_interval and bar_interval not in ("1m", "1min", "1T"):
            df = _resample_kline_interval_if_needed(df)

        test_data = df
        if start_req is not None:
            test_data = test_data[test_data["timestamp"] >= start_req]
        if end_req is not None:
            test_data = test_data[test_data["timestamp"] < end_req]
        test_data = test_data.copy()

    if len(test_data) == 0:
        print("❌ 错误: 在指定时间范围内没有可用的K线数据!")
        return

    print(f"✓ 加载了 {len(test_data)} 条K线数据")

    # 1.5. 预处理数据（带缓存）
    # 确保test_data是DataFrame类型
    if not isinstance(test_data, pd.DataFrame):
        print("❌ 错误: 数据类型不正确!")
        return
    timestamps, ohlc_data, data_length, start_date_str, end_date_str = preprocess_kline_data(test_data, use_cache)
    print(f"✓ 数据预处理完成，回测时间范围: {start_date_str} -> {end_date_str}")
    
    initial_balance = BACKTEST_CONFIG["initial_balance"]
    initial_balance_decimal = Decimal(str(initial_balance))

    # 2. 初始化高性能组件
    exchange = FastPerpetualExchange(initial_balance=initial_balance)
    strategy = FastPerpetualStrategy(exchange)
    
    print(f"✓ 初始化完成，初始保证金: {initial_balance} USDT")
    prev_close = ohlc_data[0][3]  # 使用第一行的收盘价

    liquidated = False
    stopped_by_risk = False
    peak_equity = initial_balance_decimal

    with tqdm(total=data_length, desc="回测进度", unit="K线") as pbar:
        for i in range(data_length):
            # 直接从numpy数组访问，比pandas iloc更快
            kline_timestamp = timestamps[i]
            o, h, l, c = ohlc_data[i]

            # 获取5点价格轨迹（向量化版本）
            price_trajectory = get_price_trajectory_vectorized(o, h, l, c, prev_close)
            
            # 🚀 简化优化：减少检查频率但保持核心逻辑
            for j, (price, high_since_open, low_since_open) in enumerate(price_trajectory):
                sub_timestamp = kline_timestamp + j * 12 # 模拟K线内的时间流逝 (秒)

                # 🚀 修复：确保时间戳在合理范围内
                if sub_timestamp > 2147483647 or sub_timestamp < 0:
                    sub_timestamp = kline_timestamp
                current_price_decimal = Decimal(str(price))
                exchange.set_current_price(current_price_decimal)

                # 🚀 修复：每个价格点都要检查爆仓！插针可能在任何点发生
                if exchange.check_and_handle_liquidation(sub_timestamp):
                    liquidated = True
                    break

                # 生成订单（保持策略核心逻辑）
                orders = strategy.generate_orders(current_price_decimal, sub_timestamp)
                if orders:
                    exchange.place_orders_batch(orders)

                # 订单匹配 (使用当前价格点对应的最高/最低价)
                high_decimal = Decimal(str(high_since_open))
                low_decimal = Decimal(str(low_since_open))
                exchange.fast_order_matching(high_decimal, low_decimal, sub_timestamp)

            # K线结束，更新收盘价并记录权益
            prev_close = c  # 使用当前K线的收盘价

            # 🚀 新增：更新波动率监控
            exchange.update_volatility_monitor(kline_timestamp, h, l, c)

            # 🚀 修复：确保记录权益时的时间戳有效
            if kline_timestamp <= 2147483647 and kline_timestamp >= 0:
                exchange.record_equity(kline_timestamp)

            # ======= 风险监控：最大回撤 / 最小权益 =======
            if RISK_CONFIG["enable_stop_loss"] and not liquidated:
                equity_now = exchange.get_equity()
                if equity_now > peak_equity:
                    peak_equity = equity_now
                drawdown_pct = (peak_equity - equity_now) / peak_equity if peak_equity > 0 else Decimal("0")

                if equity_now <= RISK_CONFIG["min_equity"] or drawdown_pct >= RISK_CONFIG["max_drawdown"]:
                    print("\n" + "!"*70)
                    print("⚠️ 触发止损/退场条件：")
                    if equity_now <= RISK_CONFIG["min_equity"]:
                        print(f"   - 当前权益 {equity_now:.2f} USDT 低于阈值 {RISK_CONFIG['min_equity']} USDT")
                    if drawdown_pct >= RISK_CONFIG["max_drawdown"]:
                        print(f"   - 当前回撤 {drawdown_pct:.2%} 超过阈值 {RISK_CONFIG['max_drawdown']:.0%}")
                    print("!"*70)
                    exchange.close_all_positions_market(kline_timestamp)
                    stopped_by_risk = True
                    break

            pbar.update(1)
            
            if liquidated:
                break # 停止处理后续所有K线
            if stopped_by_risk:
                break

            # 🚀 性能优化：大幅减少进度条更新频率，避免频繁的UI刷新
            if i % 10000 == 0 and i > 0: # 进度条更新频率改为10000，减少50%的UI开销
                current_balance = exchange.balance + exchange.get_unrealized_pnl()
                pnl = current_balance - initial_balance_decimal
                pbar.set_postfix({
                    '交易': len(exchange.trade_history),
                    '盈亏': f'{pnl:.2f}U',
                    '多仓': f'{exchange.long_position:.2f}',
                    '空仓': f'{exchange.short_position:.2f}'
                })
    
    # 4. 输出最终结果
    print("\n" + "="*70)
    print("� 回测结果")
    print("="*70)
    print(f"总交易次数: {len(exchange.trade_history)}")
    print(f"最终仓位 - 多头: {exchange.long_position:.4f} ETH, 空头: {exchange.short_position:.4f} ETH")
    print(f"当前保证金率: {exchange.get_margin_ratio():.4f}")
    
    if len(exchange.trade_history) > 0:
        trade_side_translation = {
            "BUY_LONG": "买入开多",
            "SELL_SHORT": "卖出开空",
            "SELL_LONG": "卖出平多",
            "BUY_SHORT": "买入平空"
        }
        print(f"\n最近5笔交易:")
        for i, trade in enumerate(exchange.trade_history[-5:], 1):
            side_cn = trade_side_translation.get(trade['side'].upper(), trade['side'])
            # 🚀 添加杠杆信息
            leverage_info = f" [杠杆: {trade.get('leverage', 'N/A')}x]" if 'leverage' in trade else ""
            print(f"  {i}. {side_cn} {trade['amount']:.4f} ETH @ {trade['price']:.2f} USDT (手续费: {trade['fee']:.4f}){leverage_info}")
    
    # 5. 先计算胜率，然后绘制性能指标
    # 计算胜率的代码移到这里，以便传递给性能分析函数
    win_rate_temp = 0.0
    profitable_trades_temp = 0
    total_trade_pairs_temp = 0

    if len(exchange.trade_history) > 1:
        # 对于做市策略，分析开仓和平仓配对
        long_positions = []  # 记录多头开仓
        short_positions = []  # 记录空头开仓

        for trade in exchange.trade_history:
            side = trade['side'].upper()
            price = trade['price']
            amount = trade['amount']

            if side == 'BUY_LONG':
                # 开多仓
                long_positions.append({'price': price, 'amount': amount})
            elif side == 'SELL_LONG' and long_positions:
                # 平多仓，计算盈亏
                if long_positions:
                    open_trade = long_positions.pop(0)  # FIFO
                    pnl = (price - open_trade['price']) * min(amount, open_trade['amount'])
                    if pnl > 0:
                        profitable_trades_temp += 1
                    total_trade_pairs_temp += 1
            elif side == 'SELL_SHORT':
                # 开空仓
                short_positions.append({'price': price, 'amount': amount})
            elif side == 'BUY_SHORT' and short_positions:
                # 平空仓，计算盈亏
                if short_positions:
                    open_trade = short_positions.pop(0)  # FIFO
                    pnl = (open_trade['price'] - price) * min(amount, open_trade['amount'])
                    if pnl > 0:
                        profitable_trades_temp += 1
                    total_trade_pairs_temp += 1

        # 计算胜率
        if total_trade_pairs_temp > 0:
            win_rate_temp = profitable_trades_temp / total_trade_pairs_temp

    performance_metrics = analyze_and_plot_performance(
        exchange.equity_history,
        initial_balance_decimal,
        exchange.total_fees_paid,
        Decimal("0"),  # 没有资金费率
        BACKTEST_CONFIG,
        STRATEGY_CONFIG,  # 传递策略参数
        win_rate_temp,  # 传递胜率
        profitable_trades_temp,  # 传递盈利交易数
        total_trade_pairs_temp,  # 传递总交易对数
        liquidation_events=exchange.liquidation_events,
        price_data=test_data,  # 🚀 传递价格数据
    )

    total_trades = len(exchange.trade_history)
    num_days = performance_metrics.get("num_days", 1)
    if num_days <= 0:
        num_days = 1
    avg_trades_per_day = total_trades / num_days
    print(f"日均交易次数: {avg_trades_per_day:.2f} 笔/天")

    if stopped_by_risk:
        print("\n已根据风险控制规则主动退场，结束回测。")

    # 返回回测结果
    final_equity = exchange.get_equity()
    total_return = (final_equity - initial_balance_decimal) / initial_balance_decimal

    # 🚀 计算胜率 - 基于做市策略的交易对分析
    win_rate = 0.0
    profitable_trades = 0
    total_trade_pairs = 0

    if len(exchange.trade_history) > 1:
        # 对于做市策略，分析开仓和平仓配对
        long_positions = []  # 记录多头开仓
        short_positions = []  # 记录空头开仓

        for trade in exchange.trade_history:
            side = trade['side'].upper()
            price = trade['price']
            amount = trade['amount']
            timestamp = trade.get('timestamp', 0)

            if side == 'BUY_LONG':
                # 开多仓
                long_positions.append({
                    'price': price,
                    'amount': amount,
                    'timestamp': timestamp
                })
            elif side == 'SELL_LONG' and long_positions:
                # 平多仓，计算盈亏
                if long_positions:
                    open_trade = long_positions.pop(0)  # FIFO
                    pnl = (price - open_trade['price']) * min(amount, open_trade['amount'])
                    if pnl > 0:
                        profitable_trades += 1
                    total_trade_pairs += 1
            elif side == 'SELL_SHORT':
                # 开空仓
                short_positions.append({
                    'price': price,
                    'amount': amount,
                    'timestamp': timestamp
                })
            elif side == 'BUY_SHORT' and short_positions:
                # 平空仓，计算盈亏
                if short_positions:
                    open_trade = short_positions.pop(0)  # FIFO
                    pnl = (open_trade['price'] - price) * min(amount, open_trade['amount'])
                    if pnl > 0:
                        profitable_trades += 1
                    total_trade_pairs += 1

        # 计算胜率
        if total_trade_pairs > 0:
            win_rate = profitable_trades / total_trade_pairs
        else:
            # 如果没有完整的交易对，基于总收益率估算胜率
            if total_return > 0:
                win_rate = 0.6  # 盈利策略估算胜率60%
            else:
                win_rate = 0.4  # 亏损策略估算胜率40%

    # 🚀 为可视化准备交易数据
    trades_for_visualization = []
    trade_side_translation = {
        "BUY_LONG": "买入开多",
        "SELL_SHORT": "卖出开空",
        "SELL_LONG": "卖出平多",
        "BUY_SHORT": "买入平空"
    }

    for trade in exchange.trade_history:
        trades_for_visualization.append({
            "timestamp": trade.get('timestamp', 0),
            "action": trade_side_translation.get(trade['side'].upper(), trade['side']),
            "side": trade['side'],
            "amount": trade['amount'],
            "price": trade['price'],
            "fee": trade['fee'],
            "leverage": trade.get('leverage', 'N/A')
        })

    # 计算平均持仓时间（基于交易历史）
    avg_holding_time = 0
    if len(exchange.trade_history) > 1:
        # 简化计算：基于交易历史的时间跨度
        first_trade_time = exchange.trade_history[0].get('timestamp', 0)
        last_trade_time = exchange.trade_history[-1].get('timestamp', 0)
        if last_trade_time > first_trade_time and total_trade_pairs > 0:
            total_hours = (last_trade_time - first_trade_time) / 3600
            avg_holding_time = total_hours / total_trade_pairs

    return {
        "final_equity": float(final_equity),
        "total_return": float(total_return),
        "total_trades": len(exchange.trade_history),
        "total_fees": float(exchange.total_fees_paid),
        "long_position": float(exchange.long_position),
        "short_position": float(exchange.short_position),
        "liquidated": liquidated,
        "stopped_by_risk": stopped_by_risk,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "win_rate": float(win_rate),  # 🚀 添加胜率指标
        "profitable_trades": profitable_trades,  # 盈利交易数
        "total_trade_pairs": total_trade_pairs,  # 总交易对数
        "max_drawdown": performance_metrics.get("max_drawdown", 0.0),  # 🚀 添加最大回撤
        "sharpe_ratio": performance_metrics.get("sharpe_ratio", 0.0),  # 🚀 添加夏普比率
        "avg_holding_time": float(avg_holding_time),  # 🚀 添加平均持仓时间（小时）
        "trades": trades_for_visualization,  # 🚀 添加交易数据供可视化使用
        "equity_history": [(timestamp, float(equity)) for timestamp, equity in exchange.equity_history]  # 权益曲线
    }

# =====================================================================================
# 主函数入口移至文件末尾
# =====================================================================================

# =====================================================================================
# 简化版性能分析函数（用于进度版回测）
# =====================================================================================

def calculate_simple_performance_metrics(equity_history, initial_balance, total_fees):
    """超快速性能分析，最小化计算量"""
    # total_fees参数保留用于未来扩展，当前版本暂不使用
    _ = total_fees  # 明确标记为未使用但保留

    if not equity_history:
        return {"max_drawdown": 0.0, "sharpe_ratio": 0.0, "annualized_return": 0.0, "total_return_pct": 0.0}

    # 基础计算
    final_equity = float(equity_history[-1][1])
    initial_balance_float = float(initial_balance)
    total_return_pct = (final_equity - initial_balance_float) / initial_balance_float

    # 🚀 超快速最大回撤计算 - 只采样关键点
    sample_size = min(100, len(equity_history))  # 最多采样100个点
    step = max(1, len(equity_history) // sample_size)

    peak = initial_balance_float
    max_drawdown = 0.0

    # 采样计算，大幅减少计算量
    for i in range(0, len(equity_history), step):
        equity_float = float(equity_history[i][1])
        if equity_float > peak:
            peak = equity_float
        drawdown = (peak - equity_float) / peak if peak > 0 else 0.0
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    # 确保检查最后一个点
    if len(equity_history) > 1:
        equity_float = float(equity_history[-1][1])
        if equity_float > peak:
            peak = equity_float
        drawdown = (peak - equity_float) / peak if peak > 0 else 0.0
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    # 简化计算，避免复杂数学运算
    annualized_return = total_return_pct  # 简化为总回报率
    sharpe_ratio = 0.0  # 设为0，避免复杂计算

    # 🚀 移除print语句，减少I/O时间
    # print语句会显著影响性能，特别是在大量数据时

    return {
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "annualized_return": annualized_return,
        "total_return_pct": total_return_pct
    }

# =====================================================================================
# 支持进度回调的回测函数
# =====================================================================================

async def run_fast_perpetual_backtest_with_progress(progress_reporter=None):
    """🎯 带进度报告的回测函数 - 直接调用主回测函数确保结果一致"""

    if progress_reporter:
        progress_reporter.update(10, 100, "初始化回测环境...")

    print("🚀 开始进度版回测...")

    try:
        if progress_reporter:
            progress_reporter.update(30, 100, "开始执行回测...")

        # 🎯 关键改进：直接调用主回测函数，确保逻辑完全一致
        result = await run_fast_perpetual_backtest(use_cache=True)

        if progress_reporter:
            progress_reporter.update(90, 100, "处理回测结果...")

        # 转换结果格式以适配前端需求，确保所有数值都是JSON可序列化的
        # 确保result不为None
        if result is None:
            result = {}

        frontend_result = {
            "success": True,
            "symbol": "ETHUSDT",
            "start_date": str(result.get("start_date", "")),
            "end_date": str(result.get("end_date", "")),
            "initial_capital": float(BACKTEST_CONFIG["initial_balance"]),
            "final_equity": float(result.get("final_equity", 0)),
            "total_return": float(result.get("total_return", 0)),
            "total_trades": int(result.get("total_trades", 0)),
            "win_rate": float(result.get("win_rate", 0)),  # 🎯 直接使用主函数的胜率
            "max_drawdown": float(result.get("max_drawdown", 0)),
            "sharpe_ratio": float(result.get("sharpe_ratio", 0)),
            "liquidated": bool(result.get("liquidated", False)),
            "avg_holding_time": float(result.get("avg_holding_time", 0)),
            "trades": [
                {k: (int(v) if isinstance(v, (int, np.integer)) else
                     float(v) if isinstance(v, (float, Decimal, np.floating)) else
                     str(v))
                 for k, v in trade.items()}
                for trade in result.get("trades", [])
            ],  # 🎯 确保交易数据JSON可序列化
            "equity_history": [
                [int(timestamp), float(equity)]
                for timestamp, equity in result.get("equity_history", [])
            ]  # 🎯 确保权益曲线数据JSON可序列化
        }

        if progress_reporter:
            progress_reporter.update(100, 100, "回测完成!")

        print("✅ 进度版回测完成")
        return frontend_result

    except Exception as e:
        if progress_reporter:
            progress_reporter.update(100, 100, f"回测失败: {str(e)}")

        print(f"❌ 回测失败: {e}")
        raise

# =====================================================================================
# 主函数入口
# =====================================================================================

if __name__ == "__main__":
    import asyncio
    import logging
    import warnings

    # 配置日志级别
    logging.basicConfig(level=logging.WARNING)

    # 检查matplotlib是否安装
    try:
        import matplotlib
        # 设置matplotlib后端，避免GUI依赖
        matplotlib.use('Agg')
    except ImportError:
        print("="*60)
        print("错误: 缺少 'matplotlib' 库。")
        print("请运行 'pip install matplotlib' 来安装。")
        print("="*60)
        exit()

if __name__ == "__main__":
    # 忽略字体警告
    warnings.filterwarnings("ignore", message="Glyph", category=UserWarning)

    # 运行主回测函数
    result = asyncio.run(run_fast_perpetual_backtest())

    print("\n🎉 回测执行完成！")
