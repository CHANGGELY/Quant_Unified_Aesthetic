# -*- coding: utf-8 -*-
"""
VWAP_n 策略 - 贝叶斯优化版本 (Optuna)
使用智能采样，快速在大参数区间内找到最优参数
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
import sys
import optuna

# 关闭 Optuna 的日志输出（除了重要信息）
optuna.logging.set_verbosity(optuna.logging.WARNING)
warnings.filterwarnings('ignore')

# 数据路径
DATA_PATH = Path('/Users/chuan/Desktop/xiangmu/客户端/Quant_Unified/策略仓库/二号网格策略/data_center/ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5')

# 全局变量：缓存数据
DF_CACHE = None

def load_data(file_path):
    """加载 H5 数据"""
    global DF_CACHE
    if DF_CACHE is not None:
        return DF_CACHE
        
    print(f"正在加载数据: {file_path}...")
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
    
    # 合成 quote_volume
    if 'quote_volume' not in df.columns:
        df['quote_volume'] = df['close'] * df['volume']
    
    # 过滤日期 (从2021年开始)
    start_date = '2021-01-01'
    df = df[df.index >= pd.to_datetime(start_date)]
    
    print(f"数据加载完成。形状: {df.shape}")
    DF_CACHE = df
    return df

def calculate_vwap(df, n):
    """计算 VWAP"""
    vwap = (df['quote_volume'].rolling(n, min_periods=1).sum() / 
            df['volume'].rolling(n, min_periods=1).sum())
    return vwap

def backtest_strategy(df, n, fee_rate=0):
    """回测单个参数"""
    vwap = calculate_vwap(df, n)
    
    signal = pd.Series(0, index=df.index)
    signal[df['close'] > vwap] = 1
    signal[df['close'] < vwap] = -1
    
    pos = signal.shift(1).fillna(0)
    mkt_ret = df['close'].pct_change().fillna(0)
    
    turnover = (pos - pos.shift(1).fillna(0)).abs()
    fees = turnover * fee_rate
    
    strat_ret = pos * mkt_ret - fees
    equity = (1 + strat_ret).cumprod()
    
    return equity

def calculate_calmar(equity):
    """计算 Calmar 比率"""
    if len(equity) == 0 or equity.iloc[-1] <= 0:
        return -10.0  # 返回一个很差的分数
    
    days = (equity.index[-1] - equity.index[0]).days
    years = max(days / 365.25, 0.001)
    
    ann_ret = (equity.iloc[-1]) ** (1/years) - 1
    
    roll_max = equity.cummax()
    drawdown = (equity - roll_max) / roll_max
    max_dd = drawdown.min()
    
    if max_dd == 0:
        return 0
    
    calmar = ann_ret / abs(max_dd)
    return calmar

def objective(trial):
    """
    Optuna 目标函数
    每次调用会智能选择一个 N 进行评估
    """
    # 参数范围: 2 到 30000 (约 21 天)
    n = trial.suggest_int('n', 2, 30000)
    
    df = load_data(DATA_PATH)
    equity = backtest_strategy(df, n)
    calmar = calculate_calmar(equity)
    
    # Optuna 默认是最小化，我们要最大化 Calmar，所以返回负值
    return -calmar

def main():
    print("🔥 VWAP_n 智能优化启动 (贝叶斯优化)")
    print("=" * 50)
    
    # 预加载数据
    load_data(DATA_PATH)
    
    # 创建 Optuna Study
    # TPE 采样器是贝叶斯优化的一种实现
    study = optuna.create_study(
        direction='minimize',  # 因为我们返回的是负的 Calmar
        sampler=optuna.samplers.TPESampler(seed=42)
    )
    
    # 运行优化
    # n_trials: 总共评估多少个参数（100-200次通常足够）
    print(f"开始智能搜索... (预计评估 200 个参数)")
    study.optimize(objective, n_trials=200, show_progress_bar=True)
    
    # 输出结果
    print("\n" + "=" * 50)
    print("🏆 优化完成!")
    print("=" * 50)
    
    best_n = study.best_params['n']
    best_calmar = -study.best_value  # 取反得到真正的 Calmar
    
    print(f"最优参数 N = {best_n}")
    print(f"最优 Calmar 比率 = {best_calmar:.4f}")
    
    # 用最优参数重新跑一遍，获取详细指标
    df = load_data(DATA_PATH)
    equity = backtest_strategy(df, best_n)
    
    days = (equity.index[-1] - equity.index[0]).days
    years = max(days / 365.25, 0.001)
    ann_ret = (equity.iloc[-1]) ** (1/years) - 1
    roll_max = equity.cummax()
    drawdown = (equity - roll_max) / roll_max
    max_dd = drawdown.min()
    
    print(f"年化收益 = {ann_ret * 100:.2f}%")
    print(f"最大回撤 = {max_dd * 100:.2f}%")
    print(f"最终净值 = {equity.iloc[-1]:.4f}")
    
    # 保存 Top 10 结果
    trials_df = study.trials_dataframe()
    trials_df['calmar'] = -trials_df['value']
    trials_df = trials_df.sort_values('calmar', ascending=False)
    
    print("\n📊 Top 10 参数:")
    print(trials_df[['params_n', 'calmar']].head(10).to_string(index=False))
    
    # 保存结果
    output_file = Path('/Users/chuan/Desktop/xiangmu/客户端/Quant_Unified/策略仓库/一号择时策略/select-coin-feat-long_short_compose/vwap_bayesian_results.csv')
    trials_df.to_csv(output_file, index=False)
    print(f"\n✅ 结果保存至: {output_file}")

if __name__ == '__main__':
    main()
