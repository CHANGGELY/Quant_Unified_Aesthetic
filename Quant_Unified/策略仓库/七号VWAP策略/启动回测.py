# -*- coding: utf-8 -*-
"""
七号VWAP策略 - 启动入口 (V2 专业版)
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings

# 忽略警告
warnings.filterwarnings('ignore')

# ======================= [核心配置区域] =======================
# 1. 策略核心参数
BEST_N = 1196             # VWAP 的周期参数 (1196 为之前优化的最优值)

# 2. 时间范围配置 (支持精准到分钟)
START_DATE = '2021-01-01' # 回测开始日期
END_DATE   = '2025-06-15' # 回测结束日期 (设为 None 则运行到数据末尾)

# 3. 交易成本与资金配置
FEE_RATE   = 0.0000       # 手续费率 (0.0000 代表模拟理想 Maker 情况)
SLIPPAGE   = 0.0001       # 预期滑点 (例如 0.01% 的价格偏移/磨损成本)
INITIAL_CASH = 10000      # 初始本金 (USDT)
LEVERAGE   = 1.0          # 杠杆倍数 (1.0 代表不带杠杆)

# 4. 数据路径
DATA_PATH = Path('/Users/chuan/Desktop/xiangmu/客户端/Quant_Unified/策略仓库/二号网格策略/data_center/ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5')
# =========================================================

def load_data(file_path, start, end):
    """
    加载并过滤 HDF5 数据
    """
    print(f"📂 正在从数据中心加载 ETH 历史分钟数据...")
    import h5py
    import hdf5plugin
    
    with h5py.File(file_path, 'r') as f:
        dset = f['klines/table']
        data = dset[:]
    
    df = pd.DataFrame(data)
    
    # 时间维度处理
    if 'candle_begin_time_GMT8' in df.columns:
        df['candle_begin_time'] = pd.to_datetime(df['candle_begin_time_GMT8'])
        df.set_index('candle_begin_time', inplace=True)
        df.drop(columns=['candle_begin_time_GMT8'], inplace=True)
    
    # 合成 quote_volume (成交额)
    if 'quote_volume' not in df.columns:
        df['quote_volume'] = df['close'] * df['volume']
    
    # 时空裁切
    if start:
        df = df[df.index >= pd.to_datetime(start)]
    if end:
        df = df[df.index <= pd.to_datetime(end)]
        
    print(f"✅ 加载成功! 记录条数: {len(df)} | 时间: {df.index[0]} -> {df.index[-1]}")
    return df

def run_backtest(df, n, fee, slippage, leverage):
    """
    执行向量化回测引擎
    """
    # 1. 计算 VWAP 基准线
    # VWAP = 累计成交额 / 累计成交量
    vwap = (df['quote_volume'].rolling(n, min_periods=1).sum() / 
            df['volume'].rolling(n, min_periods=1).sum())
    
    # 2. 生成多空信号
    signal = pd.Series(0, index=df.index)
    signal[df['close'] > vwap] = 1   # 多头区间
    signal[df['close'] < vwap] = -1  # 空头区间
    
    # 3. 关键：将信号向下平移一个K线 (由于回测中必须在K线结束才知道Close，才能决策下一根的动作)
    pos = signal.shift(1).fillna(0)
    
    # 4. 统计交易频率 (仓位绝对值的变化量)
    change_pos = (pos - pos.shift(1).fillna(0)).abs()
    
    # 5. 计算净收益率曲线
    # 市场本身的每分钟波动率
    mkt_ret = df['close'].pct_change().fillna(0)
    # 策略收益 = (仓位 * 市场波动 * 杠杆) - (换手磨损: 手续费+滑点)
    strat_ret = (pos * mkt_ret * leverage) - (change_pos * (fee + slippage))
    
    # 累计收益 (复利模式)
    equity = (1 + strat_ret).cumprod()
    return equity

def report(equity):
    """
    根据收益曲线计算并打印专业金融指标
    """
    final_equity = equity.iloc[-1]
    total_ret = (final_equity - 1) * 100
    final_cash = INITIAL_CASH * final_equity
    
    # 1. 年化收益率 (基于 365.25 天)
    days = (equity.index[-1] - equity.index[0]).days
    if days == 0: days = 1
    ann_ret = (final_equity ** (365.25 / max(days, 1))) - 1
    
    # 2. 回撤分析
    roll_max = equity.cummax()
    drawdown = (equity - roll_max) / roll_max
    max_dd = drawdown.min()
    
    # 3. 夏普比率 (简易年化版，不考虑无风险利率)
    daily_rets = equity.resample('1D').last().pct_change().dropna()
    if daily_rets.std() != 0:
        sharpe = (daily_rets.mean() / daily_rets.std()) * (365.25 ** 0.5)
    else:
        sharpe = 0
    
    # 4. 卡玛比率 (Calmar Ratio)
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

    print("\n" + "🔥" * 20)
    print("      VWAP 策略实战回测报告 (V2)")
    print("🔥" * 20)
    print(f"💰 初始本金: {INITIAL_CASH:,.0f} USDT")
    print(f"💎 最终资产: {final_cash:,.2f} USDT")
    print(f"📈 总收益率: {total_ret:.2f}%")
    print("-" * 35)
    print(f"� 年化收益: {ann_ret * 100:.2f}%")
    print(f"🌊 最大回撤: {max_dd * 100:.2f}%")
    print(f"📊 风险收益比 (Sharpe): {sharpe:.2f}")
    print(f"⚖️  卡玛比率 (Calmar): {calmar:.2f}")
    print("-" * 35)
    print(f"📅 运行时间: {equity.index[0]} 至 {equity.index[-1]}")
    print(f"🎛️  杠杆设置: {LEVERAGE}x | 手续费: {FEE_RATE*100:.3f}% | 滑点: {SLIPPAGE*100:.3f}%")
    print("🔥" * 20)

def main():
    try:
        data = load_data(DATA_PATH, START_DATE, END_DATE)
        equity_curve = run_backtest(data, BEST_N, FEE_RATE, SLIPPAGE, LEVERAGE)
        report(equity_curve)
    except Exception as e:
        print(f"❌ 运行失败: {e}")

if __name__ == '__main__':
    main()
