# -*- coding: utf-8 -*-
"""
七号VWAP策略 (V7.3) - 贝叶斯优化
优化目标: Calmar Ratio
优化参数:
    - n (均线周期): 100 ~ 10000
    - k (轨道宽度): 0.5 ~ 5.0
    - weighting (SMA/EMA)
    - mode (Trend/Reversion)
"""

import optuna
import pandas as pd
import numpy as np
from pathlib import Path
import warnings
import sys

# 引用同目录下的启动回测逻辑
sys.path.append(str(Path(__file__).parent))
try:
    from 启动回测 import load_data, run_backtest
except ImportError:
    # Fallback if run directly and path issue
    import importlib.util
    spec = importlib.util.spec_from_file_location("启动回测", Path(__file__).parent / "启动回测.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    load_data = module.load_data
    run_backtest = module.run_backtest

warnings.filterwarnings('ignore')

# ======================= [全局配置] =======================
DATA_PATH = Path('/Users/chuan/Desktop/xiangmu/客户端/Quant_Unified/策略仓库/二号网格策略/data_center/ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5')
START_DATE = '2021-01-01'
END_DATE   = '2025-06-15'

FEE_RATE   = 0.0000      # 0费率 (Maker)
SLIPPAGE   = 0.0001
LEVERAGE   = 1.0

N_TRIALS   = 100          # 试验次数
# =========================================================

# 缓存数据，避免重复加载
CACHED_DATA = None

def get_data():
    global CACHED_DATA
    if CACHED_DATA is None:
        CACHED_DATA = load_data(DATA_PATH, START_DATE, END_DATE)
    return CACHED_DATA

def objective(trial):
    try:
        df = get_data()
        
        # 参数搜索空间
        n = trial.suggest_int('n', 100, 10000)
        k = trial.suggest_float('k', 0.5, 5.0, step=0.1)
        weighting = trial.suggest_categorical('weighting', ['SMA', 'EMA'])
        mode = trial.suggest_categorical('mode', ['Trend', 'Reversion'])
        
        # 运行回测
        equity, pos = run_backtest(df, n, k, weighting, mode, FEE_RATE, SLIPPAGE, LEVERAGE)
        
        if len(equity) == 0: return 0.0
        
        final_equity = equity.iloc[-1]
        days = (equity.index[-1] - equity.index[0]).days
        years = max(days / 365.25, 0.001)
        ann_ret = (final_equity ** (1/years)) - 1
        
        roll_max = equity.cummax()
        max_dd = ((equity - roll_max) / roll_max).min()
        
        if max_dd == 0: return 0.0
        
        calmar = ann_ret / abs(max_dd)
        
        # 惩罚项: 如果交易次数太少，视为无效
        trade_count = (pos - pos.shift(1).fillna(0)).abs().sum()
        if trade_count < 20: 
            return 0.0
            
        # 惩罚项: 如果收益为负，Calmar无意义
        if ann_ret < 0:
            return ann_ret # 返回负收益本身作为惩罚
            
        return calmar
        
    except Exception as e:
        print(f"Trial failed: {e}")
        return 0.0

def main():
    print("🚀 启动 V7.3 贝叶斯优化...")
    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=N_TRIALS)
    
    print("\n" + "="*40)
    print("🏆 最佳参数组合:")
    print(study.best_params)
    print(f"💎 最佳 Calmar: {study.best_value:.4f}")
    print("="*40)
    
    # 打印前5名
    print("\nTop 5 Trials:")
    df_trials = study.trials_dataframe()
    df_trials = df_trials.sort_values('value', ascending=False).head(5)
    print(df_trials[['number','value','params_mode','params_weighting','params_n','params_k']])

if __name__ == '__main__':
    main()
