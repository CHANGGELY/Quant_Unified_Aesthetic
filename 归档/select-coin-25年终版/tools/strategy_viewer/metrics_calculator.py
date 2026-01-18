"""
邢不行™️选币框架 - 交易指标计算器
Python数字货币量化投资课程

版权所有 ©️ 邢不行
微信: xbx8662

计算每个交易期间的各项指标
"""

import pandas as pd
import numpy as np
import numba as nb
from typing import Dict, Optional
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed


@nb.njit(cache=True)
def _max_drawdown_long_jit(highs, lows, closes, entry_price, exit_price):
    running_max = entry_price
    max_drawdown = 0.0
    for i in range(len(highs)):
        high = highs[i]
        low = lows[i]
        close = closes[i]
        drawdown_low = (low - running_max) / running_max
        if drawdown_low < max_drawdown:
            max_drawdown = drawdown_low
        if high > 0.0:
            drawdown_internal = (close - high) / high
            if drawdown_internal < max_drawdown:
                max_drawdown = drawdown_internal
        if high > running_max:
            running_max = high
    drawdown_exit = (exit_price - running_max) / running_max
    if drawdown_exit < max_drawdown:
        max_drawdown = drawdown_exit
    if max_drawdown < 0.0:
        return max_drawdown
    return 0.0


@nb.njit(cache=True)
def _max_drawdown_short_jit(highs, lows, closes, entry_price, exit_price):
    running_min = entry_price
    max_drawdown = 0.0
    for i in range(len(highs)):
        high = highs[i]
        low = lows[i]
        close = closes[i]
        drawdown_high = (running_min - high) / running_min
        if drawdown_high < max_drawdown:
            max_drawdown = drawdown_high
        if low > 0.0:
            drawdown_internal = (low - close) / low
            if drawdown_internal < max_drawdown:
                max_drawdown = drawdown_internal
        if low < running_min:
            running_min = low
    drawdown_exit = (running_min - exit_price) / running_min
    if drawdown_exit < max_drawdown:
        max_drawdown = drawdown_exit
    if max_drawdown < 0.0:
        return max_drawdown
    return 0.0


