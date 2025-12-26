"""
Feature Engineering (特征工程)
-----------------------------
升级版：支持 LightGBM 模型所需的所有特征。
包含 OBI (各档), Spread, RSI, MA Deviation, Volatility 等。

特征列表:
['spread', 'obi_l1', 'obi_l5', 'obi_decay', 'obi_l10', 'obi_l20', 'obi_l50', 
 'ret_std_10', 'hl_range_10', 'dev_ma_60', 'rsi_14']
"""

from __future__ import annotations

import math
import numpy as np
from collections import deque
from dataclasses import dataclass, asdict
from typing import Deque, Optional, Tuple, Dict, List


@dataclass(frozen=True)
class FeatureSnapshot:
    """
    模型输入特征快照。
    字段名必须与模型训练时的 feature_names 一致。
    """
    mid_price: float
    
    # 核心特征
    spread: float
    obi_l1: float
    obi_l5: float
    obi_decay: float
    obi_l10: float
    obi_l20: float
    obi_l50: float
    
    # 时间序列特征
    ret_std_10: float
    hl_range_10: float
    dev_ma_60: float
    rsi_14: float
    
    # 辅助
    volatility: float  # 综合波动率
    vol_down: float    # 下行波动率 (用于 Bid)
    vol_up: float      # 上行波动率 (用于 Ask)
    toxicity: float    # 交易流毒性 (VPIN-lite)


