# -*- coding: utf-8 -*-
"""
Quant_Unified 监控面板 (Gradio 版)
这是一个运行在 Hugging Face Spaces 上的监控应用，它会：
1. 在后台启动数据采集服务。
2. 实时从 Supabase 获取并显示各个服务的运行状态。
"""

import gradio as gr
import os
import subprocess
import time
import pandas as pd
from supabase import create_client
from datetime import datetime
import threading

# ==========================================
# 1. 配置与初始化
# ==========================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

# 初始化 Supabase 客户端
supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def 启动后台采集():
    """在独立进程中启动采集脚本"""
    print("🚀 正在启动后台采集服务...")
    script_path = os.path.join("服务", "数据采集", "启动采集.py")
    # 设置环境变量，确保子进程能找到项目根目录
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()
    # 使用 sys.executable 确保使用相同的 Python 解释器
    import sys
    process = subprocess.Popen(
        [sys.executable, script_path],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True
    )
    # 实时打印日志到终端（HF 容器日志可见）
    for line in process.stdout:
        print(f"[Collector] {line.strip()}")

def 周期性整理与同步():
    """每隔 4 小时执行一次数据整理与 HF 同步"""
    import sys
    organize_script = os.path.join("服务", "数据采集", "整理行情数据.py")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()
    
    while True:
        # 等待一段时间再执行第一次（让采集运行一会儿）
        time.sleep(60) # 启动后 1 分钟先跑一次
        print("🕒 开始执行周期性数据整理与同步...")
        try:
            # 1. 执行整理 (整理后会自动删除原始碎片)
            subprocess.run([sys.executable, organize_script], env=env, check=True)
            
            # 2. 执行云端同步
            print("📤 开始同步到 Hugging Face Dataset...")
            from 服务.数据采集.hf_sync import sync_to_hf
            if sync_to_hf():
                print("✅ 周期性整理与同步完成。")
        except Exception as e:
            print(f"❌ 周期性整理与同步失败: {e}")
        
        # 每 4 小时运行一次
        time.sleep(4 * 3600)

# 启动后台线程
thread_collector = threading.Thread(target=启动后台采集, daemon=True)
thread_collector.start()

thread_sync = threading.Thread(target=周期性整理与同步, daemon=True)
thread_sync.start()

# ==========================================
# 2. UI 逻辑
# ==========================================
def 获取监控数据():
    """从 Supabase 获取 service_status 表的所有数据"""
    if not supabase:
        return pd.DataFrame([{"错误": "未配置 SUPABASE_URL 或 KEY"}])
    
    try:
        response = supabase.table("service_status").select("*").execute()
        data = response.data
        if not data:
            return pd.DataFrame([{"信息": "目前没有服务在运行"}])
        
        # 转换为 DataFrame 方便展示
        df = pd.DataFrame(data)
        
        # --- 新增：从嵌套的 details 字典中提取性能指标 ---
        def extract_metrics(row):
            details = row.get("details", {})
            if isinstance(details, dict):
                row["cpu_percent"] = details.get("cpu_percent", "")
                row["memory_percent"] = details.get("memory_percent", "")
                # 将 details 转换为更易读的字符串，或者只保留除指标外的其他信息
                other_details = {k: v for k, v in details.items() if k not in ["cpu_percent", "memory_percent"]}
                row["details_str"] = str(other_details)
            else:
                row["details_str"] = str(details)
            return row

        df = df.apply(extract_metrics, axis=1)
        
        # 简单处理下时间格式
        if "updated_at" in df.columns:
            df["更新时间"] = pd.to_datetime(df["updated_at"]).dt.strftime('%Y-%m-%d %H:%M:%S')
            df = df.drop(columns=["updated_at"])
        
        # 重命名列名，让高中生也能看懂
        rename_map = {
            "service_name": "服务名称",
            "status": "状态",
            "cpu_percent": "CPU使用率(%)",
            "memory_percent": "内存使用率(%)",
            "details_str": "详细信息"
        }
        # 只保留需要的列
        cols = ["service_name", "status", "details_str", "cpu_percent", "memory_percent", "更新时间"]
        available_cols = [c for c in cols if c in df.columns]
        df = df[available_cols].rename(columns=rename_map)
        return df
    except Exception as e:
        return pd.DataFrame([{"错误": f"获取数据失败: {str(e)}"}])

def 检查配置状态():
    status = {
        "SUPABASE_URL": "✅ 已配置" if os.getenv("SUPABASE_URL") else "❌ 未配置",
        "SUPABASE_KEY": "✅ 已配置" if (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")) else "❌ 未配置",
        "HF_TOKEN": "✅ 已配置" if os.getenv("HF_TOKEN") else "❌ 未配置 (需手动在 Settings -> Secrets 配置)",
    }
    return status

# ==========================================
# 3. 构建 Gradio 界面
# ==========================================
with gr.Blocks(title="Quant_Unified 监控中心", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🚀 Quant_Unified 量化系统监控中心")
    
    with gr.Accordion("🛠️ 系统环境检查", open=False):
        conf = 检查配置状态()
        for k, v in conf.items():
            gr.Markdown(f"**{k}**: {v}")
            
    gr.Markdown("实时展示部署在云端的采集服务状态。数据通过 Supabase 同步。")
    gr.Markdown("---") # 添加一个小分隔线触发重启
    
    with gr.Row():
        status_table = gr.DataFrame(
            label="服务状态列表", 
            value=获取监控数据, 
            every=5,
            interactive=False
        ) 
        
    with gr.Row():
        refresh_btn = gr.Button("手动刷新")
        refresh_btn.click(获取监控数据, outputs=status_table)

    gr.Markdown("---")
    gr.Markdown("💡 **提示**：如果状态显示为 'ok'，说明后台采集正在正常工作。")

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