class MetricsCalculator:
    """交易指标计算器"""
    
    def calculate(self, periods_df: pd.DataFrame, kline_data_dict: dict, workers: Optional[int] = None) -> pd.DataFrame:
        """
        为每个交易期间计算指标
        
        Args:
            periods_df: 交易期间DataFrame
            kline_data_dict: K线数据字典 {symbol: DataFrame}
            
        Returns:
            包含计算结果的periods_df
        """
        if periods_df.empty:
            return periods_df
        
        result = periods_df.copy()
        
        print(f"📊 计算 {len(result)} 个交易期间的指标...")
        
        success_count = 0

        if workers is None or workers <= 1:
            for idx, row in tqdm(result.iterrows(), total=len(result), desc="计算交易指标", ncols=80):
                symbol = row['symbol']
                entry_time = row['entry_time']
                exit_time = row['exit_time']
                direction = row['direction']
                if symbol not in kline_data_dict:
                    continue
                kline_df = kline_data_dict[symbol]
                metrics = self._calculate_period_metrics(
                    kline_df, entry_time, exit_time, direction
                )
                if metrics is not None:
                    result.at[idx, 'return'] = metrics['return']
                    result.at[idx, 'max_drawdown'] = metrics['max_drawdown']
                    result.at[idx, 'volatility'] = metrics['volatility']
                    result.at[idx, 'return_drawdown_ratio'] = metrics['return_drawdown_ratio']
                    success_count += 1
        else:
            def task(item):
                idx, row = item
                symbol = row['symbol']
                entry_time = row['entry_time']
                exit_time = row['exit_time']
                direction = row['direction']
                if symbol not in kline_data_dict:
                    return idx, None
                kline_df = kline_data_dict[symbol]
                metrics = self._calculate_period_metrics(
                    kline_df, entry_time, exit_time, direction
                )
                return idx, metrics

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(task, (idx, row))
                    for idx, row in result.iterrows()
                ]
                for future in tqdm(as_completed(futures), total=len(futures), desc="计算交易指标(并行)", ncols=80):
                    idx, metrics = future.result()
                    if metrics is not None:
                        result.at[idx, 'return'] = metrics['return']
                        result.at[idx, 'max_drawdown'] = metrics['max_drawdown']
                        result.at[idx, 'volatility'] = metrics['volatility']
                        result.at[idx, 'return_drawdown_ratio'] = metrics['return_drawdown_ratio']
                        success_count += 1
        
        print(f"✅ 成功计算 {success_count}/{len(result)} 个交易期间的指标")
        
        return result
    
    def _calculate_period_metrics(self, kline_df: pd.DataFrame,
                                   entry_time: pd.Timestamp,
                                   exit_time: pd.Timestamp,
                                   direction: str) -> Dict:
        """
        计算单个交易期间的指标
        
        Args:
            kline_df: K线数据
            entry_time: 买入时间（实际买入时刻）
            exit_time: 卖出时间（实际卖出时刻）
            direction: 方向 ('long' 或 'short')
            
        Returns:
            指标字典，如果数据不足返回None
        """
        if kline_df.index.name == 'candle_begin_time':
            try:
                entry_kline = kline_df.loc[[entry_time]]
            except KeyError:
                entry_kline = kline_df.iloc[0:0]
            try:
                exit_kline = kline_df.loc[[exit_time]]
            except KeyError:
                exit_kline = kline_df.iloc[0:0]
        else:
            entry_kline = kline_df[kline_df['candle_begin_time'] == entry_time]
            exit_kline = kline_df[kline_df['candle_begin_time'] == exit_time]
        
        if entry_kline.empty or exit_kline.empty:
            return None
        
        # 买入价 = entry时刻的K线开盘价
        entry_price = entry_kline.iloc[0]['open']
        
        # 卖出价 = exit时刻的K线开盘价
        exit_price = exit_kline.iloc[0]['open']
        
        # 1. 计算收益率（考虑方向）
        if direction == 'long':
            return_rate = (exit_price - entry_price) / entry_price
        else:  # short
            return_rate = (entry_price - exit_price) / entry_price
        
        if kline_df.index.name == 'candle_begin_time':
            period_klines = kline_df[
                (kline_df.index >= entry_time) &
                (kline_df.index < exit_time)
            ]
        else:
            period_klines = kline_df[
                (kline_df['candle_begin_time'] >= entry_time) &
                (kline_df['candle_begin_time'] < exit_time)
            ]
        
        if period_klines.empty:
            return self._default_metrics()
        
        # 2. 计算最大回撤
        max_drawdown = self._calculate_max_drawdown(
            period_klines, entry_price, exit_price, direction
        )
        
        # 3. 计算波动率
        volatility = self._calculate_volatility(period_klines)
        
        # 4. 计算收益回撤比（保持收益的正负号）
        if max_drawdown < 0:
            return_drawdown_ratio = return_rate / abs(max_drawdown)
        else:
            return_drawdown_ratio = 0.0
        
        return {
            'return': return_rate,
            'max_drawdown': max_drawdown,
            'volatility': volatility,
            'return_drawdown_ratio': return_drawdown_ratio,
        }
    
    def _calculate_max_drawdown(self, period_klines: pd.DataFrame,
                                 entry_price: float, 
                                 exit_price: float,
                                 direction: str) -> float:
        """
        计算最大回撤（向量化优化版本）
        
        最大回撤定义：
        - 多头：从买入后的运行最高点到后续最低点的最大跌幅
        - 空头：从买入后的运行最低点到后续最高点的最大升幅
        
        计算策略：
        1. period_klines 不包含 exit_time 的K线
        2. 考虑每根K线的 high 和 low 价格
        3. 最终卖出价 exit_price 也参与回撤计算
        4. 使用向量化操作提高效率
        
        Args:
            period_klines: 期间内的K线数据（不含exit_time的K线）
            entry_price: 买入价格
            exit_price: 卖出价格
            direction: 方向
            
        Returns:
            最大回撤（负值或0）
        """
        if len(period_klines) == 0:
            if direction == 'long':
                return min(0.0, (exit_price - entry_price) / entry_price)
            else:
                return min(0.0, (entry_price - exit_price) / entry_price)

        highs = period_klines['high'].to_numpy(dtype=np.float64, copy=False)
        lows = period_klines['low'].to_numpy(dtype=np.float64, copy=False)
        closes = period_klines['close'].to_numpy(dtype=np.float64, copy=False)

        if direction == 'long':
            return float(
                _max_drawdown_long_jit(
                    highs,
                    lows,
                    closes,
                    float(entry_price),
                    float(exit_price),
                )
            )
        else:
            return float(
                _max_drawdown_short_jit(
                    highs,
                    lows,
                    closes,
                    float(entry_price),
                    float(exit_price),
                )
            )
    
    def _calculate_volatility(self, period_klines: pd.DataFrame) -> float:
        """
        计算波动率（收盘价收益率的标准差）
        
        Args:
            period_klines: 期间内的K线数据
            
        Returns:
            波动率
        """
        if len(period_klines) < 2:
            return 0.0
        
        returns = period_klines['close'].pct_change().dropna()
        
        # 去掉最后一根K线的收益率
        # 因为最后一根K线我们只用了开盘价（卖出），不关心收盘价
        if len(returns) > 1:
            returns = returns[:-1]
        
        if len(returns) > 0:
            return float(returns.std())
        else:
            return 0.0
    
    def _default_metrics(self) -> Dict:
        """默认指标值（数据不足时）"""
        return {
            'return': 0.0,
            'max_drawdown': 0.0,
            'volatility': 0.0,
            'return_drawdown_ratio': 0.0,
        }
