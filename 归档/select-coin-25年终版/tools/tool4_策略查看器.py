"""
策略查看器 (Streamlit版)
使用说明：
        在终端运行: streamlit run tools/tool4_策略查看器.py
"""

import streamlit as st
import pandas as pd
import sys
import warnings
from pathlib import Path
import os
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ====================================================================================================
# Path Setup
# ====================================================================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.model.backtest_config import load_config
from tools.strategy_viewer.period_generator import PeriodGenerator
from tools.strategy_viewer.metrics_calculator import MetricsCalculator
from tools.strategy_viewer.coin_selector import CoinSelector
from tools.strategy_viewer.viewer_config import StrategyViewerConfig

warnings.filterwarnings("ignore")

# ====================================================================================================
# Default Configuration
# ====================================================================================================
DEFAULT_CONFIG = {
    "enabled": 1,
    "selection_mode": "rank",
    "metric_type": "return",
    "sort_direction": "desc",
    "selection_value": (1, 30),
    "target_symbols": [],
    "chart_days": 7,
    "show_volume": True,
}

# ====================================================================================================
# Helper Functions
# ====================================================================================================

@st.cache_data
def load_and_process_data(num_workers: int):
    """
    Load data and perform initial processing (Period Generation & Metrics Calculation).
    Cached by Streamlit to avoid re-running on every interaction.
    """
    # 1. Load Config
    try:
        conf = load_config()
    except Exception as e:
        st.error(f"加载回测配置失败: {e}")
        return None, None, None

    # 2. Determine Paths
    result_folder = conf.get_result_folder()
    select_result_path = result_folder / 'final_select_results.pkl'
    kline_data_path = Path('data') / 'candle_data_dict.pkl'

    # 3. Check Files
    if not select_result_path.exists():
        st.error(f"选币结果文件不存在: {select_result_path}\n请先运行完整回测（Step 1-4）生成选币结果")
        return None, None, None
    
    if not kline_data_path.exists():
        st.error(f"K线数据文件不存在: {kline_data_path}\n请先运行 Step 1 准备数据")
        return None, None, None

    # 4. Load Data
    with st.spinner('正在加载数据... (首次运行可能需要几秒钟)'):
        select_results = pd.read_pickle(select_result_path)
        kline_data_dict = pd.read_pickle(kline_data_path)

    for _, df in kline_data_dict.items():
        if 'candle_begin_time' in df.columns:
            if not pd.api.types.is_datetime64_any_dtype(df['candle_begin_time']):
                df['candle_begin_time'] = pd.to_datetime(df['candle_begin_time'])
            if df.index.name != 'candle_begin_time':
                df.set_index('candle_begin_time', inplace=True, drop=False)

    # 5. Generate Periods
    hold_period = conf.strategy.hold_period
    # Infer kline period from hold period
    if hold_period.upper().endswith('H'):
        kline_period = '1h'
    elif hold_period.upper().endswith('D'):
        kline_period = '1d'
    else:
        kline_period = '1h'

    generator = PeriodGenerator(hold_period, kline_period)
    periods_df = generator.generate(select_results)

    if periods_df.empty:
        st.warning("未生成任何交易期间")
        return None, None, None

    calculator = MetricsCalculator()
    periods_df = calculator.calculate(periods_df, kline_data_dict, workers=num_workers)

    return periods_df, kline_data_dict, conf, kline_period

