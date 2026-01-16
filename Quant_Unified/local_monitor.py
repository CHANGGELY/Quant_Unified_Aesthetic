# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from supabase import create_client
import time
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 加载本地 .env (如果有)
load_dotenv()

# ==========================================
# 自动启动逻辑 (允许直接点击运行)
# ==========================================
if __name__ == "__main__":
    import sys
    import logging
    # 简单的检测方法：如果直接运行 python 脚本，sys.modules 中不会有 streamlit 的 runtime
    # 但由于我们开头 import 了 streamlit，所以最好用 st.runtime.exists()
    try:
        from streamlit.web import cli as stcli
        if not st.runtime.exists():
            print("🚀 正在启动 Streamlit...")
            sys.argv = ["streamlit", "run", sys.argv[0]]
            sys.exit(stcli.main())
    except Exception as e:
        pass # 如果检测失败，就继续往下走，或者本来就在 streamlit 环境中


st.set_page_config(
    page_title="香农策略云端监控",
    page_icon="☁️",
    layout="wide"
)

# ==========================================
# 配置区
# ==========================================
with st.sidebar:
    st.title("🛠 配置")
    
    # 优先从环境变量读，否则让用户填
    env_url = os.getenv("SUPABASE_URL", "")
    env_key = os.getenv("SUPABASE_KEY", "")
    
    supabase_url = st.text_input("Supabase URL", value=env_url, type="password")
    supabase_key = st.text_input("Supabase Key (Anon)", value=env_key, type="password")
    
    limit_num = st.slider("显示最近数据点 (分钟)", 60, 2000, 1440)
    auto_refresh = st.toggle("自动刷新 (60s)", value=True)
    
    # ==========================================
    # 语言切换
    # ==========================================
    lang = st.radio("语言 / Language", ["中文", "English"], index=0, horizontal=True)
    is_cn = lang == "中文"

    st.markdown("---")
    st.markdown("### 说明")
    st.markdown("此面板读取云端数据库 `strategy_logs` 表，展示策略实盘表现。" if is_cn else "This dashboard reads `strategy_logs` from Supabase to show live performance.")

# ==========================================
# 核心逻辑
# ==========================================

@st.cache_resource
def get_client(url, key):
    if not url or not key:
        return None
    return create_client(url, key)

def fetch_data(client, limit):
    """从 Supabase 获取最近 n 条数据"""
    try:
        response = client.table("strategy_logs") \
            .select("*") \
            .order("timestamp", desc=True) \
            .limit(limit) \
            .execute()
        
        data = response.data
        if not data:
            return pd.DataFrame()
            
        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp') # 绘图需要时间正序
        return df
    except Exception as e:
        st.error(f"数据获取失败: {e}")
        return pd.DataFrame()

# ==========================================
# 界面渲染
# ==========================================
st.title("☁️ 8号香农策略 - 云端实盘监控" if is_cn else "☁️ Shannon Strat - Cloud Monitor")

if not supabase_url or not supabase_key:
    st.warning("👈 请在左侧侧边栏配置 Supabase 连接信息" if is_cn else "Please configure Supabase in the sidebar")
    st.stop()

client = get_client(supabase_url, supabase_key)

# 获取数据
with st.spinner("正在同步云端数据..." if is_cn else "Syncing data..."):
    df = fetch_data(client, limit_num)

if df.empty:
    st.info("暂无数据。请确保云端策略已启动并开始上报。" if is_cn else "No data. Ensure strategy is running.")
else:
    # 1. 核心指标卡片
    last_row = df.iloc[-1]
    last_roi = last_row.get('roi', 0)
    last_equity = last_row.get('equity', 0)
    last_width = last_row.get('grid_width', 0)
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("当前净值 (USDC)" if is_cn else "Equity (USDC)", f"${last_equity:.2f}")
    col2.metric("累计收益率 (ROI)" if is_cn else "ROI", f"{last_roi:.2%}", delta_color="normal")
    col3.metric("当前网格宽度" if is_cn else "Grid Width", f"{last_width:.2%}")
    col4.metric("市场状态 (Regime)" if is_cn else "Regime", last_row.get('regime', 'Unknown'))
    
    # 2. 资金曲线图
    st.subheader("📈 资金曲线 (Equity Curve)")
    st.line_chart(df, x="timestamp", y="equity", color="#00FF00")
    
    # 3. 详细数据图表
    st.subheader("📊 详细数据 (Price & Grid Width)" if is_cn else "📊 Details")
    
    # 双轴图比较难画，分开画
    st.caption("价格走势 (ETH/USDC)" if is_cn else "Price (ETH/USDC)")
    st.line_chart(df, x="timestamp", y="price")
    
    st.caption("网格宽度变化 (Volatility Proxy)" if is_cn else "Grid Width (Vol)")
    st.line_chart(df, x="timestamp", y="grid_width")
    
    # 4. 数据表格
    with st.expander("查看原始数据 (最近100条)" if is_cn else "Raw Data"):
        # 汉化表头
        df_display = df.tail(100).sort_values('timestamp', ascending=False).copy()
        if is_cn:
            df_display = df_display.rename(columns={
                "timestamp": "时间",
                "symbol": "交易对",
                "price": "价格",
                "equity": "净值",
                "roi": "收益率",
                "grid_width": "网格宽度",
                "regime": "状态",
                "vol_short": "短期波动",
                "vol_long": "长期波动",
                "ratio": "仓位比例",
                "available": "可用余额",
                "position": "持仓数量",
                "leverage_real": "实际杠杆"
            })
        st.dataframe(df_display)

# 自动刷新
if auto_refresh:
    time.sleep(60)
    st.rerun()
