#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Loader 测试脚本
验证 TardisDataLoader 能否正确读取 Parquet 并生成重放快照。
"""

import sys
import os
from pathlib import Path
import polars as pl
import logging

# 添加项目根目录到路径
sys.path.append(os.getcwd())

from Quant_Unified.策略仓库.五号预测策略.config import Config
from Quant_Unified.策略仓库.五号预测策略.data_loader_tardis import TardisDataLoader

# 配置日志
logging.basicConfig(level=logging.INFO)

def test_loader():
    symbol = "BTCUSDT"
    date_str = "2024-01-01"
    temp_dir = "./temp_test_data"
    os.makedirs(temp_dir, exist_ok=True)
    
    # 1. 创建模拟 Parquet 数据
    # 构造两个时间点的更新，跨越 100ms
    # T0: 0ms
    # T1: 50ms
    # T2: 150ms -> 应该触发 100ms 的快照
    
    base_ts = 1704067200000000 # 2024-01-01 00:00:00 (us)
    
    data = {
        "symbol": [symbol, symbol, symbol],
        "timestamp": [
            base_ts + 0, 
            base_ts + 50000,   # +50ms
            base_ts + 150000   # +150ms (cross 100ms boundary)
        ],
        "local_timestamp": [base_ts]*3,
        "is_snapshot": [False]*3,
        "side": ["buy", "sell", "buy"],
        "price_int": [6000000, 6000100, 5999900], # 60000.00, 60001.00, 59999.00
        "amount_int": [1000, 2000, 500]           # 1.000, 2.000, 0.500
    }
    
    df = pl.DataFrame(data)
    # 强制转换 timestamp 类型以匹配真实数据
    df = df.with_columns(pl.col("timestamp").cast(pl.Int64)) # 微秒本身就是 Int64 存储
    
    pq_path = Path(temp_dir) / f"{symbol}_{date_str}_incremental.parquet"
    df.write_parquet(pq_path)
    
    print(f"模拟数据已写入: {pq_path}")
    
    # 2. 初始化 Loader
    # 临时覆盖 data_root 指向测试目录
    cfg = Config(
        symbol=symbol, 
        data_source="tardis", 
        data_root=Path(temp_dir),
        sample_interval_ms=100 # 100ms
    )
    
    loader = TardisDataLoader(cfg)
    
    # 3. 运行加载
    print("开始加载...")
    snapshots = list(loader.load_day(date_str))
    
    print(f"捕获快照数量: {len(snapshots)}")
    
    # 4. 验证
    # 应该至少有一个快照在 100ms 时刻生成
    # 此时盘口应该包含前两个更新 (T0, T1)，但不包含 T2 (因为它在 150ms)
    
    if len(snapshots) > 0:
        snap = snapshots[0]
        print("快照内容:", snap)
        
        # 验证还原后的价格
        # T0: Buy 60000.00, 1.0
        # T1: Sell 60001.00, 2.0
        
        # 检查 Bid1
        assert snap['bid1_p'] == 60000.0, f"Bid1 Price Error: {snap['bid1_p']}"
        assert snap['bid1_q'] == 1.0, f"Bid1 Qty Error: {snap['bid1_q']}"
        
        # 检查 Ask1
        assert snap['ask1_p'] == 60001.0, f"Ask1 Price Error: {snap['ask1_p']}"
        assert snap['ask1_q'] == 2.0, f"Ask1 Qty Error: {snap['ask1_q']}"
        
        print("✅ 快照验证通过！")
    else:
        print("❌ 未生成快照")

    # 清理
    import shutil
    shutil.rmtree(temp_dir)

if __name__ == "__main__":
    test_loader()
