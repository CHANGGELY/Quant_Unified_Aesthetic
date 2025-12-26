#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Tardis 数据加载适配器
功能：读取压缩的 Parquet 数据，驱动 L2 重放引擎，并生成固定频率的特征快照。
"""

import polars as pl
import numpy as np
from pathlib import Path
from typing import Generator, Any
import logging
from Quant_Unified.基础库.common_core.utils.orderbook_replay import OrderBook
from .config import Config

logger = logging.getLogger(__name__)

class TardisDataLoader:
    def __init__(self, config: Config):
        self.cfg = config
        self.ob = OrderBook(config.symbol)
        
    def load_day(self, date_str: str) -> Generator[dict, None, None]:
        """
        加载指定日期的数据，并按配置频率生成快照
        """
        # 1. 构造文件路径
        l2_file = self.cfg.data_root / f"{self.cfg.symbol}_{date_str}_incremental.parquet"
        
        if not l2_file.exists():
            logger.warning(f"数据文件不存在: {l2_file}")
            return

        logger.info(f"正在加载 Tardis 数据: {l2_file}")
        
        # 2. 读取数据 (使用 LazyFrame 优化性能，但此处为了遍历需要 collect)
        # 注意：为了性能，这里我们一次性读入内存（Tardis 单日压缩后仅几百 MB，完全可控）
        # 必须按时间戳严格排序
        df = pl.read_parquet(l2_file).sort("timestamp")
        
        # 3. 准备迭代器
        # 将 DataFrame 转为 Numpy 或 dict 列表以加速遍历
        # 虽然 Polars iter_rows 也不慢，但 Numpy 更快
        rows = df.select([
            "side", "price_int", "amount_int", "timestamp"
        ]).to_numpy()
        
        # 4. 重放循环
        next_snapshot_ts = None
        interval_us = self.cfg.sample_interval_ms * 1000 # 转微秒
        
        # 记录上一帧的时间戳，用于初始化
        if len(rows) > 0:
            current_ts = rows[0][3] # timestamp 是第 4 列
            # 对齐到整刻度
            next_snapshot_ts = (current_ts // interval_us + 1) * interval_us
        
        count = 0
        for row in rows:
            # row: [side_str, price_int, amount_int, timestamp_datetime]
            # 注意：polars 读取 categorical 会转为 str，datetime 会转为 int (微秒) 或 datetime 对象
            # 这里的 numpy 转换可能会让 datetime 变成 int64 (微秒)
            
            side = row[0]
            p_int = row[1]
            a_int = row[2]
            ts = row[3] # 假设是 int64 (微秒)
            
            # 如果时间戳跨越了快照点，生成快照
            while next_snapshot_ts is not None and ts >= next_snapshot_ts:
                # 获取快照
                snapshot = self.ob.get_flat_snapshot(depth=self.cfg.depth_levels)
                # 注入时间戳信息
                snapshot["timestamp"] = next_snapshot_ts
                snapshot["symbol"] = self.cfg.symbol
                
                # 还原价格和数量为真实物理值 (Float)
                # 这一步在生成快照时做，比每一步都做要快得多
                self._restore_precision(snapshot)
                
                yield snapshot
                
                next_snapshot_ts += interval_us
                count += 1
                
            # 应用增量更新
            self.ob.apply_delta(side, p_int, a_int)
            
        logger.info(f"重放完成: {date_str}, 生成快照数: {count}")

    def _restore_precision(self, snapshot: dict):
        """将整数快照还原为浮点数"""
        pm = self.cfg.price_mult
        am = self.cfg.amount_mult
        
        # 遍历字典键，原位修改
        for k, v in snapshot.items():
            if k.endswith("_p"):
                snapshot[k] = v / pm
            elif k.endswith("_q"):
                snapshot[k] = v / am

if __name__ == "__main__":
    # 简单测试
    cfg = Config(symbol="BTCUSDT", data_source="tardis")
    loader = TardisDataLoader(cfg)
    # 假设有一个测试文件
    # for snap in loader.load_day("2024-01-01"):
    #     print(snap)
    #     break
