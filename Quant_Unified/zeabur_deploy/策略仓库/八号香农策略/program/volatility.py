# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
from collections import deque
import logging

logger = logging.getLogger(__name__)

class VolatilityEngine:
    """
    波动率状态机引擎
    不再单一使用 ATR，而是基于长短周期波动率比率进行状态切换。
    """
    def __init__(self, config):
        self.config = config
        self.prices = deque(maxlen=2000) # 存储足够多的历史价格 (需要满足 long_window)
        self.times = deque(maxlen=2000)
        
        # 缓存计算结果
        self.vol_short = 0.0
        self.vol_long = 0.0
        self.ratio = 0.0
        self.ewma_vol = 0.0
        self.ewma_price = 0.0
        self.regime = 'NORMAL' # NORMAL, SPIKE, CRUSH
        
        # 状态参数
        self.short_win = getattr(config, 'vol_short_window', 60)
        self.long_win = getattr(config, 'vol_long_window', 1440)
        self.ewma_alpha = getattr(config, 'vol_ewma_alpha', 0.05)
        
        # 📢 状态切换打印开关 (默认关闭，避免刷屏)
        # 只有当 config.verbose_regime_switch = True 时才打印状态变化
        self.verbose = getattr(config, 'verbose_regime_switch', False)
        
        if self.verbose:
            logger.info(f"[VolEngine] 初始化完成 | Short: {self.short_win}m | Long: {self.long_win}m")

    def add_price(self, price, timestamp=None):
        """添加最新的分钟级价格"""
        if price <= 0:
            return
        
        self.prices.append(float(price))
        if timestamp:
            self.times.append(timestamp)
        
        # 实时更新计算
        self._calculate()

    def _calculate(self):
        """
        核心计算逻辑：
        1. 计算对数收益率
        2. 计算短期和长期标准差
        3. 更新 EWMA
        4. 判定 Regime
        """
        if len(self.prices) < 2:
            return

        # 转换为 Series 方便计算
        series_price = pd.Series(list(self.prices))
        
        # 计算对数收益率: ln(P_t / P_{t-1})
        # 注意: 这里的 std 是分钟级别的波动率
        log_returns = np.log(series_price / series_price.shift(1)).dropna()
        
        if len(log_returns) < self.short_win:
            # 数据不足时，暂时用所有数据的 std
            self.vol_short = log_returns.std()
            self.vol_long = self.vol_short
            self.ratio = 1.0
            self.ewma_vol = self.vol_short
            return

        # 1. 计算短期波动率 (Short Vol)
        self.vol_short = log_returns.tail(self.short_win).std()
        
        # 2. 计算长期波动率 (Long Vol)
        # 如果数据不够 long_win，就用所有可用数据
        curr_long_win = min(len(log_returns), self.long_win)
        self.vol_long = log_returns.tail(curr_long_win).std()
        
        # 3. 计算比率
        if self.vol_long > 1e-9:
            self.ratio = self.vol_short / self.vol_long
        else:
            self.ratio = 1.0
            
        # 4. 更新 EWMA Vol (平滑后的基准波动率)
        # EWMA_t = alpha * Vol_short + (1 - alpha) * EWMA_{t-1}
        if self.ewma_vol == 0.0:
            self.ewma_vol = self.vol_short
        else:
            self.ewma_vol = self.ewma_alpha * self.vol_short + (1 - self.ewma_alpha) * self.ewma_vol

        # 4.1 更新 EWMA Price (用于中心价平滑)
        # 使用相同的 Alpha 或独立 Alpha? 通常价格平滑需要更快一点? 
        # 这里复用 vol_ewma_alpha 或者 hardcode 一个 0.1
        current_price = series_price.iloc[-1]
        if self.ewma_price == 0.0:
            self.ewma_price = current_price
        else:
            self.ewma_price = self.ewma_alpha * current_price + (1 - self.ewma_alpha) * self.ewma_price

        # 5. 判定状态
        spike_thresh = getattr(self.config, 'regime_spike_threshold', 1.5)
        crush_thresh = getattr(self.config, 'regime_crush_threshold', 0.5)
        
        old_regime = self.regime
        if self.ratio > spike_thresh:
            self.regime = 'SPIKE'
        elif self.ratio < crush_thresh:
            self.regime = 'CRUSH'
        else:
            self.regime = 'NORMAL'
            
        if old_regime != self.regime:
            if self.verbose:  # 只有开启 verbose 时才打印状态切换
                logger.info(f"[VolEngine] 状态切换: {old_regime} -> {self.regime} (Ratio={self.ratio:.2f})")

    def get_market_status(self):
        """返回当前市场状态摘要"""
        # 基准网格宽度 (Base Width)
        # 假设 k=1，Base = EWMA_Vol
        base_width = self.ewma_vol * getattr(self.config, 'vol_k_factor', 1.0)
        
        # 根据状态调整宽度
        multiplier = 1.0
        if self.regime == 'SPIKE':
            multiplier = getattr(self.config, 'width_multiplier_spike', 1.5)
        elif self.regime == 'CRUSH':
            multiplier = getattr(self.config, 'width_multiplier_crush', 0.8)
            
        final_width = base_width * multiplier
        
        # 应用物理下限
        min_width = float(getattr(self.config, 'min_grid_width_bps', 5.0)) / 10000.0
        if final_width < min_width:
            final_width = min_width

        return {
            'regime': self.regime,
            'vol_short': self.vol_short,
            'vol_long': self.vol_long,
            'ratio': self.ratio,
            'final_width': final_width,  # 这里的 width 是百分比形式，如 0.005 (0.5%)
            'raw_base_width': base_width,
            'multiplier': multiplier,
            'ewma_price': self.ewma_price
        }
