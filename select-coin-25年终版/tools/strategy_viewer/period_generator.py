"""
邢不行™️选币框架 - 连续交易期间生成器
Python数字货币量化投资课程

版权所有 ©️ 邢不行
微信: xbx8662

基于选币结果生成连续交易期间
"""

import pandas as pd
from typing import Dict, List
from tqdm import tqdm


class PeriodGenerator:
    """连续交易期间生成器"""
    
    def __init__(self, hold_period: str = '9H', kline_period: str = '1h'):
        """
        初始化生成器
        
        Args:
            hold_period: 持仓周期，如 '9H', '1D', '30min'
            kline_period: K线周期，如 '1h', '4h', '1d'
        """
        self.hold_period = hold_period
        # 转为timedelta（pandas支持小写的h/d）
        self.hold_period_td = pd.to_timedelta(hold_period.lower())
        self.kline_period_td = pd.to_timedelta(kline_period.lower())
    
    
    def generate(self, select_results: pd.DataFrame) -> pd.DataFrame:
        """
        生成连续交易期间
        
        核心逻辑：
        1. 按币种分组
        2. 遍历每个币种的选币记录，按时间排序
        3. 判断连续性：如果两次选币时间间隔 <= 持仓周期 * 1.2，视为连续
        4. 将连续的选币合并为一个交易期间
        
        Args:
            select_results: 选币结果 DataFrame
                必须包含列: candle_begin_time, symbol, 方向
        
        Returns:
            交易期间 DataFrame
                列: symbol, direction, entry_time, exit_time, holding_hours,
                    return, max_drawdown, volatility, return_drawdown_ratio
        """
        if select_results.empty:
            print("⚠️ 选币结果为空")
            return pd.DataFrame()
        
        all_periods = []
        
        # 确保时间列为datetime类型
        if 'candle_begin_time' in select_results.columns:
            select_results['candle_begin_time'] = pd.to_datetime(select_results['candle_begin_time'])
        
        # 按币种分组处理
        symbols = select_results['symbol'].unique()
        print(f"📊 处理 {len(symbols)} 个币种的选币记录...")
        
        for symbol in tqdm(symbols, desc="生成交易期间", ncols=80):
            symbol_df = select_results[select_results['symbol'] == symbol].copy()
            symbol_df = symbol_df.sort_values('candle_begin_time')
            
            # 识别该币种的连续选币期间
            periods = self._identify_continuous_periods(symbol, symbol_df)
            all_periods.extend(periods)
        
        if not all_periods:
            print("⚠️ 未识别出任何交易期间")
            return pd.DataFrame()
        
        # 转换为DataFrame
        periods_df = pd.DataFrame(all_periods)
        
        print(f"✅ 识别出 {len(periods_df)} 个连续交易期间")
        
        return periods_df
    
    def _identify_continuous_periods(self, symbol: str, symbol_df: pd.DataFrame) -> List[Dict]:
        """
        识别单个币种的连续交易期间
        
        Args:
            symbol: 币种名称
            symbol_df: 该币种的选币记录（已按时间排序）
            
        Returns:
            交易期间列表
        """
        periods = []
        
        current_start = None  # 当前期间的开始选币时间
        last_time = None      # 上一次选币时间
        direction = None      # 交易方向
        
        # ✅ 容错值设为 K线周期的 10%
        tolerance = self.kline_period_td * 0.1
        
        for _, row in symbol_df.iterrows():
            select_time = row['candle_begin_time']  # 选币时间
            current_direction = 'long' if row['方向'] == 1 else 'short'
            
            if current_start is None:
                # 开始新期间
                current_start = select_time
                last_time = select_time
                direction = current_direction
            else:
                # ✅ 计算时间间隔（使用 timedelta）
                time_gap = select_time - last_time
                
                # ✅ 判断是否连续（严格模式：间隔必须 <= 持仓周期 + 方向一致）
                if time_gap <= self.hold_period_td + tolerance and current_direction == direction:
                    # 连续，延续当前期间
                    last_time = select_time
                else:
                    # 不连续，保存当前期间，开始新期间
                    period = self._create_period_record(
                        symbol, current_start, last_time, direction
                    )
                    periods.append(period)
                    
                    # 开始新期间
                    current_start = select_time
                    last_time = select_time
                    direction = current_direction
        
        # 保存最后一个期间
        if current_start is not None:
            period = self._create_period_record(
                symbol, current_start, last_time, direction
            )
            periods.append(period)
        
        return periods
    
    def _create_period_record(self, symbol: str, start_select_time: pd.Timestamp,
                              end_select_time: pd.Timestamp, direction: str) -> Dict:
        """
        创建交易期间记录
        
        关键时间转换：
        - entry_time = 第一次选币时间 + 1个K线周期（实际买入在下一根K线开盘）
        - exit_time = 最后一次选币时间 + 持仓周期 + 1个K线周期
        
        Args:
            symbol: 币种名称
            start_select_time: 第一次选币时间
            end_select_time: 最后一次选币时间
            direction: 交易方向 ('long' 或 'short')
            
        Returns:
            交易期间字典
        """
        # ✅ 修改：使用 kline_period 而非硬编码1小时
        entry_time = start_select_time + self.kline_period_td
        exit_time = end_select_time + self.hold_period_td + self.kline_period_td
        
        holding_duration = exit_time - entry_time
        
        # ✅ 保持向后兼容：持仓时长统一用小时表示
        # (HTML 格式化函数会自动处理小数位的小时，转换为合适的显示格式)
        holding_hours = holding_duration.total_seconds() / 3600
        
        return {
            'symbol': symbol,
            'direction': direction,
            'entry_time': entry_time,
            'exit_time': exit_time,
            'holding_hours': round(holding_hours, 2),
            # 以下字段在后续步骤中填充
            'return': 0.0,
            'max_drawdown': 0.0,
            'volatility': 0.0,
            'return_drawdown_ratio': 0.0,
        }

