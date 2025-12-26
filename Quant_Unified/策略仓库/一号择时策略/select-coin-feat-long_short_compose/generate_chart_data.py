# -*- coding: utf-8 -*-
"""
生成回测可视化数据
导出 Top 5 参数资金曲线 + Buy & Hold 基准 为 JSON
"""

import pandas as pd
import numpy as np
from pathlib import Path
import json
import warnings

warnings.filterwarnings('ignore')

# 数据路径
DATA_PATH = Path('/Users/chuan/Desktop/xiangmu/客户端/Quant_Unified/策略仓库/二号网格策略/data_center/ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5')
OUTPUT_DIR = Path('/Users/chuan/Desktop/xiangmu/客户端/Quant_Unified/策略仓库/一号择时策略/select-coin-feat-long_short_compose/dashboard')

# Top 5 参数
TOP_PARAMS = [1196, 1195, 1197, 1190, 1200]

def 加载数据(file_path):
    """加载 H5 数据"""
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
    
    if 'quote_volume' not in df.columns:
        df['quote_volume'] = df['close'] * df['volume']
    
    # 从2021年开始
    df = df[df.index >= pd.to_datetime('2021-01-01')]
    print(f"数据加载完成。形状: {df.shape}")
    return df

def 计算VWAP(df, n):
    """计算 VWAP"""
    return (df['quote_volume'].rolling(n, min_periods=1).sum() / 
            df['volume'].rolling(n, min_periods=1).sum())

def 回测策略(df, n):
    """回测单个参数，返回资金曲线"""
    vwap = 计算VWAP(df, n)
    
    signal = pd.Series(0, index=df.index)
    signal[df['close'] > vwap] = 1
    signal[df['close'] < vwap] = -1
    
    pos = signal.shift(1).fillna(0)
    mkt_ret = df['close'].pct_change().fillna(0)
    
    strat_ret = pos * mkt_ret
    equity = (1 + strat_ret).cumprod()
    
    return equity

def 计算回撤(equity):
    """计算回撤序列"""
    roll_max = equity.cummax()
    drawdown = (equity - roll_max) / roll_max
    return drawdown

def 计算指标(equity):
    """计算年化收益、回撤、Calmar"""
    days = (equity.index[-1] - equity.index[0]).days
    years = max(days / 365.25, 0.001)
    
    final_val = float(equity.iloc[-1])
    ann_ret = (final_val) ** (1/years) - 1
    
    roll_max = equity.cummax()
    drawdown = (equity - roll_max) / roll_max
    max_dd = float(drawdown.min())
    
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0
    
    return {
        '年化收益': round(ann_ret * 100, 2),
        '最大回撤': round(max_dd * 100, 2),
        'Calmar': round(calmar, 2),
        '最终净值': round(final_val, 2)
    }

def main():
    print("🔥 生成可视化数据...")
    
    # 创建输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 加载数据
    df = 加载数据(DATA_PATH)
    
    # 重采样到日线（减少数据量，提升前端性能）
    df_daily = df.resample('1D').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'quote_volume': 'sum'
    }).dropna()
    
    print(f"重采样到日线: {df_daily.shape}")
    
    # 计算各策略资金曲线
    结果 = {}
    指标汇总 = {}
    
    for n in TOP_PARAMS:
        print(f"计算参数 N={n}...")
        equity = 回测策略(df, n)
        
        # 重采样到日线
        equity_daily = equity.resample('1D').last().dropna()
        
        结果[f'VWAP_{n}'] = {
            'dates': equity_daily.index.strftime('%Y-%m-%d').tolist(),
            'equity': equity_daily.round(4).tolist(),
            'drawdown': 计算回撤(equity_daily).round(4).tolist()
        }
        指标汇总[f'VWAP_{n}'] = 计算指标(equity_daily)
    
    # 计算 Buy & Hold
    print("计算 Buy & Hold...")
    buyhold = df['close'] / df['close'].iloc[0]
    buyhold_daily = buyhold.resample('1D').last().dropna()
    
    结果['Buy_Hold'] = {
        'dates': buyhold_daily.index.strftime('%Y-%m-%d').tolist(),
        'equity': buyhold_daily.round(4).tolist(),
        'drawdown': 计算回撤(buyhold_daily).round(4).tolist()
    }
    指标汇总['Buy_Hold'] = 计算指标(buyhold_daily)
    
    # 构建完整数据对象
    chart_data = {
        'curves': 结果,
        'metrics': 指标汇总
    }
    
    # 读取 HTML 模板
    template_path = OUTPUT_DIR / 'index.html'
    if not template_path.exists():
        print(f"❌ 错误: 未找到 HTML 模板文件: {template_path}")
        return

    with open(template_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # 替换数据加载逻辑
    # 我们将把 fetch('chart_data.json') ... 这一段替换为直接赋值
    json_str = json.dumps(chart_data, ensure_ascii=False)
    
    # JS 注入点：查找 loadData 函数并替换
    # 我们直接生成一个新的 standalone.html
    
    # 新的 JS 代码，直接包含数据
    new_js = f"""
        const chartData = {json_str};
        
        // 直接渲染，不再需要 fetch
        renderMetrics();
        renderCheckboxes();
        renderCharts();
        
        async function loadData() {{
            // 此函数已废弃，保留空壳防止报错
            console.log('Using embedded data');
        }}
    """
    
    # 简单的字符串替换：找到原来的 loadData() 调用和定义，替换掉
    # 这里我们采用一种更稳健的方法：替换整个 <script> 块中涉及数据加载的部分
    # 但为了简单有效，我们假设 index.html 结构固定。
    # 更好的方式是：在 index.html 里留一个占位符，或者我们直接重写整个 HTML 文件
    
    # 让我们重新构建 HTML 内容，确保它是独立的
    # 我们将读取现有的 CSS 和 HTML 结构，但注入新的 Script
    
    standalone_html = html_content.replace(
        "let chartData = null;", 
        f"let chartData = {json_str};"
    ).replace(
        "async function loadData() {", 
        "async function loadData() {\n            renderMetrics();\n            renderCheckboxes();\n            renderCharts();\n            return;"
    )
    
    output_file = OUTPUT_DIR / 'vwap_dashboard_standalone.html'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(standalone_html)
    
    print(f"✅ 独立版页面已生成: {output_file}")
    print("🚀 现在你可以直接双击打开这个文件，无需服务器！")

if __name__ == '__main__':
    main()
