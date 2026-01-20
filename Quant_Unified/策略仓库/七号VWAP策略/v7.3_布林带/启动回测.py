# -*- coding: utf-8 -*-
"""
七号 VWAP 策略（V7.3.1 布林带回归）- 启动回测

这个文件是干嘛的？
    用历史分钟 K 线（开/高/低/收）回测 V7.3.1 版本的 VWAP“轨道策略”（像布林带一样有上轨/下轨）。
    核心规则（用一句话概括）：
        价格偏离上/下轨就“反向开仓”，回到 VWAP（中轨）就止盈；若继续突破到 (k+1)×σ 就止损。

术语解释（用人话）：
    - VWAP（Volume Weighted Average Price：成交量加权平均价）
      类比：买得越多的成交价，对“平均价”的影响越大。
    - 布林带（Bollinger Bands）：一条中轨 + 上下两条“波动范围轨道”，用来判断价格是否“偏离太多”。
    - EMA（Exponential Moving Average：指数移动平均）：
      类比：越新的数据权重越大，反应更快。
    - SMA（Simple Moving Average：简单移动平均）：
      类比：窗口里的每个数据权重一样，反应更慢但更平滑。
"""

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
# 策略版本
STRATEGY_VERSION = "V7.3.1"

# 默认参数
N = 1391                  # 周期
K = 2.0                   # 轨道宽度 k：V7.3.1 初始取 2（后续可做参数优化）
WEIGHTING_TYPE = 'EMA'    # 加权方式
LOGIC_MODE = 'Reversion_Stop'  # 模式: 'Reversion_Stop'（回归 + 止损，V7.3.1）

START_DATE = '2021-01-01'
END_DATE   = '2025-06-15'

FEE_RATE   = 0.0000       # 模拟 Maker (0 费率)
SLIPPAGE   = 0.0001
INITIAL_CASH = 10000
LEVERAGE   = 1.0

# 自动处理数据路径
from 基础库.common_core.data_center import 生成分钟K线文件名, 获取分钟K线H5文件

DATA_PATH = 获取分钟K线H5文件(
    生成分钟K线文件名("ETHUSDT", 开始日期="2019-11-01", 结束日期="2025-06-15", 带table后缀=True)
)
# =========================================================

def load_data(file_path, start, end):
    print(f"📂 [{STRATEGY_VERSION} 布林带] 正在加载 ETH 历史数据...")
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
    """
    计算 VWAP + “布林带”轨道。

    说明（用人话）：
        - 中轨：VWAP（成交量加权平均价）
        - 上下轨：VWAP ± k × 标准差（σ）
        - 标准差 σ：这里用价格序列的标准差近似（业界常见做法）
    """

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
    
    return vwap, upper, lower, std

def run_backtest(df, n, k, weighting, mode, fee, slippage, leverage):
    print(f"⚙️  正在回测: Mode={mode} {weighting} N={n} K={k}")
    
    # 1. 计算指标
    middle, upper, lower, std = calculate_vwap_bands(df, n, k, weighting)
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
            
            if np.isnan(m):
                pos[i] = curr_pos
                continue

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

    elif mode == 'Reversion_Stop':
        """
        V7.3.1：布林带回归策略（带止损）

        开仓：
            - Price > Upper：做空（认为超买，将回落）
            - Price < Lower：做多（认为超卖，将反弹）

        止盈：
            - 触碰 VWAP（中轨）就平仓

        止损：
            - 价格继续突破，超过 (k+1) × σ 时止损
              做空止损：VWAP + (k+1)×σ
              做多止损：VWAP - (k+1)×σ
        """

        pos = np.zeros(len(df))
        curr_pos = 0

        c_arr = close.values
        m_arr = middle.values
        u_arr = upper.values
        l_arr = lower.values
        s_arr = std.values

        for i in range(1, len(df)):
            price = c_arr[i]
            m = m_arr[i]
            u = u_arr[i]
            l = l_arr[i]
            s = s_arr[i]

            if np.isnan(m) or np.isnan(s):
                pos[i] = curr_pos
                continue

            # 止损带（比入场带更远 1 个标准差）
            upper_stop = m + (k + 1.0) * s
            lower_stop = m - (k + 1.0) * s

            if curr_pos == 0:
                if price > u:      # 突破上轨，开空
                    curr_pos = -1
                elif price < l:    # 跌破下轨，开多
                    curr_pos = 1

            elif curr_pos == 1:  # 持多
                # 先判止损，再判止盈（更安全：先保命）
                if price <= lower_stop:
                    curr_pos = 0
                elif price >= m:
                    curr_pos = 0

            elif curr_pos == -1:  # 持空
                if price >= upper_stop:
                    curr_pos = 0
                elif price <= m:
                    curr_pos = 0

            pos[i] = curr_pos

    # 3. 计算收益
    pos_series = pd.Series(pos, index=df.index)
    change_pos = (pos_series - pos_series.shift(1).fillna(0)).abs()
    
    mkt_ret = df['close'].pct_change().fillna(0)
    strat_ret = (pos_series.shift(1).fillna(0) * mkt_ret * leverage) - (change_pos * (fee + slippage))
    
    equity = (1 + strat_ret).cumprod()
    return equity, pos_series

def report(equity, pos, 策略名称, close_price=None):
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
    计算器.打印报告(策略名称=策略名称)
    
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
        可视化.生成报告(策略名称=策略名称)

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-chart", action="store_true", help="不显示图表")
    parser.add_argument("--mode", type=str, default=LOGIC_MODE, help="回测模式: Trend / Reversion / Reversion_Stop")
    parser.add_argument("--k", type=float, default=K, help="轨道宽度 k（倍数）")
    parser.add_argument("--n", type=int, default=N, help="周期 N")
    parser.add_argument("--weighting", type=str, default=WEIGHTING_TYPE, help="加权方式: EMA / SMA")
    args = parser.parse_args()
    
    # 全局变量控制图表开关
    global show_chart
    show_chart = not args.no_chart

    try:
        data = load_data(DATA_PATH, START_DATE, END_DATE)
        mode = args.mode
        k = float(args.k)
        n = int(args.n)
        weighting = args.weighting

        策略名称 = f"VWAP {STRATEGY_VERSION} ({mode}) N={n} K={k} {weighting}"

        equity_curve, pos = run_backtest(data, n, k, weighting, mode, FEE_RATE, SLIPPAGE, LEVERAGE)
        
        # 传入价格序列用于绘图
        report(equity_curve, pos, 策略名称=策略名称, close_price=data['close'].values)
        
    except Exception as e:
        print(f"❌ 运行失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
