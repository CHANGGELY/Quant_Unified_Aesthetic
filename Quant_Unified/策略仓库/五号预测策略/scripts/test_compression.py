#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
数据压缩完整性测试
验证 Float -> Int -> Float 的还原精度是否符合预期。
"""

import polars as pl
import os
import numpy as np

# 还原系数
PRICE_MULT = 100.0
AMOUNT_MULT = 1000.0

def test_compression_integrity():
    test_file = "test_sample.csv"
    pq_file = "test_sample.parquet"
    
    # 1. 构造测试数据
    data = {
        "symbol": ["BTCUSDT", "BTCUSDT"],
        "timestamp": ["2024-01-01 00:00:00.123456", "2024-01-01 00:00:00.789012"],
        "local_timestamp": ["2024-01-01 00:00:00.123456", "2024-01-01 00:00:00.789012"],
        "is_snapshot": ["false", "false"],
        "side": ["buy", "sell"],
        "price": [60000.12, 60000.13],
        "amount": [1.234, 0.567]
    }
    df_raw = pl.DataFrame(data)
    df_raw.write_csv(test_file)
    
    print(f"原始数据:\n{df_raw}")

    try:
        # 2. 模拟 ETL 压缩过程
        q = pl.scan_csv(test_file)
        df_compressed = q.with_columns([
            pl.col("timestamp").str.to_datetime().cast(pl.Datetime("us")),
            pl.col("local_timestamp").str.to_datetime().cast(pl.Datetime("us")),
            pl.col("symbol").cast(pl.Categorical),
            pl.col("side").cast(pl.Categorical),
            pl.col("is_snapshot").cast(pl.Boolean),
            (pl.col("price") * PRICE_MULT).round(0).cast(pl.Int64).alias("price_int"),
            (pl.col("amount") * AMOUNT_MULT).round(0).cast(pl.Int64).alias("amount_int")
        ]).select([
            "symbol", "timestamp", "local_timestamp", "is_snapshot", "side", "price_int", "amount_int"
        ]).collect()
        
        df_compressed.write_parquet(pq_file, compression='zstd', compression_level=10)
        
        # 3. 模拟还原过程
        df_read = pl.read_parquet(pq_file)
        df_restored = df_read.with_columns([
            (pl.col("price_int") / PRICE_MULT).alias("price"),
            (pl.col("amount_int") / AMOUNT_MULT).alias("amount")
        ])
        
        print(f"还原数据:\n{df_restored}")

        # 4. 断言验证
        for i in range(len(df_raw)):
            assert abs(df_raw["price"][i] - df_restored["price"][i]) < 1e-8, f"价格不一致: {df_raw['price'][i]} vs {df_restored['price'][i]}"
            assert abs(df_raw["amount"][i] - df_restored["amount"][i]) < 1e-8, f"数量不一致: {df_raw['amount'][i]} vs {df_restored['amount'][i]}"
            
        print("✅ 完整性测试通过！精度损耗在可接受范围内。\n")

    finally:
        # 清理
        if os.path.exists(test_file): os.remove(test_file)
        if os.path.exists(pq_file): os.remove(pq_file)

if __name__ == "__main__":
    test_compression_integrity()
