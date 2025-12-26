"""
Quant Unified 量化交易系统
[数据准备脚本]
功能：负责读取历史 CSV/Parquet 数据，清洗格式，对齐时间戳，为回测提供标准输入。
"""
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import time
from pytz import timezone

# 导入配置
from 策略仓库.二号网格策略.config import Config
from 策略仓库.二号网格策略.api.binance import fetch_candle_data

def fetch_and_save_data(conf: Config, start_dt, end_dt):
    print(f"🌍 开始从币安获取数据: {conf.symbol} ({start_dt} - {end_dt})")
    
    symbol = conf.symbol
    interval = conf.candle_period if hasattr(conf, 'candle_period') else '1m'
    
    # 计算需要获取的总时长
    total_duration = end_dt - start_dt
    
    # 分块获取，每次 1000 条
    limit = 1000
    dfs = []
    
    # 从后往前获取
    current_end = end_dt
    
    while current_end > start_dt:
        print(f"  ⬇️  下载进度: {current_end} (剩余 {max(0, int((current_end - start_dt).total_seconds()/60))} 分钟)")
        try:
            df_chunk = fetch_candle_data(symbol, current_end, interval, limit)
        except Exception as e:
            print(f"  ⚠️  API请求失败: {e}")
            break

        if df_chunk.empty:
            print("  ⚠️  获取到空数据，停止下载")
            break
            
        # 统一时间格式
        if 'candle_begin_time' in df_chunk.columns:
             if pd.api.types.is_float_dtype(df_chunk['candle_begin_time']) or pd.api.types.is_integer_dtype(df_chunk['candle_begin_time']):
                 df_chunk['candle_begin_time'] = pd.to_datetime(df_chunk['candle_begin_time'], unit='ms')
        
        # Adjust timezone (UTC -> UTC+8)
        # Assuming fetch_candle_data returns UTC timestamps (Binance API default)
        # We need to add 8 hours to match Asia/Shanghai if not already handled
        # But let's check if fetch_candle_data already handles it?
        # api/binance.py uses ccxt. fetch_ohlcv returns UTC timestamps.
        # So yes, add 8 hours for local display/usage if the system expects local time.
        # However, pandas timezone handling is tricky.
        # Let's add 8 hours to be safe as per previous code convention.
        df_chunk['candle_begin_time'] = df_chunk['candle_begin_time'] + timedelta(hours=8)

        dfs.append(df_chunk)
        
        # Update current_end to the start of the earliest candle fetched
        min_time = df_chunk['candle_begin_time'].min()
        if min_time >= current_end:
             print("  ⚠️  数据时间未推进，停止下载")
             break
        current_end = min_time
        
        if min_time <= start_dt:
            break
            
        time.sleep(0.1) # Rate limit protection

    if not dfs:
        return pd.DataFrame()
        
    # 合并数据
    df_all = pd.concat(dfs, ignore_index=True)
    df_all.sort_values('candle_begin_time', inplace=True)
    df_all.drop_duplicates('candle_begin_time', inplace=True)
    
    # 再次过滤精确范围
    mask = (df_all['candle_begin_time'] >= start_dt) & (df_all['candle_begin_time'] <= end_dt)
    df_final = df_all.loc[mask].copy()
    
    print(f"✅ 下载完成: {len(df_final)} 条数据")
    
    # 保存到本地
    save_path = Path(conf.data_center_dir)
    save_path.mkdir(parents=True, exist_ok=True)
    file_name = f"{conf.symbol}.csv"
    full_path = save_path / file_name
    
    # 如果文件已存在，尝试合并
    if full_path.exists():
        print(f"  💾 合并至现有文件: {full_path}")
        try:
            # 简单追加模式：读取旧数据，合并新数据，去重
            # 注意编码问题
            try:
                df_old = pd.read_csv(full_path, encoding='utf-8')
            except:
                df_old = pd.read_csv(full_path, encoding='gbk')
            
            # 标准化列名 (如果旧文件列名不同，这里可能需要更多处理，暂假设标准格式)
            col_map = {
                "open_time": "candle_begin_time", 
                "datetime": "candle_begin_time", 
                "date": "candle_begin_time",
                "Open": "open", "High": "high", "Low": "low", "Close": "close"
            }
            df_old.rename(columns=col_map, inplace=True)
            
            # 确保时间列格式
            if 'candle_begin_time' in df_old.columns:
                df_old['candle_begin_time'] = pd.to_datetime(df_old['candle_begin_time'])
                
            # 合并
            df_final = pd.concat([df_old, df_final], ignore_index=True)
            df_final.drop_duplicates('candle_begin_time', inplace=True)
            df_final.sort_values('candle_begin_time', inplace=True)
            
        except Exception as e:
            print(f"  ⚠️ 合并失败，将覆盖文件: {e}")
            pass
            
    print(f"  💾 保存文件: {full_path}")
    df_final.to_csv(full_path, index=False)
    
    return df_final

