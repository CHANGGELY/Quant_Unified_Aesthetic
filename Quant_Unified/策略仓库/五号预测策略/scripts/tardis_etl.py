#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Tardis 数据 ETL 脚本 (高兼容版)
功能：使用 requests 下载增量 L2 数据，并使用 Polars 进行极致压缩转换。
"""

import os
import glob
import logging
import polars as pl
import requests
from datetime import datetime, timedelta
import argparse

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === ⚙️ 核心配置区域 ===
TARGET_SYMBOLS = ['BTCUSDT', 'ETHUSDT']
# 精确的起始日期配置 (来源于 Tardis API)
SYMBOL_START_DATES = {
    'BTCUSDT': '2019-11-17',
    'ETHUSDT': '2019-11-27'
}
EXCHANGE = 'binance-futures'
DOWNLOAD_DIR = './tardis_temp'
OUTPUT_DIR = './final_parquet'

# 精度控制
PRICE_MULT = 100  
AMOUNT_MULT = 1000 

def get_monthly_first_days(start_date_str: str) -> list[str]:
    start_date = datetime.strptime(start_date_str[:10], "%Y-%m-%d")
    end_date = datetime.now()
    dates = []
    curr = start_date.replace(day=1)
    if curr < start_date:
        if curr.month == 12: curr = curr.replace(year=curr.year+1, month=1)
        else: curr = curr.replace(month=curr.month+1)
    while curr <= end_date:
        dates.append(curr.strftime("%Y-%m-%d"))
        if curr.month == 12: curr = curr.replace(year=curr.year+1, month=1)
        else: curr = curr.replace(month=curr.month+1)
    return dates

def download_file(url: str, dest_path: str, max_retries: int = 5):
    """使用 requests 下载文件，支持禁用 SSL 校验和重试"""
    import time
    
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"开始下载 (尝试 {attempt}/{max_retries}): {url}")
            # verify=False 彻底解决证书问题
            with requests.get(url, stream=True, timeout=300, verify=False) as r:
                r.raise_for_status()
                with open(dest_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024*1024):
                        if chunk: f.write(chunk)
            return True
        except Exception as e:
            wait_time = 2 ** attempt # 指数退避: 2, 4, 8, 16, 32 秒
            logger.warning(f"下载失败 (尝试 {attempt}/{max_retries}): {e} | 等待 {wait_time}s 后重试...")
            if attempt < max_retries:
                time.sleep(wait_time)
            else:
                logger.error(f"❌ 最终下载失败: {url}")
                return False
    return False

def process_and_compress(csv_path: str, symbol: str, date: str):
    output_filename = f"{symbol}_{date}_incremental.parquet"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    
    if os.path.exists(output_path):
        logger.info(f"✅ {output_filename} 已存在，跳过。")
        if os.path.exists(csv_path): os.remove(csv_path)
        return

    logger.info(f"🔄 正在转换压缩: {symbol} - {date} ...")
    try:
        # 显式指定 schema 以避免类型推断错误，Tardis CSV 的 timestamp 通常是 i64 (微秒)
        # 但有时也可能是 ISO 字符串，所以我们先不强制 schema，而是在表达式里处理
        q = pl.scan_csv(csv_path)

        # 2. 极致压缩转换逻辑
        # 兼容处理：如果 timestamp 已经是数字，直接 cast 为 Datetime；如果是字符串，先转 Datetime
        # Polars 的 cast(pl.Datetime("us")) 对 i64 (微秒) 是直接生效的
        
        df = q.with_columns([
            # 先统一尝试转为 Int64 (微秒)，如果原本是 String 格式的数字也能转
            # 如果是 ISO 字符串，pl.col("timestamp").cast(pl.Int64) 可能会失败，
            # 但 Tardis 的 incremental_book_L2 默认确实是微秒整数
            pl.col("timestamp").cast(pl.Int64).cast(pl.Datetime("us")),
            pl.col("local_timestamp").cast(pl.Int64).cast(pl.Datetime("us")),
            
            # 文本压缩：重复的 symbol/side 转分类编码
            pl.col("symbol").cast(pl.Categorical),
            pl.col("side").cast(pl.Categorical),
            pl.col("is_snapshot").cast(pl.Boolean),

            # 核心：Float 转 Int (提升压缩率)
            (pl.col("price") * PRICE_MULT).round(0).cast(pl.Int64).alias("price_int"),
            (pl.col("amount") * AMOUNT_MULT).round(0).cast(pl.Int64).alias("amount_int")
        ]).select([
            # 只保留需要的列
            "symbol", "timestamp", "local_timestamp", "is_snapshot", "side", "price_int", "amount_int"
        ]).collect()

        df.write_parquet(output_path, compression='zstd', compression_level=10, use_pyarrow=True)
        
        raw_size = os.path.getsize(csv_path) / (1024*1024)
        pq_size = os.path.getsize(output_path) / (1024*1024)
        logger.info(f"🎉 完成! {raw_size:.1f}MB -> {pq_size:.1f}MB (压缩率: {pq_size/raw_size:.1%})")
        os.remove(csv_path)
    except Exception as e:
        logger.error(f"❌ 处理出错: {e}")

def process_task(task_info):
    """单个任务的处理逻辑：下载 -> 转换"""
    symbol, date, output_dir, download_dir = task_info
    
    # 构造路径
    final_path = os.path.join(output_dir, f"{symbol}_{date}_incremental.parquet")
    if os.path.exists(final_path):
        return f"✅ {symbol} {date} 已完成"

    yyyy, mm, dd = date.split('-')
    url = f"https://datasets.tardis.dev/v1/{EXCHANGE}/incremental_book_L2/{yyyy}/{mm}/{dd}/{symbol}.csv.gz"
    dest_csv = os.path.join(download_dir, f"{symbol}_{date}.csv.gz")

    # 下载
    if download_file(url, dest_csv):
        # 转换
        try:
            process_and_compress(dest_csv, symbol, date)
            return f"🎉 完成 {symbol} {date}"
        except Exception as e:
            return f"❌ 转换失败 {symbol} {date}: {e}"
    else:
        return f"❌ 下载失败 {symbol} {date}"

def main():
    global DOWNLOAD_DIR, OUTPUT_DIR
    parser = argparse.ArgumentParser(description='Tardis Data ETL Tool')
    parser.add_argument('--symbols', nargs='+', default=TARGET_SYMBOLS)
    parser.add_argument('--download_dir', default=DOWNLOAD_DIR)
    parser.add_argument('--output_dir', default=OUTPUT_DIR)
    # 新增并发参数
    parser.add_argument('--workers', type=int, default=4, help='并发下载数量')
    args = parser.parse_args()

    os.makedirs(args.download_dir, exist_ok=True)
    os.makedirs(args.output_dir, exist_ok=True)
    
    DOWNLOAD_DIR = args.download_dir
    OUTPUT_DIR = args.output_dir

    # 1. 生成任务列表
    tasks = []
    for symbol in args.symbols:
        start_date = SYMBOL_START_DATES.get(symbol, "2020-01-01")
        target_dates = get_monthly_first_days(start_date)
        for date in target_dates:
            tasks.append((symbol, date, OUTPUT_DIR, DOWNLOAD_DIR))
            
    total = len(tasks)
    logger.info(f"🚀 启动并行模式，Workers={args.workers}，总任务数: {total}")

    # 2. 并行执行
    # 使用 ThreadPoolExecutor 进行并发下载
    # 注意：虽然是多线程，但 process_and_compress 里的 Polars 运算会释放 GIL，所以也能利用多核
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        # 提交所有任务
        future_to_task = {executor.submit(process_task, t): t for t in tasks}
        
        completed_count = 0
        for future in as_completed(future_to_task):
            completed_count += 1
            res = future.result()
            progress = completed_count / total
            logger.info(f"[{completed_count}/{total} | {progress:.1%}] {res}")

if __name__ == "__main__":
    # 禁用警告
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()