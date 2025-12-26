import ccxt
import pandas as pd
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import os

# Configuration
SYMBOL = 'ETH/USDT'
START_DATE = '2021-01-01 00:00:00'
END_DATE = '2025-12-12 00:00:00'
TIMEFRAME = '1m'
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), '策略仓库', '二号网格策略', 'data_center', 'ETHUSDT.csv')
MAX_WORKERS = 8  # Conservative worker count

def download_chunk(exchange_id, symbol, start_ts, end_ts):
    try:
        # Create a new exchange instance for each thread to avoid SSL/socket issues
        exchange = getattr(ccxt, exchange_id)({
            'enableRateLimit': True,
            'options': {'defaultType': 'future'} # Contract trading
        })
        
        all_ohlcv = []
        current_since = start_ts
        
        while current_since < end_ts:
            try:
                # Binance futures allows up to 1500 candles
                ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, since=current_since, limit=1500)
                if not ohlcv:
                    break
                
                all_ohlcv.extend(ohlcv)
                
                last_ts = ohlcv[-1][0]
                # If we got fewer than requested, we might be at the end of data or range
                if len(ohlcv) < 1500:
                    # But wait, we might just be at the "current" end of data, but we want to reach end_ts
                    # If last_ts >= end_ts, we are done
                    pass
                
                current_since = last_ts + 60000 # +1 min
                
                if current_since >= end_ts:
                    break
                    
                # Small sleep to be nice to the API
                time.sleep(0.1)
                    
            except Exception as e:
                print(f"  ⚠️ Error in chunk {start_ts}: {e}")
                time.sleep(2)
                continue
                
        return all_ohlcv
    except Exception as e:
        print(f"  ❌ Critical error in thread: {e}")
        return []

def main():
    print(f"🚀 启动极速并行下载: {SYMBOL} ({START_DATE} - {END_DATE})")
    
    start_dt = pd.to_datetime(START_DATE)
    end_dt = pd.to_datetime(END_DATE)
    
    # Split into chunks (e.g., 60 days per chunk)
    chunks = []
    curr = start_dt
    chunk_size_days = 60
    
    while curr < end_dt:
        next_chunk = curr + timedelta(days=chunk_size_days)
        if next_chunk > end_dt:
            next_chunk = end_dt
        chunks.append((curr, next_chunk))
        curr = next_chunk
        
    print(f"📦 任务拆分: 共 {len(chunks)} 个数据块，使用 {MAX_WORKERS} 个线程并行下载...")
    
    all_data = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for s, e in chunks:
            s_ts = int(s.timestamp() * 1000)
            e_ts = int(e.timestamp() * 1000)
            futures.append(executor.submit(download_chunk, 'binance', SYMBOL, s_ts, e_ts))
            
        completed = 0
        for future in as_completed(futures):
            res = future.result()
            all_data.extend(res)
            completed += 1
            print(f"  ✅ 进度: {completed}/{len(chunks)} 块完成 (当前累计 {len(all_data)} 条)")

    if not all_data:
        print("❌ 未下载到任何数据")
        return

    # Process DataFrame
    print("🔄 正在处理数据合并与去重...")
    df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # Drop duplicates and sort
    df.drop_duplicates(subset='timestamp', inplace=True)
    df.sort_values('timestamp', inplace=True)
    
    # Filter exact range
    start_ts_final = int(start_dt.timestamp() * 1000)
    end_ts_final = int(end_dt.timestamp() * 1000)
    df = df[(df['timestamp'] >= start_ts_final) & (df['timestamp'] <= end_ts_final)]
    
    # Format: UTC+8
    df['candle_begin_time'] = pd.to_datetime(df['timestamp'], unit='ms') + timedelta(hours=8)
    
    # Select and rename columns
    final_df = df[['candle_begin_time', 'open', 'high', 'low', 'close', 'volume']].copy()
    
    # Save
    save_path = Path(OUTPUT_FILE)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    final_df.to_csv(save_path, index=False)
    print(f"🎉 数据下载完成！已保存 {len(final_df)} 条K线至 {save_path}")
    print(f"📅 数据范围: {final_df['candle_begin_time'].min()} -> {final_df['candle_begin_time'].max()}")

if __name__ == "__main__":
    main()