class RollingFeatureEngine:
    """
    增强版滚动特征计算器。
    支持 RSI, MA, Volatility 和多档 OBI。
    """

    def __init__(self, window_ns: int) -> None:
        self.window_ns = window_ns
        
        # 基础数据容器
        self._mid_prices: Deque[float] = deque(maxlen=100) # 用于 MA 和 RSI
        self._returns: Deque[float] = deque(maxlen=100)    # 用于 Vol
        
        # 当前状态
        self._mid = 0.0
        self._spread = 0.0
        self._last_mid: Optional[float] = None
        
        # OBI 缓存
        self._obis: Dict[str, float] = {
            'obi_l1': 0.0, 'obi_l5': 0.0, 'obi_decay': 0.0,
            'obi_l10': 0.0, 'obi_l20': 0.0, 'obi_l50': 0.0
        }
        
        # 交易流缓存 (用于 Toxicity)
        # 存储元组 (ts_ns, amount, side_int)  side: 1=Buy, -1=Sell
        self._recent_trades: Deque[Tuple[int, float, int]] = deque(maxlen=1000)

    def update_quote(
        self,
        bid_price: float,
        ask_price: float,
        bid_size: float,
        ask_size: float,
        ts_ns: int,
        depth: Optional[Dict[str, np.ndarray]] = None  # 接收完整深度
    ) -> None:
        """
        更新行情并计算特征。
        :param depth: 字典, {'bids': [[p,q],...], 'asks': [[p,q],...]}
        """
        if bid_price <= 0.0 or ask_price <= 0.0:
            return
            
        mid = 0.5 * (bid_price + ask_price)
        self._mid = mid
        self._spread = ask_price - bid_price
        
        # 1. 计算 OBI 相关特征
        if depth:
            self._compute_depth_features(depth)
        else:
            # 回退：如果没有深度，仅用 L1
            obi = self._compute_obi_simple(bid_size, ask_size)
            for k in self._obis:
                self._obis[k] = obi

        # 2. 计算收益率
        if self._last_mid is not None and self._last_mid > 0.0 and mid > 0.0:
            ret = math.log(mid / self._last_mid)
            self._returns.append(ret)
        self._last_mid = mid
        self._mid_prices.append(mid)

        # 这里的 window_ns逻辑简化为定长 deque (tick-based) 以匹配常见的 ML 特征逻辑
        # 因为 RSI_14 通常指 14 个 bar/tick

    def dummy_update_trade(self, *args, **kwargs):
        pass

    def update_trade(self, last_qty: float, order_side: str, ts_ns: int) -> None:
        """
        更新成交流用于计算毒性。
        :param order_side: 'BUY' or 'SELL' (string) or int
        """
        # side_int: 1 for Buy, -1 for Sell
        s_int = 1 if str(order_side).strip().upper() == 'BUY' else -1
        self._recent_trades.append((ts_ns, float(last_qty), s_int))

        # 清理 5 秒之前的旧数据 (简单起见，每次插入时清理一次头部即可，或者在计算时清理)
        # 为了性能，这里不做 heavy cleanup，计算时再 filter
        pass

    def snapshot(self) -> FeatureSnapshot:
        """生成特征快照"""
        # 计算技术指标
        rsi = self._calc_rsi(14)
        ma_60 = self._calc_ma(60)
        dev_ma = (self._mid - ma_60) / self._mid if ma_60 > 0 else 0.0
        
        ret_std = self._calc_std(10)
        hl_range = self._calc_hl_range(10) # 这里的 10 可能是 tick 数
        
        return FeatureSnapshot(
            mid_price=self._mid,
            spread=self._spread,
            obi_l1=self._obis['obi_l1'],
            obi_l5=self._obis['obi_l5'],
            obi_decay=self._obis['obi_decay'],
            obi_l10=self._obis['obi_l10'], # 近似
            obi_l20=self._obis['obi_l20'], # 近似
            obi_l50=self._obis['obi_l50'], # 近似
            ret_std_10=ret_std,
            hl_range_10=hl_range,
            dev_ma_60=dev_ma,
            rsi_14=rsi,
            volatility=ret_std,
            vol_down=self._calc_downside_vol(10),
            vol_up=self._calc_upside_vol(10),
            toxicity=self._calc_toxicity(1_000_000_000), # 1秒窗口
        )

    def _compute_depth_features(self, depth: Dict[str, np.ndarray]):
        bids = depth['bids']  # shape (N, 2)
        asks = depth['asks']
        
        def calc_obi(level):
            # 取前 level 档的总量
            b_vol = bids[:level, 1].sum() if len(bids) > 0 else 0
            a_vol = asks[:level, 1].sum() if len(asks) > 0 else 0
            denom = b_vol + a_vol
            return (b_vol - a_vol) / denom if denom > 0 else 0.0

        self._obis['obi_l1'] = calc_obi(1)
        self._obis['obi_l5'] = calc_obi(5)
        
        # 只有5档数据时，L10/20/50 只能复用 L5
        self._obis['obi_l10'] = self._obis['obi_l5']
        self._obis['obi_l20'] = self._obis['obi_l5']
        self._obis['obi_l50'] = self._obis['obi_l5']
        
        # Decay: 加权 OBI
        # 权重: 1, 1/2, 1/3, 1/4, 1/5
        w_b = 0.0
        w_a = 0.0
        for i in range(min(5, len(bids))):
            w = 1.0 / (i + 1)
            w_b += bids[i, 1] * w
            w_a += asks[i, 1] * w
        
        denom = w_b + w_a
        self._obis['obi_decay'] = (w_b - w_a) / denom if denom > 0 else 0.0

    @staticmethod
    def _compute_obi_simple(b, a):
        denom = b + a
        return (b - a) / denom if denom > 0 else 0

    def _calc_rsi(self, period: int) -> float:
        if len(self._mid_prices) < period + 1:
            return 50.0 # 默认中性
            
        # 简化版 RSI 结算 (基于最近 N 个 tick)
        gains = 0.0
        losses = 0.0
        prices = list(self._mid_prices)[-period-1:]
        
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i-1]
            if diff > 0:
                gains += diff
            else:
                losses -= diff
                
        if losses == 0:
            return 100.0
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def _calc_ma(self, period: int) -> float:
        if len(self._mid_prices) < 1:
            return 0.0
        n = min(len(self._mid_prices), period)
        return sum(list(self._mid_prices)[-n:]) / n

    def _calc_std(self, period: int) -> float:
        if len(self._returns) < 2:
            return 0.0
        n = min(len(self._returns), period)
        rets = list(self._returns)[-n:]
        return np.std(rets)

    def _calc_hl_range(self, period: int) -> float:
        if len(self._mid_prices) < 1:
            return 0.0
        n = min(len(self._mid_prices), period)
        prices = list(self._mid_prices)[-n:]
        high = max(prices)
        low = min(prices)
        curr = prices[-1]
        return (high - low) / curr if curr > 0 else 0.0

    def _calc_downside_vol(self, period: int) -> float:
        """计算下行波动率 (只看负收益)"""
        if len(self._returns) < 2: return 0.0001
        n = min(len(self._returns), period)
        rets = list(self._returns)[-n:]
        neg_rets = [r for r in rets if r < 0]
        if len(neg_rets) < 2: return np.std(rets) # 回退到整体波动率
        return np.std(neg_rets)

    def _calc_upside_vol(self, period: int) -> float:
        """计算上行波动率 (只看正收益)"""
        if len(self._returns) < 2: return 0.0001
        n = min(len(self._returns), period)
        rets = list(self._returns)[-n:]
        pos_rets = [r for r in rets if r > 0]
        if len(pos_rets) < 2: return np.std(rets) # 回退到整体波动率
        return np.std(pos_rets)

    def _calc_toxicity(self, window_ns: int) -> float:
        """
        计算流毒性 (VPIN-lite)
        Toxicity = |BuyVol - SellVol| / TotalVol
        """
        if not self._recent_trades:
            return 0.0
            
        now_ns = self._recent_trades[-1][0]
        cutoff = now_ns - window_ns
        
        buy_vol = 0.0
        sell_vol = 0.0
        
        # 从后往前遍历
        for t_ns, qty, side in reversed(self._recent_trades):
            if t_ns < cutoff:
                break
            if side == 1:
                buy_vol += qty
            else:
                sell_vol += qty
                
        total_vol = buy_vol + sell_vol
        if total_vol <= 0:
            return 0.0
            
        return abs(buy_vol - sell_vol) / total_vol
