# -*- coding: utf-8 -*-
"""
七号 VWAP 策略（v7.2 双均线）- 贝叶斯优化（Optuna）

这个文件是干嘛的？
    用“贝叶斯优化”自动帮你试参数（不用你手动一格一格遍历），找到表现更好的 N。

术语解释（用人话）：
    - VWAP（Volume Weighted Average Price：成交量加权平均价）
      类比：菜市场的“平均价”不是简单平均，而是“买得越多的价格越重要”。
    - Optuna：一个自动调参库，会根据历史试验结果更聪明地选下一个要试的参数。
    - Calmar（卡玛比率）：年化收益 / 最大回撤。类比：同样赚钱，谁“跌得没那么吓人”谁更稳。
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

# ====== 自动计算项目根目录（Quant_Unified）======
当前文件 = Path(__file__).resolve()
Quant_Unified根目录 = 当前文件.parents[3]
if str(Quant_Unified根目录) not in sys.path:
    sys.path.insert(0, str(Quant_Unified根目录))

# 数据路径：统一走“数据中心”，避免把路径写死在某台电脑上
from 基础库.common_core.data_center import 生成分钟K线文件名, 获取分钟K线H5文件

DATA_PATH = 获取分钟K线H5文件(
    生成分钟K线文件名("ETHUSDT", 开始日期="2019-11-01", 结束日期="2025-06-15", 带table后缀=True)
)

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
    print("VWAP_n 智能优化启动（贝叶斯优化）")
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
    from datetime import datetime

    时间戳 = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = Path(__file__).resolve().parent / f"贝叶斯优化结果_{时间戳}.csv"
    trials_df.to_csv(output_file, index=False)
    print(f"\n✅ 结果保存至: {output_file}")

if __name__ == '__main__':
    main()
