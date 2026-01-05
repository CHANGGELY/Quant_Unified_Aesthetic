import sys
from pathlib import Path
import warnings
import pandas as pd
import numpy as np

# ====== 自动计算项目根目录 ======
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[3]  # Quant_Unified
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from 基础库.common_core.backtest.metrics import 回测指标计算器
from 基础库.common_core.backtest.可视化 import 回测可视化

warnings.filterwarnings('ignore')

# ======================= [核心配置区域] =======================
# 默认参数 (基于贝叶斯优化结果 Calmar=1.43)
N = 1391                  # 周期
K = 3.9                   # 轨道宽度 (倍数)
WEIGHTING_TYPE = 'EMA'    # 加权方式
LOGIC_MODE = 'Reversion'  # 模式: 'Reversion' (反转策略胜出)

START_DATE = '2021-01-01'
END_DATE   = '2025-06-15'

FEE_RATE   = 0.0000       # 模拟 Maker (0 费率)
SLIPPAGE   = 0.0001
INITIAL_CASH = 10000
LEVERAGE   = 1.0

# 自动处理数据路径
DATA_PATH = PROJECT_ROOT / "策略仓库/二号网格策略/data_center/ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5"
# =========================================================

def load_data(file_path, start, end):
    print(f"📂 [V7.3 布林带] 正在加载 ETH 历史数据...")
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

def calculate_vwap_bands(df, n, k, weighting):
    typical_price = (df['close'] + df['high'] + df['low']) / 3
    
    if weighting == 'EMA':
        # VWAP
        vwap = (df['quote_volume'].ewm(span=n, min_periods=n).mean() / 
                df['volume'].ewm(span=n, min_periods=n).mean())
        # StdDev (Weighted EWM StdDev is complex, approximating with Close Price StdDev for simplicity and speed)
        # 业界常用做法: 轨道宽度基于价格的标准差，而非 VWAP 本身的标准差
        std = df['close'].ewm(span=n, min_periods=n).std()
    else:
        # VWAP
        vwap = (df['quote_volume'].rolling(n, min_periods=n).sum() / 
                df['volume'].rolling(n, min_periods=n).sum())
        # StdDev
        std = df['close'].rolling(n, min_periods=n).std()
        
    upper = vwap + k * std
    lower = vwap - k * std
    
    return vwap, upper, lower

