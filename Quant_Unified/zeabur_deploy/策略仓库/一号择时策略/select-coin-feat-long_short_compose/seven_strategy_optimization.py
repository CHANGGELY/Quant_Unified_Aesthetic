# -*- coding: utf-8 -*-
"""
VWAP_n 策略参数遍历优化脚本 (Standalone Optimization)
Target: ETHUSDT Minute Data
Strategy: Close > VWAP -> Long, Close < VWAP -> Short
Optimization: Rank by Calmar Ratio (Ann Free Returns / Max Drawdown)
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
import sys
import os

# Filter warnings
warnings.filterwarnings('ignore')

# Data Path
DATA_PATH = Path('/Users/chuan/Desktop/xiangmu/客户端/Quant_Unified/策略仓库/二号网格策略/data_center/ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5')

def load_data(file_path):
    """
    读取 HDF5 数据 (使用 h5py)
    """
    print(f"Loading data from {file_path} using h5py...")
    try:
        import h5py
        import hdf5plugin  # Register plugins for Blosc/etc
        with h5py.File(file_path, 'r') as f:
            # Assming data is in 'klines/table' based on inspection
            if 'klines' in f and 'table' in f['klines']:
               dset = f['klines/table']
               data = dset[:]
            else:
               # Fallback or search
               print("Keys found:", list(f.keys()))
               raise ValueError("Could not find 'klines/table' in H5 file.")
        
        df = pd.DataFrame(data)
        
        # Convert bytes column names if necessary (h5py returns numpy compound array, pandas handles it)
        # But we verify column names
        # Based on inspection: ['index', 'open', 'high', 'low', 'close', 'volume', 'candle_begin_time_GMT8']
        # Rename candle_begin_time_GMT8 to candle_begin_time or keep as index
        
        if 'candle_begin_time_GMT8' in df.columns:
            df['candle_begin_time'] = pd.to_datetime(df['candle_begin_time_GMT8'])
            df.set_index('candle_begin_time', inplace=True)
            df.drop(columns=['candle_begin_time_GMT8'], inplace=True)
            
        # Synthesize quote_volume if missing
        if 'quote_volume' not in df.columns:
            # Using close * volume as approximation
            df['quote_volume'] = df['close'] * df['volume']
            
        print(f"Data loaded. Shape: {df.shape}")
        return df
    except Exception as e:
        print(f"Error loading data: {e}")
        # traceback
        import traceback
        traceback.print_exc()
        sys.exit(1)

def calculate_vwap(df, n):
    """
    计算 VWAP
    """
    # quote_volume is usually Close * Volume (or similar)
    # vwap = sum(quote_volume, n) / sum(volume, n)
    vwap = (df['quote_volume'].rolling(n, min_periods=1).sum() / 
            df['volume'].rolling(n, min_periods=1).sum())
    return vwap

def backtest_strategy(df, n, fee_rate=0):
    """
    回测单个 N 参数
    fee_rate: 0 (Maker Mode)
    """
    # Calculate VWAP
    vwap = calculate_vwap(df, n)
    
    # Generate Signal
    # 1: Long, -1: Short
    # Signal is calculated based on CURRENT Close vs VWAP.
    # We must SHIFT signal by 1 to get POSITION for next minute.
    # Position: shift(1) of signal.
    # If Close > VWAP, Signal = 1. Next candle we hold Long.
    
    signal = pd.Series(0, index=df.index)
    signal[df['close'] > vwap] = 1
    signal[df['close'] < vwap] = -1
    
    # Position (1 for Long, -1 for Short)
    # Shift 1 because we trade at Open of next candle based on Signal from Close of this candle
    # Or more simply, we calculate return based on signal * next_pct_change
    pos = signal.shift(1).fillna(0)
    
    # Calculate Returns
    # Simple return: (Close - PrevClose) / PrevClose
    # Strategy Return: pos * Simple Return
    # Note: Implementation simplification. For rigorous backtest, consider funding rates, etc.
    # But for parameter ranking, this close-to-close approx is usually sufficient.
    
    # pct_change is (Close_t - Close_t-1) / Close_t-1
    # Strategy PnL at t = Pos_t * pct_change_t
    # Pos_t is determined by Signal_t-1
    
    mkt_ret = df['close'].pct_change().fillna(0)
    
    # Fee calculation (Simplified)
    # Fee is paid when position CHANGES.
    # change_mask = pos != pos.shift(1)
    # logic: if pos changes from 1 to -1, we sell 1 and sell 1 -> 2 units turnover?
    # Simplified: |pos - pos.shift(1)| * fee_rate
    # pos is 1, 0, -1.
    # 0 -> 1: buy 1 unit. turnover 1.
    # 1 -> -1: sell 2 units. turnover 2.
    turnover = (pos - pos.shift(1).fillna(0)).abs()
    fees = turnover * fee_rate
    
    # Trade Count
    # turnover sum / 2 roughly (open + close = 2 turnover)
    # or just count changes
    trade_count = (pos != pos.shift(1).fillna(0)).sum()
    
    strat_ret = pos * mkt_ret - fees
    
    # Equity Curve
    equity = (1 + strat_ret).cumprod()
    
    return equity, strat_ret, trade_count

def calculate_metrics(equity, strat_ret):
    """
    计算策略评价指标
    """
    # Annualized Return
    # Assuming 1m data.
    # Total Time in years
    if len(equity) == 0:
        return 0, 0, 0
        
    days = (equity.index[-1] - equity.index[0]).days
    if days == 0:
        years = 0.001 # avoid div by zero
    else:
        years = days / 365.25
        
    total_ret = equity.iloc[-1] - 1
    # Check if equity <= 0 to avoid complex number in pow
    if equity.iloc[-1] <= 0:
        ann_ret = -1.0 # Bust
    else:
        ann_ret = (equity.iloc[-1]) ** (1/years) - 1
    
    # Max Drawdown
    roll_max = equity.cummax()
    drawdown = (equity - roll_max) / roll_max
    max_dd = drawdown.min() # negative value
    
    # Calmar Ratio
    # If max_dd is 0 (impossible usually), handle it.
    if max_dd == 0:
        calmar = 0
    else:
        calmar = ann_ret / abs(max_dd)
        
    return ann_ret, max_dd, calmar

def main():
    print(f"🔥 Starting VWAP_n Optimization...")
    
    # 1. Load Data
    df = load_data(DATA_PATH)
    
    # Filter Data from 2021-01-01
    start_date = '2021-01-01'
    df = df[df.index >= pd.to_datetime(start_date)]
    print(f"Data filtered from {start_date}. New shape: {df.shape}")
    
    # 2. Define Parameter Range
    # n from 2 to 4320, step 1 (Every integer)
    n_params = list(range(2, 4321, 1))
    print(f"Scanning {len(n_params)} parameters: {n_params[0]} ... {n_params[-1]}")
    
    results = []
    
    # 3. Optimization Loop
    for n in n_params:
        equity, strat_ret, trade_count = backtest_strategy(df, n)
        ann_ret, max_dd, calmar = calculate_metrics(equity, strat_ret)
        
        results.append({
            'n': n,
            'ann_return': ann_ret,
            'max_drawdown': max_dd,
            'calmar_ratio': calmar,
            'trade_count': trade_count,
            'final_equity': equity.iloc[-1]
        })
        
        if n % 100 == 0:
            print(f"Processing n={n}... Calmar: {calmar:.4f}, Trades: {trade_count}")
            
    # 4. Rank and Report
    res_df = pd.DataFrame(results)
    
    # Rank by Calmar Ratio (Descending)
    res_df.sort_values(by='calmar_ratio', ascending=False, inplace=True)
    
    print("\n" + "="*50)
    print("🏆 Optimization Results (Top 20)")
    print("="*50)
    print(res_df.head(20).to_string(index=False))
    
    # Save to CSV
    output_file = Path('/Users/chuan/Desktop/xiangmu/客户端/Quant_Unified/策略仓库/一号择时策略/select-coin-feat-long_short_compose/vwap_optimization_results.csv')
    res_df.to_csv(output_file, index=False)
    print(f"\n✅ Results saved to {output_file}")

if __name__ == '__main__':
    main()
