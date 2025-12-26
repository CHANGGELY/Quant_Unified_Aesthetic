import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import time
from pytz import timezone
import yaml

from 策略仓库.二号网格策略.api.binance import fetch_candle_data

class BacktestEngine:
    def __init__(self, config_path="config.yaml"):
        self.config = self._load_config(config_path)
        self.strategy = None
        self.df = pd.DataFrame()

    def _load_config(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def set_strategy(self, strategy):
        self.strategy = strategy

    def load_data(self):
        """
        Loads data based on configuration.
        Consolidated logic from previous _load_local_candles and _fetch_online_candles_chunked.
        """
        local_path = self.config['backtest'].get('local_data_path')
        data_center_dir = self.config['backtest'].get('data_center_dir')
        symbol = self.config['backtest']['symbol']
        start_time_str = self.config['backtest']['start_time']
        end_time_str = self.config['backtest']['end_time']
        tz_str = self.config['backtest'].get('timezone', 'Asia/Shanghai')
        num_hours = self.config['backtest'].get('num_hours', 0)
        
        tz = timezone(tz_str)
        try:
             end_time = tz.localize(datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
             # Try parsing without seconds if it fails
             end_time = tz.localize(datetime.strptime(end_time_str, "%Y-%m-%d %H:%M"))

        if num_hours and num_hours > 0:
            # 懒人模式：使用 num_hours 推算起始时间
            num_kline = int(num_hours * 60)
            print(f"启用懒人模式: 回测时长 {num_hours} 小时 (截止时间: {end_time})")
        else:
            # 精确模式：使用 start_time 计算 num_kline
            try:
                start_time = tz.localize(datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                start_time = tz.localize(datetime.strptime(start_time_str, "%Y-%m-%d %H:%M"))
            
            delta_minutes = int((end_time - start_time).total_seconds() / 60)
            num_kline = max(1, delta_minutes)
            print(f"启用精确模式: {start_time} 至 {end_time} (共 {num_kline} 分钟)")
        
        # 1. Try loading specific local file
        df = self._try_load_file(local_path, symbol, end_time, num_kline)
        if not df.empty and self._check_data_integrity(df, end_time, num_kline):
             print(f"使用指定本地文件: {local_path}")
             self.df = df
             return

        # 2. Try searching in data center
        candidates = self._find_in_data_center(data_center_dir, symbol)
        for cand in candidates:
             df = self._try_load_file(cand, symbol, end_time, num_kline)
             if not df.empty and self._check_data_integrity(df, end_time, num_kline):
                 print(f"使用数据中心文件: {cand}")
                 self.df = df
                 return

        # 3. Fetch online
        print("本地数据未完整覆盖，开始线上抓取...")
        self.df = self._fetch_online_candles_chunked(symbol, end_time, num_kline)
        # Save fetched data
        if not self.df.empty:
             self._save_candles_to_local(self.df, data_center_dir, symbol)

    def _try_load_file(self, file_path, symbol, end_time, num_kline):
        if not file_path:
            return pd.DataFrame()
        p = Path(file_path)
        if not p.exists():
            return pd.DataFrame()
        
        try:
            if p.suffix == ".h5":
                try:
                    df = pd.read_hdf(p, key="table")
                except:
                    from pandas import HDFStore
                    with HDFStore(p, mode="r") as store:
                        keys = store.keys()
                        if not keys: return pd.DataFrame()
                        df = store[keys[0]]
            elif p.suffix == ".csv":
                df = pd.read_csv(p)
            else:
                return pd.DataFrame()
            
            if "symbol" in df.columns:
                df = df[df["symbol"] == symbol]
            
            # Normalize column names
            col_map = {"open_time": "candle_begin_time", "datetime": "candle_begin_time", "date": "candle_begin_time"}
            df.rename(columns=col_map, inplace=True)
            
            if "candle_begin_time" not in df.columns:
                return pd.DataFrame()
                
            for c in ["open","high","low","close"]:
                if c in df.columns:
                    df[c] = df[c].astype(float)
            
            # Timezone handling
            utc_offset = int(time.localtime().tm_gmtoff / 3600)
            cbt = df["candle_begin_time"]
            if pd.api.types.is_numeric_dtype(cbt):
                df["candle_begin_time"] = pd.to_datetime(cbt, unit="ms") + timedelta(hours=utc_offset)
            else:
                df["candle_begin_time"] = pd.to_datetime(cbt)
            
            df.sort_values("candle_begin_time", inplace=True)
            df.drop_duplicates("candle_begin_time", keep="last", inplace=True)
            df = df[df["candle_begin_time"] <= end_time]
            return df.tail(num_kline).reset_index(drop=True)
        except Exception as e:
            return pd.DataFrame()

    def _check_data_integrity(self, df, end_time, num_kline):
        if len(df) < num_kline:
            return False
        
        window_end_naive = pd.to_datetime(end_time).tz_localize(None)
        window_start_naive = window_end_naive - pd.to_timedelta(f"{num_kline-1}m")
        
        df_times = pd.to_datetime(df['candle_begin_time']).dt.tz_localize(None) if df['candle_begin_time'].dt.tz is not None else pd.to_datetime(df['candle_begin_time'])
        
        mask = (df_times >= window_start_naive) & (df_times <= window_end_naive)
        window_df = df.loc[mask]
        
        expected = pd.date_range(window_start_naive, window_end_naive, freq='1min')
        present = pd.DatetimeIndex(window_df['candle_begin_time'])
        missing = expected.difference(present)
        
        return len(missing) == 0 and len(window_df) >= num_kline

    def _find_in_data_center(self, data_center_dir, symbol):
        base = Path(data_center_dir)
        if not base.exists():
            return []
        candidates = list(base.glob(f"{symbol}_1m_*.csv")) + list(base.glob(f"{symbol}_1m_*.h5"))
        # Sort logic (simplified for brevity, assume similar to original)
        return [str(p) for p in candidates]

    def _fetch_online_candles_chunked(self, symbol, end_time, num_kline):
        total = num_kline
        chunk = 1500
        dfs = []
        minutes = pd.to_timedelta('1m')
        fetched = 0
        while fetched < total:
            need = min(chunk, total - fetched)
            e = end_time - minutes * fetched
            df = fetch_candle_data(symbol, e, '1m', need)
            if df is None or len(df) == 0:
                break
            dfs.append(df)
            fetched += need
        if not dfs:
            return pd.DataFrame()
        df = pd.concat(dfs, ignore_index=True)
        df.sort_values(by=['candle_begin_time'], inplace=True)
        df.drop_duplicates(subset=['candle_begin_time'], keep='last', inplace=True)
        return df.tail(num_kline).reset_index(drop=True)

    def _save_candles_to_local(self, df, data_center_dir, symbol):
        try:
            base = Path(data_center_dir)
            base.mkdir(parents=True, exist_ok=True)
            start = pd.to_datetime(df['candle_begin_time'].iloc[0])
            end = pd.to_datetime(df['candle_begin_time'].iloc[-1])
            name = f"{symbol}_1m_{start.strftime('%Y-%m-%d_%H-%M')}_to_{end.strftime('%Y-%m-%d_%H-%M')}.csv"
            df.to_csv(base / name, index=False)
            print(f'已保存到数据中心 {base / name}')
        except:
            pass

    def run(self):
        if self.strategy is None:
            raise ValueError("Strategy not set")
        
        self.load_data()
        if self.df.empty:
            print("未获取到数据，无法回测")
            return

        # Initialize strategy with first price
        self.strategy.on_tick(self.df['candle_begin_time'].iloc[0], self.df['open'].iloc[0])
        self.strategy.init() # Call custom init if needed

        for index, row in self.df.iterrows():
            ts = row['candle_begin_time']
            # OHLC Simulation
            self.strategy.on_tick(ts, row['open'])
            
            if row['close'] < row['open']:
                self.strategy.on_tick(ts, row['high'])
                self.strategy.on_tick(ts, row['low'])
            else:
                self.strategy.on_tick(ts, row['low'])
                self.strategy.on_tick(ts, row['high'])
                
            self.strategy.on_tick(ts, row['close'])
            self.strategy.on_bar(row)

        self.print_metrics()

    def print_metrics(self):
        # Assuming strategy has account_dict and money
        if not hasattr(self.strategy, 'account_dict') or not hasattr(self.strategy, 'money'):
            return
            
        acc = self.strategy.account_dict
        money = self.strategy.money
        
        pl_pair = acc.get("pair_profit", 0)
        pl_pos = acc.get("positions_profit", 0)
        pl_total = pl_pair + pl_pos
        
        print("-" * 30)
        print(f"回测结果摘要")
        print(f"初始资金: {money}")
        print(f"最大盈利: {getattr(self.strategy, 'max_profit', 0)}")
        print(f"最大亏损: {getattr(self.strategy, 'max_loss', 0)}")
        print(f"配对次数: {acc.get('pairing_count', 0)}")
        print(f"已配对利润: {pl_pair:.2f} ({pl_pair/money*100:.1f}%)")
        print(f"持仓盈亏: {pl_pos:.2f} ({pl_pos/money*100:.1f}%)")
        print(f"总收益: {pl_total:.2f} ({pl_total/money*100:.1f}%)")
        
        # APR Calculation
        start_time = pd.to_datetime(self.df['candle_begin_time'].iloc[0])
        end_time = pd.to_datetime(self.df['candle_begin_time'].iloc[-1])
        duration_hours = max(0.001, (end_time - start_time).total_seconds() / 3600)
        duration_days = duration_hours / 24
        
        roi = pl_total / money
        apr_linear = roi * (365 * 24 / duration_hours)
        apr_compound = ((1 + roi) ** (365 * 24 / duration_hours)) - 1
        
        daily_pairings = acc.get("pairing_count", 0) / max(duration_days, 0.001)
        
        print(f"回测时长: {duration_hours:.2f} 小时")
        print(f"日均配对: {daily_pairings:.2f}")
        print(f"线性年化: {apr_linear*100:.1f}%")
        print(f"复利年化: {apr_compound*100:.1f}%")
        
        shift_up = getattr(self.strategy, 'upward_shift_count', 0)
        shift_down = getattr(self.strategy, 'downward_shift_count', 0)
        print(f"移动统计: 上移 {shift_up} / 下移 {shift_down} (总计 {shift_up+shift_down})")
