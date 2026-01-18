#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Tardis 数据加载适配器
功能：读取压缩的 Parquet 数据，驱动 L2 重放引擎，并生成固定频率的特征快照。

重要说明：
    这里我们刻意使用 `pyarrow`（Apache Arrow 的 Python 实现）来读 Parquet：
    - 好处：依赖更少、兼容性更强（尤其是新版本 Python）
    - 也能流式（batch）读取，避免一次性把整天数据全塞进内存
"""

import os
import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.compute as pc
import numpy as np
from pathlib import Path
from typing import Generator, Any
import logging
from 基础库.common_core.utils.orderbook_replay import OrderBook
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

        # 2) 流式读取 Parquet（按 batch 遍历）
        pf = pq.ParquetFile(l2_file)

        # 3) 重放循环（按固定间隔产出快照）
        next_snapshot_ts = None
        interval_us = self.cfg.sample_interval_ms * 1000 # 转微秒
        
        count = 0
        batch_size = int(os.getenv("PREDICT5_TARDIS_BATCH_SIZE", "200000") or "200000")

        for batch in pf.iter_batches(batch_size=batch_size, columns=["side", "price_int", "amount_int", "timestamp"]):
            # side 是 DictionaryArray（字典编码），用 indices + dictionary 可以少分配很多字符串对象
            side_arr = batch.column(0)
            if isinstance(side_arr, pa.DictionaryArray):
                side_dict = side_arr.dictionary.to_pylist()
                side_idx = side_arr.indices.to_numpy(zero_copy_only=False)
            else:
                side_dict = []
                side_idx = None
                side_np = side_arr.to_numpy(zero_copy_only=False)

            price_np = batch.column(1).to_numpy(zero_copy_only=False)
            amount_np = batch.column(2).to_numpy(zero_copy_only=False)
            ts_np = pc.cast(batch.column(3), pa.int64()).to_numpy(zero_copy_only=False)

            if next_snapshot_ts is None and len(ts_np) > 0:
                current_ts = int(ts_np[0])
                next_snapshot_ts = int((current_ts // interval_us + 1) * interval_us)

            for i in range(len(ts_np)):
                ts = int(ts_np[i])

                # 如果时间戳跨越了快照点，生成快照（使用“当前订单簿状态”，不包含本条 delta）
                while next_snapshot_ts is not None and ts >= next_snapshot_ts:
                    snapshot = self.ob.get_flat_snapshot(depth=self.cfg.depth_levels)
                    snapshot["timestamp"] = int(next_snapshot_ts)
                    snapshot["symbol"] = self.cfg.symbol
                    self._restore_precision(snapshot)
                    yield snapshot

                    next_snapshot_ts += interval_us
                    count += 1

                if side_idx is not None:
                    side = side_dict[int(side_idx[i])]
                else:
                    side = side_np[i]
                p_int = int(price_np[i])
                a_int = int(amount_np[i])
                self.ob.apply_delta(str(side), p_int, a_int)
            
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