def run_backtest(df, n, k, weighting, mode, fee, slippage, leverage):
    print(f"⚙️  正在回测: Mode={mode} {weighting} N={n} K={k}")
    
    # 1. 计算指标
    middle, upper, lower = calculate_vwap_bands(df, n, k, weighting)
    close = df['close']
    
    # 2. 信号逻辑
    # 使用状态机逻辑循环 (向量化处理复杂逻辑较难，这里为了清晰展示逻辑分支，先用向量化近似或循环)
    # 为了准确性，特别是涉及止盈止损状态切换，建议使用向量化配合状态位，或者 Numba。
    # 这里为了保持 Python 原生且逻辑清晰，使用 pandas 向量化信号生成。
    
    long_signal = pd.Series(0, index=df.index)
    short_signal = pd.Series(0, index=df.index)
    close_signal = pd.Series(0, index=df.index) # 1=Close Long, -1=Close Short, 2=Close All
    
    if mode == 'Trend':
        # Trend_CenterToEdge
        # 开多: Close > Middle
        # 开空: Close < Middle
        # 平多: Close > Upper (止盈) OR Close < Middle (止损/反转)
        # 平空: Close < Lower (止盈) OR Close > Middle (止损/反转)
        
        # 简化版趋势逻辑: 
        # 在中轨上方持有直到上轨，在中轨下方持有直到下轨
        # 实际上这变成了:
        # Pos = 1 if Middle < Close < Upper
        # Pos = -1 if Lower < Close < Middle
        # Pos = 0 if Close > Upper or Close < Lower (超买超卖区平仓)
        
        # 但这样会有问题: 突破上轨后应该是极强趋势，平仓可能会踏空。
        # 不过根据用户需求 "触碰到上轨就平多"，我们严格执行。
        
        # 向量化逻辑:
        # Condition 1: Middle < Close < Upper -> Long Zone
        # Condition 2: Lower < Close < Middle -> Short Zone
        # Condition 3: Close > Upper -> Overbought (Flat)
        # Condition 4: Close < Lower -> Oversold (Flat)
        
        # 但要注意 hysteresis (滞后性)，不能频繁开平。
        # 比如 Close 刚刚 > Upper 平仓了，下一根 Close 回落到 Upper 下方一点点，是否立即由开多？
        # 通常建议: 碰上轨平仓后，必须等回到中轨由于才再次开仓？或者允许再次上车？
        # 这里采用简单逻辑: 只要在区间内就持有。
        
        # 修正: 严格按照用户描述 "收盘价大于中轨做多...触碰到上轨就平多"
        # 这意味着 Position 在 (CrossOver Middle) 时变为 1
        # Position 在 (Touch Upper) 时变为 0
        # Position 在 (CrossUnder Middle) 时变为 0 (或 -1)
        
        # 这种路径依赖逻辑很难纯向量化，使用简单的用于回测的状态生成器
        
        pos = np.zeros(len(df))
        curr_pos = 0 # 0, 1, -1
        
        c_arr = close.values
        m_arr = middle.values
        u_arr = upper.values
        l_arr = lower.values
        
        for i in range(1, len(df)):
            price = c_arr[i]
            m = m_arr[i]
            u = u_arr[i]
            l = l_arr[i]
            
            if np.isnan(m) or np.isnan(u):
                continue
            
            # 趋势逻辑
            if curr_pos == 0:
                if price > m and price < u: # 在中上轨之间，做多 (过滤掉直接跳空到上轨上方的极端情况)
                   curr_pos = 1
                elif price < m and price > l: # 在中下轨之间，做空
                   curr_pos = -1
            
            elif curr_pos == 1: # 持多单
                if price >= u: # 触及上轨，止盈
                    curr_pos = 0
                elif price < m: # 跌破中轨，止损/反转
                    curr_pos = -1 # 反手做空? 还是先平仓? 用户逻辑 implied "收盘价小于中轨就开空" -> 翻转
            
            elif curr_pos == -1: # 持空单
                if price <= l: # 触及下轨，止盈
                    curr_pos = 0
                elif price > m: # 升破中轨，止损/反转
                    curr_pos = 1
            
            pos[i] = curr_pos
            
    elif mode == 'Reversion':
        # Reversion_EdgeToCenter
        # 做空: 价格 > 上轨
        # 平空: 价格 < 中轨
        # 做多: 价格 < 下轨
        # 平多: 价格 > 中轨
        
        pos = np.zeros(len(df))
        curr_pos = 0 
        
        c_arr = close.values
        m_arr = middle.values
        u_arr = upper.values
        l_arr = lower.values
        
        for i in range(1, len(df)):
            price = c_arr[i]
            m = m_arr[i]
            u = u_arr[i]
            l = l_arr[i]
            
            if np.isnan(m): continue

            if curr_pos == 0:
                if price >= u: # 触及上轨，开空
                    curr_pos = -1
                elif price <= l: # 触及下轨，开多
                    curr_pos = 1
            
            elif curr_pos == 1: # 持多
                if price >= m: # 回归中轨，平仓
                    curr_pos = 0
                # 止损? 反转策略通常扛单，或者设固定止损。这里暂无硬性止损，直到回归。
            
            elif curr_pos == -1: # 持空
                if price <= m: # 回归中轨，平仓
                    curr_pos = 0
            
            pos[i] = curr_pos

    # 3. 计算收益
    pos_series = pd.Series(pos, index=df.index)
    change_pos = (pos_series - pos_series.shift(1).fillna(0)).abs()
    
    mkt_ret = df['close'].pct_change().fillna(0)
    strat_ret = (pos_series.shift(1).fillna(0) * mkt_ret * leverage) - (change_pos * (fee + slippage))
    
    equity = (1 + strat_ret).cumprod()
    return equity, pos_series

def report(equity, pos, close_price=None):
    if len(equity) == 0: return
    
    # 还原权益 (归一化 -> 绝对值)
    equity_val = equity.values * INITIAL_CASH
    
    # 1. 统一指标报告
    计算器 = 回测指标计算器(
        权益曲线=equity_val,
        初始资金=INITIAL_CASH,
        时间戳=equity.index,
        周期每年数量=525600
    )
    计算器.打印报告(策略名称=f"VWAP V7.3 ({LOGIC_MODE})")
    
    # 2. 统一可视化图表 (默认开启)
    if 'show_chart' not in globals() or globals()['show_chart']:
        可视化 = 回测可视化(
            权益曲线=equity_val,
            时间序列=equity.index,
            初始资金=INITIAL_CASH,
            价格序列=close_price,
            显示图表=True,
            保存路径=PROJECT_ROOT / "策略仓库/七号VWAP策略/v7.3_布林带"
        )
        可视化.生成报告(策略名称=f"VWAP V7.3 ({LOGIC_MODE})")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-chart", action="store_true", help="不显示图表")
    args = parser.parse_args()
    
    # 全局变量控制图表开关
    global show_chart
    show_chart = not args.no_chart

    try:
        data = load_data(DATA_PATH, START_DATE, END_DATE)
        equity_curve, pos = run_backtest(data, N, K, WEIGHTING_TYPE, LOGIC_MODE, FEE_RATE, SLIPPAGE, LEVERAGE)
        
        # 传入价格序列用于绘图
        report(equity_curve, pos, close_price=data['close'].values)
        
    except Exception as e:
        print(f"❌ 运行失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
