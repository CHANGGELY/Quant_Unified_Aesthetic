import streamlit as st
import time
import os
import subprocess
from datetime import datetime

# 设置页面标题
st.set_page_config(
    page_title="香农策略监控台",
    page_icon="📡",
    layout="wide",
)

st.title("📡 8号香农策略 - 实时监控")

# 日志文件路径
LOG_FILE = "runtime.log"

# CSS 美化
st.markdown("""
    <style>
    .stTextArea textarea {
        font-family: 'Consolas', 'Courier New', monospace;
        background-color: #1e1e1e;
        color: #d4d4d4;
    }
    </style>
    """, unsafe_allow_html=True)

# 侧边栏状态
with st.sidebar:
    st.header("系统状态")
    
    # 检查进程是否存活
    try:
        # 查找 real_trading.py 进程
        result = subprocess.run(["pgrep", "-f", "real_trading.py"], capture_output=True, text=True)
        is_running = result.returncode == 0
    except Exception:
        is_running = False
        
    if is_running:
        st.success("运行中 (Running)")
    else:
        st.error("已停止 (Stopped)")
        
    st.info(f"最后刷新: {datetime.now().strftime('%H:%M:%S')}")
    
    if st.button("刷新状态"):
        st.rerun()

# 主区域：显示日志
st.subheader("📝 实时日志 (Runtime Logs)")

# 自动刷新开关
auto_refresh = st.toggle("自动刷新 (每 5秒)", value=True)

# 读取日志内容
log_content = ""
if os.path.exists(LOG_FILE):
    try:
        # 读取最后 100 行
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            # 过滤不需要的杂音 (可选)
            filtered_lines = [line for line in lines if "HTTP Request:" not in line]
            log_content = "".join(filtered_lines[-100:])
    except Exception as e:
        log_content = f"读取日志错误: {e}"
else:
    log_content = "等待策略启动... (日志文件尚未创建)"

# 显示日志框
st.text_area("Log Output", log_content, height=600, key="log_area")

# 自动刷新逻辑
if auto_refresh:
    time.sleep(5)
    st.rerun()