def get_kline_chart_fig(period_row, kline_df, config, kline_period):
    """
    Generate Plotly Figure for a specific period.
    Adapted from HTMLReporter._generate_kline_chart.
    """
    entry_time = period_row['entry_time']
    exit_time = period_row['exit_time']
    
    # Calculate display range
    kline_period_td = pd.to_timedelta(kline_period)
    
    # Parse chart_days
    chart_days_val = config['chart_days']
    
    if kline_period_td >= pd.Timedelta(hours=1):
        # Daily or larger
        try:
            days = int(chart_days_val)
        except:
            days = 7
        display_start = entry_time - pd.Timedelta(days=days)
        display_end = exit_time + pd.Timedelta(days=days)
    else:
        # Intraday
        holding_duration = exit_time - entry_time
        holding_klines = holding_duration / kline_period_td
        
        if chart_days_val == 'auto':
            if holding_klines < 10: percentage = 5
            elif holding_klines < 20: percentage = 15
            else: percentage = 20
            
            total_klines = holding_klines / (percentage / 100)
            if total_klines < 50:
                expand_klines = (50 - holding_klines) / 2
                expand_duration = expand_klines * kline_period_td
            else:
                expand_multiplier = (100 - percentage) / (2 * percentage)
                expand_duration = holding_duration * expand_multiplier
        
        elif isinstance(chart_days_val, str) and chart_days_val.endswith('k'):
            try:
                expand_klines = int(chart_days_val[:-1])
                expand_duration = expand_klines * kline_period_td
            except:
                expand_duration = pd.Timedelta(days=1)
        
        else:
            try:
                percentage = int(chart_days_val)
                total_klines = holding_klines / (percentage / 100)
                if total_klines < 50:
                    expand_klines = (50 - holding_klines) / 2
                    expand_duration = expand_klines * kline_period_td
                else:
                    expand_multiplier = (100 - percentage) / (2 * percentage)
                    expand_duration = holding_duration * expand_multiplier
            except:
                # Fallback
                expand_duration = pd.Timedelta(days=1)

        display_start = entry_time - expand_duration
        display_end = exit_time + expand_duration

    # Filter Kline Data
    if 'candle_begin_time' in kline_df.columns:
        if not pd.api.types.is_datetime64_any_dtype(kline_df['candle_begin_time']):
            kline_df['candle_begin_time'] = pd.to_datetime(kline_df['candle_begin_time'])
    if 'MA7' not in kline_df.columns or 'MA14' not in kline_df.columns:
        kline_df['MA7'] = kline_df['close'].rolling(window=7, min_periods=1).mean()
        kline_df['MA14'] = kline_df['close'].rolling(window=14, min_periods=1).mean()
    display_kline = kline_df[
        (kline_df['candle_begin_time'] >= display_start) &
        (kline_df['candle_begin_time'] <= display_end)
    ].copy()
    
    if display_kline.empty:
        return None

    # Create Figure
    if config['show_volume']:
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.75, 0.25],
            subplot_titles=('价格', '成交量')
        )
    else:
        fig = go.Figure()

    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=display_kline['candle_begin_time'],
            open=display_kline['open'],
            high=display_kline['high'],
            low=display_kline['low'],
            close=display_kline['close'],
            name='K线',
            increasing_line_color='#26a69a',
            increasing_fillcolor='#26a69a',
            decreasing_line_color='#ef5350',
            decreasing_fillcolor='#ef5350',
        ),
        row=1, col=1
    )

    # MA Lines
    fig.add_trace(
        go.Scatter(x=display_kline['candle_begin_time'], y=display_kline['MA7'], mode='lines', name='MA7', line=dict(width=1, color='#ff9800')),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(x=display_kline['candle_begin_time'], y=display_kline['MA14'], mode='lines', name='MA14', line=dict(width=1, color='#2196f3')),
        row=1, col=1
    )

    # Highlight Period
    fig.add_vrect(
        x0=entry_time, x1=exit_time,
        fillcolor='rgba(255, 193, 7, 0.3)', layer='below', line_width=0,
        annotation_text="交易期间", annotation_position="top left",
        row=1, col=1
    )

    # Volume
    if config['show_volume']:
        colors = ['#26a69a' if c >= o else '#ef5350' for c, o in zip(display_kline['close'], display_kline['open'])]
        fig.add_trace(
            go.Bar(x=display_kline['candle_begin_time'], y=display_kline['volume'], name='成交量', marker_color=colors, opacity=0.7),
            row=2, col=1
        )

    # Layout
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=500,
        hovermode='x unified',
        template='plotly_white',
        margin=dict(l=50, r=50, t=30, b=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    
    return fig

# ====================================================================================================
# Main App
# ====================================================================================================

def main():
    st.set_page_config(page_title="策略查看器", page_icon="📊", layout="wide")
    
    st.title("📊 策略查看器")
    st.markdown("---")

    cpu_count = os.cpu_count() or 1
    default_workers = max(1, cpu_count // 2)

    st.sidebar.header("⚙️ 筛选配置")
    st.sidebar.subheader("并行计算")
    st.sidebar.markdown(
        f"当前机器检测到 **{cpu_count} 核心 CPU**。"
        " 线程数越大，计算越快，但 CPU 占用也越高。"
        " 一般建议设置为 CPU 核心数的一半到等于核心数之间。"
    )
    num_workers = st.sidebar.number_input(
        "并行线程数",
        min_value=1,
        max_value=cpu_count,
        value=default_workers,
        step=1,
    )

    data_load_state = st.text('正在加载数据...')
    result = load_and_process_data(int(num_workers))
    if not result or result[0] is None:
        data_load_state.text("数据加载失败")
        st.stop()
    
    periods_df, kline_data_dict, conf, kline_period = result
    data_load_state.text(f"数据加载完成! 策略: {conf.name}, 共 {len(periods_df)} 个交易期间")
    data_load_state.empty()

    st.sidebar.header("⚙️ 筛选配置")
    
    # Mode Selection
    selection_mode = st.sidebar.selectbox(
        "选择模式", 
        options=['rank', 'pct', 'val', 'symbol'],
        index=['rank', 'pct', 'val', 'symbol'].index(DEFAULT_CONFIG['selection_mode']),
        format_func=lambda x: {'rank': 'Rank (排名)', 'pct': 'Pct (百分比)', 'val': 'Value (数值)', 'symbol': 'Symbol (币种)'}[x]
    )

    # Metric Type
    metric_type = st.sidebar.selectbox(
        "排序指标",
        options=['return', 'max_drawdown', 'volatility', 'return_drawdown_ratio'],
        index=['return', 'max_drawdown', 'volatility', 'return_drawdown_ratio'].index(DEFAULT_CONFIG['metric_type']),
        format_func=lambda x: {'return': '收益率', 'max_drawdown': '最大回撤', 'volatility': '波动率', 'return_drawdown_ratio': '收益回撤比'}[x]
    )

    # Sort Direction
    sort_direction = st.sidebar.selectbox(
        "排序方向",
        options=['desc', 'asc', 'auto'],
        index=['desc', 'asc', 'auto'].index(DEFAULT_CONFIG['sort_direction']),
        format_func=lambda x: {'desc': '降序 (Desc)', 'asc': '升序 (Asc)', 'auto': '自动 (Auto)'}[x]
    )

    # Selection Value (Dynamic)
    st.sidebar.subheader("筛选参数")
    selection_value = None
    target_symbols = []

    if selection_mode == 'rank':
        col1, col2 = st.sidebar.columns(2)
        start_rank = col1.number_input("起始排名", min_value=1, value=1, step=1)
        end_rank = col2.number_input("结束排名", min_value=1, value=30, step=1)
        selection_value = (start_rank, end_rank)
    
    elif selection_mode == 'pct':
        pct_range = st.sidebar.slider("选择百分比范围", 0.0, 1.0, (0.0, 0.1), 0.01)
        selection_value = pct_range
        
    elif selection_mode == 'val':
        col1, col2 = st.sidebar.columns(2)
        min_val = col1.number_input("最小值", value=0.05, format="%.4f")
        max_val = col2.number_input("最大值", value=0.20, format="%.4f")
        selection_value = (min_val, max_val)
        
    elif selection_mode == 'symbol':
        all_symbols = sorted(periods_df['symbol'].unique().tolist())
        target_symbols = st.sidebar.multiselect("选择币种", all_symbols, default=all_symbols[:1] if all_symbols else [])
        selection_value = (1, 100) # Dummy value for symbol mode
    
    # Other Configs
    st.sidebar.markdown("---")
    chart_days = st.sidebar.text_input("K线显示范围 (天数/'auto'/'30k')", value="7")
    show_volume = st.sidebar.checkbox("显示成交量", value=True)
    
    max_display = st.sidebar.number_input("最大显示数量 (防止卡顿)", min_value=1, max_value=100, value=20)

    # 3. Construct Viewer Config
    viewer_config_dict = {
        "enabled": 1,
        "selection_mode": selection_mode,
        "metric_type": metric_type,
        "sort_direction": sort_direction,
        "selection_value": selection_value,
        "target_symbols": target_symbols,
        "chart_days": chart_days,
        "show_volume": show_volume
    }
    
    viewer_config = StrategyViewerConfig.from_dict(viewer_config_dict)

    # 4. Filter Data
    selector = CoinSelector(viewer_config)
    selected_periods = selector.select(periods_df)

    # 5. Display Summary
    st.subheader("📈 汇总统计")
    
    if selected_periods.empty:
        st.warning("⚠️ 筛选后无结果，请调整筛选参数")
    else:
        col1, col2, col3, col4 = st.columns(4)
        total_count = len(selected_periods)
        win_rate = (selected_periods['return'] > 0).mean()
        avg_return = selected_periods['return'].mean()
        avg_dd = selected_periods['max_drawdown'].mean()

        col1.metric("交易次数", f"{total_count}")
        col2.metric("胜率", f"{win_rate:.1%}")
        col3.metric("平均收益", f"{avg_return:.2%}", delta_color="normal")
        col4.metric("平均回撤", f"{avg_dd:.2%}", delta_color="inverse")
        
        # 6. Display Details
        st.subheader(f"🔍 交易详情 (显示前 {min(len(selected_periods), max_display)} 个)")
        
        # Limit display count
        display_periods = selected_periods.head(max_display)
        
        for idx, row in display_periods.iterrows():
            with st.expander(f"#{row['current_rank']} {row['symbol']} | 收益: {row['return']:.2%} | {row['entry_time']} -> {row['exit_time']}", expanded=(idx == display_periods.index[0])):
                
                # Metrics Table
                m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns(5)
                m_col1.markdown(f"**方向**: {'🟢 做多' if row['direction'] == 'long' else '🔴 做空'}")
                m_col2.markdown(f"**收益率**: `{row['return']:.2%}`")
                m_col3.markdown(f"**最大回撤**: `{row['max_drawdown']:.2%}`")
                m_col4.markdown(f"**波动率**: `{row['volatility']:.2%}`")
                m_col5.markdown(f"**持仓**: `{row['holding_hours']:.1f}h`")
                
                # Chart
                kline_df = kline_data_dict.get(row['symbol'])
                if kline_df is None:
                    st.error("缺少K线数据")
                else:
                    fig = get_kline_chart_fig(row, kline_df, viewer_config_dict, kline_period)
                    if fig:
                        st.plotly_chart(fig, use_container_width=True, key=f"chart_{idx}")
                    else:
                        st.warning("K线数据不足，无法绘图")

if __name__ == "__main__":
    try:
        # Check if running in Streamlit
        import streamlit.runtime.scriptrunner
        main()
    except (ImportError, ModuleNotFoundError):
        # Fallback or instructions if run directly with python
        # Actually, `streamlit run` executes the script, so __name__ is still __main__
        # But `streamlit` module is available.
        # If run as `python tool3.py`, it will not have streamlit context and might fail on st.commands
        # So we print instruction.
        if st.runtime.exists():
            main()
        else:
            print("\n" + "="*80)
            print("  策略查看器 (Streamlit版)")
            print("="*80)
            print("\n  请使用 Streamlit 运行此工具：")
            print(f"\n  streamlit run {Path(__file__).name}")
            print("\n" + "="*80 + "\n")
