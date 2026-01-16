# -*- coding: utf-8 -*-
"""
七号VWAP策略 (V7.2) - 双均线交叉策略
逻辑: 快线 > 慢线 做多, 快线 < 慢线 做空
参数: 基于 V7.2 贝叶斯优化结果 (SMA 模式胜出)
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings

warnings.filterwarnings('ignore')

# ======================= [核心配置区域] =======================
FAST_N = 136              # 快线周期
SLOW_N = 972              # 慢线周期
WEIGHTING_TYPE = 'SMA'    # 加权方式: 'SMA' (推荐) 或 'EMA'

START_DATE = '2021-01-01'
END_DATE   = '2025-06-15'

FEE_RATE   = 0.0000
SLIPPAGE   = 0.0001
INITIAL_CASH = 10000
LEVERAGE   = 1.0

DATA_PATH = Path('/Users/chuan/Desktop/xiangmu/客户端/Quant_Unified/策略仓库/二号网格策略/data_center/ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5')
# =========================================================

def load_data(file_path, start, end):
    print(f"📂 [V7.2 双均线] 正在加载 ETH 历史数据...")
    import h5py
    import hdf5plugin
    
    with h5py.File(file_path, 'r') as f:
        dset = f['klines/table']
        data = dset[:]
    
    df = pd.DataFrame(data)
    
    if 'candle_begin_time_GMT8' in df.columns:
        df['candle_begin_time'] = pd.to_datetime(df['candle_begin_time_GMT8'])
        df.set_index('candle_begin_time', inplace=True)
        df.drop(columns=['candle_begin_time_GMT8'], inplace=True)
    
    if 'quote_volume' not in df.columns:
        df['quote_volume'] = df['close'] * df['volume']
    
    if start: df = df[df.index >= pd.to_datetime(start)]
    if end: df = df[df.index <= pd.to_datetime(end)]
        
    print(f"✅ 加载成功! 记录条数: {len(df)}")
    return df

def calculate_vwap(df, n, weighting):
    if weighting == 'EMA':
        return (df['quote_volume'].ewm(span=n, min_periods=1).mean() / 
                df['volume'].ewm(span=n, min_periods=1).mean())
    else:
        return (df['quote_volume'].rolling(n, min_periods=1).sum() / 
                df['volume'].rolling(n, min_periods=1).sum())

def run_backtest(df, n_fast, n_slow, fee, slippage, leverage, weighting):
    print(f"⚙️  正在回测: {weighting} Fast={n_fast} Slow={n_slow}")
    
    vwap_fast = calculate_vwap(df, n_fast, weighting)
    vwap_slow = calculate_vwap(df, n_slow, weighting)
    
    signal = pd.Series(0, index=df.index)
    signal[vwap_fast > vwap_slow] = 1
    signal[vwap_fast < vwap_slow] = -1
    
    pos = signal.shift(1).fillna(0)
    change_pos = (pos - pos.shift(1).fillna(0)).abs()
    
    mkt_ret = df['close'].pct_change().fillna(0)
    strat_ret = (pos * mkt_ret * leverage) - (change_pos * (fee + slippage))
    
    equity = (1 + strat_ret).cumprod()
    return equity

def report(equity):
    if len(equity) == 0: return
    final_equity = equity.iloc[-1]
    total_ret = (final_equity - 1) * 100
    final_cash = INITIAL_CASH * final_equity
    
    days = (equity.index[-1] - equity.index[0]).days
    years = max(days / 365.25, 0.001)
    ann_ret = (final_equity ** (1/years)) - 1
    
    roll_max = equity.cummax()
    max_dd = ((equity - roll_max) / roll_max).min()
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

    print("\n" + "🔥" * 20)
    print("      VWAP V7.2 (双均线) 回测报告")
    print("🔥" * 20)
    print(f"💰 初始本金: {INITIAL_CASH:,.0f} USDT")
    print(f"💎 最终资产: {final_cash:,.2f} USDT")
    print(f"📈 总收益率: {total_ret:.2f}%")
    print("-" * 35)
    print(f"📅 年化收益: {ann_ret * 100:.2f}%")
    print(f"🌊 最大回撤: {max_dd * 100:.2f}%")
    print(f"⚖️  卡玛比率: {calmar:.2f}")
    print("-" * 35)
    print(f"🛠️  参数: {WEIGHTING_TYPE} Fast={FAST_N} Slow={SLOW_N}")
    print("🔥" * 20)

def main():
    try:
        data = load_data(DATA_PATH, START_DATE, END_DATE)
        equity_curve = run_backtest(data, FAST_N, SLOW_N, FEE_RATE, SLIPPAGE, LEVERAGE, WEIGHTING_TYPE)
        report(equity_curve)
    except Exception as e:
        print(f"❌ 运行失败: {e}")

if __name__ == '__main__':
    main()
