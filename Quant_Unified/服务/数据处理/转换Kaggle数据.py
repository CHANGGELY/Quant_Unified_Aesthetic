"""
脚本名称: 转换Kaggle数据.py
功能描述: 
    将 Kaggle 下载的分钟级 CSV 格式订单簿数据转换为系统标准的 Parquet 格式。
    原数据结构: [Symbol, 50*AskP, 50*AskQ, 50*BidP, 50*BidQ, Timestamp]
    目标路径: data/外部数据/Kaggle_L2_1m/{symbol}/{date}/depth.parquet

使用说明:
    1. 确保 archive.zip 位于 data/分钟级盘口/archive.zip
    2. 直接运行此脚本
    3. 脚本会自动解压、清洗、重命名列、并按日期分片存储

注意事项:
    - 这里的 BTC_USDT 是现货(Spot)数据，跟合约(Futures)有基差，但用来训练趋势模型是可以的。
    - 只有分钟级快照，无法计算高频因子(OFI等)，适合做中低频策略。
"""

import zipfile
import pandas as pd
import numpy as np
from pathlib import Path
import os
import sys

# 添加项目根目录到路径，以便导入配置（如果需要）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

# 配置
ZIP_PATH = PROJECT_ROOT / "data/分钟级盘口/archive.zip"
OUTPUT_ROOT = PROJECT_ROOT / "data/外部数据/Kaggle_L2_1m"
TEMP_DIR = PROJECT_ROOT / "data/temp_kaggle_extract"

# 映射配置
SOURCE_DEPTH_LEVEL = 50 # Kaggle 文件固定为 50 档

# 导入全局配置 (目标档位)
try:
    from config import DEPTH_LEVEL as TARGET_DEPTH_LEVEL
except ImportError:
    try:
        from Quant_Unified.config import DEPTH_LEVEL as TARGET_DEPTH_LEVEL
    except ImportError:
        TARGET_DEPTH_LEVEL = SOURCE_DEPTH_LEVEL

def setup_directories():
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