def prepare_data(conf: Config):
    """
    标准化数据准备函数
    读取CSV文件，清洗数据，并返回准备好进行回测的DataFrame
    """
    print(f"🌀 正在加载数据: {conf.symbol}...")
    
    data_dir = Path(conf.data_center_dir)
    df = pd.DataFrame()
    
    if not data_dir.exists():
        print(f"❌ 数据目录不存在: {data_dir}")
        candidates = []
    else:
        # Search for the symbol file
        candidates = list(data_dir.rglob(f"{conf.symbol}.csv"))
        
        if not candidates:
            print(f"❌ 未找到交易对数据: {conf.symbol}")
            # Try finding without USDT suffix if not present
            if "USDT" in conf.symbol:
                base_symbol = conf.symbol.replace("USDT", "")
                period_suffix = f"-{conf.candle_period}" if hasattr(conf, 'candle_period') else ""
                
                # 尝试1: 优先查找带周期的文件名
                if period_suffix:
                    candidates = list(data_dir.rglob(f"{base_symbol}-USDT{period_suffix}.csv"))
                
                # 尝试2: 标准格式 {base_symbol}-USDT.csv
                if not candidates:
                    candidates = list(data_dir.rglob(f"{base_symbol}-USDT.csv"))
    
    if candidates:
        file_path = candidates[0]
        print(f"✅ 找到数据文件: {file_path}")
        
        try:
            try:
                # 尝试读取 CSV (默认认为第一行是标题，不跳过)
                df = pd.read_csv(file_path, encoding='utf-8')
            except UnicodeDecodeError:
                print("⚠️ UTF-8读取失败，尝试GBK编码...")
                df = pd.read_csv(file_path, encoding='gbk')
            
            # Standardize columns
            col_map = {
                "open_time": "candle_begin_time", 
                "datetime": "candle_begin_time", 
                "date": "candle_begin_time",
                "Open": "open", "High": "high", "Low": "low", "Close": "close"
            }
            df.rename(columns=col_map, inplace=True)
            
            # Ensure numeric
            for c in ["open", "high", "low", "close"]:
                if c in df.columns:
                    df[c] = df[c].astype(float)
                    
            # Timezone handling
            if "candle_begin_time" in df.columns:
                first_val = df["candle_begin_time"].iloc[0]
                if isinstance(first_val, (int, float)) or (isinstance(first_val, str) and first_val.isdigit()):
                     utc_offset = 8 
                     df["candle_begin_time"] = pd.to_datetime(df["candle_begin_time"], unit="ms") + timedelta(hours=utc_offset)
                else:
                     df["candle_begin_time"] = pd.to_datetime(df["candle_begin_time"])
            
            df.sort_values("candle_begin_time", inplace=True)
            
            # Filter time range
            tz = timezone(conf.timezone)
            end_dt = pd.to_datetime(conf.end_time)
            
            # num_hours 优先级处理逻辑
            if hasattr(conf, 'num_hours') and conf.num_hours > 0:
                print(f"🕒 启用懒人模式: 结束时间={end_dt}, 回溯 {conf.num_hours} 小时")
                start_dt = end_dt - timedelta(hours=conf.num_hours)
            else:
                if hasattr(conf, 'start_time'):
                    start_dt = pd.to_datetime(conf.start_time)
                    print(f"🕒 启用精确模式: {start_dt} 至 {end_dt}")
                else:
                    start_dt = end_dt - timedelta(days=30)
                    print(f"🕒 未指定开始时间，默认回溯 30 天: {start_dt} 至 {end_dt}")
            
            # Make naive if df is naive
            if df["candle_begin_time"].dt.tz is not None:
                 df["candle_begin_time"] = df["candle_begin_time"].dt.tz_localize(None)
                 
            df = df[(df["candle_begin_time"] >= start_dt) & (df["candle_begin_time"] <= end_dt)]
            
            # 重采样处理
            if hasattr(conf, 'candle_period') and conf.candle_period != "1m":
                print(f"🔄 正在重采样数据至 {conf.candle_period}...")
                df.set_index('candle_begin_time', inplace=True)
                
                agg_dict = {
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                }
                if 'volume' in df.columns:
                    agg_dict['volume'] = 'sum'
                if 'quote_volume' in df.columns:
                    agg_dict['quote_volume'] = 'sum'
                    
                df_resampled = df.resample(conf.candle_period).agg(agg_dict)
                df_resampled.dropna(inplace=True)
                df = df_resampled.reset_index()
                print(f"✅ 重采样完成，新数据量: {len(df)} 条")

            print(f"✅ 数据加载完成，共 {len(df)} 条K线")
            
        except Exception as e:
            print(f"❌ 数据读取失败: {e}")
            df = pd.DataFrame()

    # 自动下载逻辑
    if df.empty:
        print("⚠️ 本地数据为空或未找到，尝试自动下载...")
        # 重新计算时间范围 (需要再次计算，因为上面可能是在 try 块里计算的)
        tz = timezone(conf.timezone)
        end_dt = pd.to_datetime(conf.end_time)
        if hasattr(conf, 'num_hours') and conf.num_hours > 0:
            start_dt = end_dt - timedelta(hours=conf.num_hours)
        else:
            if hasattr(conf, 'start_time'):
                start_dt = pd.to_datetime(conf.start_time)
            else:
                start_dt = end_dt - timedelta(days=30)
        
        df = fetch_and_save_data(conf, start_dt, end_dt)
        return df

    return df.reset_index(drop=True)