def process_single_csv(csv_path: Path):
    print(f"🔄 正在处理: {csv_path.name} ...")
    
    # 1. 读取 CSV (无表头，自动分配)
    # 使用 low_memory=False 防止混合类型警告
    try:
        df = pd.read_csv(csv_path, header=None, low_memory=False)
        
        # 检查第一行是否为表头 (通过最后一列是否为 "time_exchange_minute" 判断)
        # Kaggle 数据有的有表头，有的可能没有，需要动态判断
        if df.iloc[0, 201] == "time_exchange_minute":
            print(f"   检测到表头，正在移除...")
            df = df.iloc[1:]
            
    except Exception as e:
        print(f"❌ 读取失败 {csv_path.name}: {e}")
        return

    # 2. 验证列数
    expected_cols = 1 + (DEPTH_LEVEL * 4) + 1 # Symbol + 4*50 + Timestamp
    if len(df.columns) != expected_cols:
        print(f"⚠️ 列数不匹配: 期望 {expected_cols}, 实际 {len(df.columns)}. 跳过此文件。")
        return

    # 3. 重命名列
    # Kaggle 结构: Symbol(0), AskP(1-50), AskQ(51-100), BidP(101-150), BidQ(151-200), Timestamp(201)
    # 注意: 这里的 AskP 是升序 (Ask1...Ask50), BidP 是降序 (Bid1...Bid50), 符合我们系统的标准
    
    new_columns = {}
    new_columns[0] = "original_symbol"
    new_columns[201] = "timestamp_str"
    
    # 映射 Ask Prices (Col 1-50) -> ask1_p ... ask50_p
    for i in range(1, 51):
        new_columns[i] = f"ask{i}_p"
        
    # 映射 Ask Qtys (Col 51-100) -> ask1_q ... ask50_q
    for i in range(51, 101):
        level = i - 50
        new_columns[i] = f"ask{level}_q"
        
    # 映射 Bid Prices (Col 101-150) -> bid1_p ... bid50_p
    for i in range(101, 151):
        level = i - 100
        new_columns[i] = f"bid{level}_p"
        
    # 映射 Bid Qtys (Col 151-200) -> bid1_q ... bid50_q
    for i in range(151, 201):
        level = i - 150
        new_columns[i] = f"bid{level}_q"
        
    df = df.rename(columns=new_columns)
    
    # 4. 数据清洗与转换
    print(f"   转换时间戳与格式...")
    
    # 解析时间戳 2023-10-07T11:23:00.000Z
    df["datetime"] = pd.to_datetime(df["timestamp_str"])
    df["timestamp"] = df["datetime"].astype("int64") / 10**9 # 转为秒级浮点数
    
    # 提取日期用于分片
    df["date_str"] = df["datetime"].dt.strftime("%Y-%m-%d")
    
    # 提取 Symbol (去除 BINANCE_SPOT_ 前缀，虽然它是现货，但为了系统兼容，我们保留核心部分)
    # 例如 BINANCE_SPOT_BTC_USDT -> BTCUSDT
    sample_symbol = df["original_symbol"].iloc[0]
    clean_symbol = sample_symbol.replace("BINANCE_SPOT_", "").replace("_", "")
    
    # 5. 按日期分片保存
    print(f"   正在分片保存到 {OUTPUT_ROOT}/{clean_symbol} ...")
    
    # 获取所有不重复的日期
    unique_dates = df["date_str"].unique()
    
    for date_str in unique_dates:
        day_df = df[df["date_str"] == date_str].copy()
        
        # 丢弃辅助列
        cols_to_drop = ["original_symbol", "timestamp_str", "datetime", "date_str"]
        final_df = day_df.drop(columns=cols_to_drop)
        
        # 确保 timestamp 在第一列 (可选，为了好看)
        cols = ["timestamp"] + [c for c in final_df.columns if c != "timestamp"]
        
        # 过滤多余的档位 (如果配置只保存 20 档)
        if TARGET_DEPTH_LEVEL < SOURCE_DEPTH_LEVEL:
            valid_cols = {"timestamp"}
            for i in range(1, TARGET_DEPTH_LEVEL + 1):
                valid_cols.update([f"ask{i}_p", f"ask{i}_q", f"bid{i}_p", f"bid{i}_q"])
            cols = [c for c in cols if c in valid_cols]
            
        final_df = final_df[cols]
        
        # 构建输出路径
        save_dir = OUTPUT_ROOT / clean_symbol / date_str
        save_dir.mkdir(parents=True, exist_ok=True)
        save_file = save_dir / "depth.parquet"
        
        # 保存
        final_df.to_parquet(save_file, compression="snappy")
        
    print(f"✅ {clean_symbol} 处理完成。")

def main():
    if not ZIP_PATH.exists():
        print(f"❌ 找不到文件: {ZIP_PATH}")
        return

    print(f"📂 开始解压并处理: {ZIP_PATH}")
    
    with zipfile.ZipFile(ZIP_PATH, 'r') as zip_ref:
        # 获取所有 CSV 文件列表
        csv_files = [f for f in zip_ref.namelist() if f.endswith('.csv')]
        print(f"   发现 {len(csv_files)} 个 CSV 文件。")
        
        for file_name in csv_files:
            # 检查是否已经处理过 (简单检查目录是否存在)
            # 这里先不做跳过逻辑，因为可能需要覆盖
            
            # 解压单个文件到临时目录
            print(f"   正在解压 {file_name} ...")
            zip_ref.extract(file_name, TEMP_DIR)
            
            # 处理
            extracted_path = TEMP_DIR / file_name
            process_single_csv(extracted_path)
            
            # 删除临时文件以释放空间
            extracted_path.unlink()
            
    # 清理临时目录
    try:
        TEMP_DIR.rmdir()
    except:
        pass
        
    print("\n🎉 所有数据转换完成！")
    print(f"数据位置: {OUTPUT_ROOT}")

if __name__ == "__main__":
    main()
