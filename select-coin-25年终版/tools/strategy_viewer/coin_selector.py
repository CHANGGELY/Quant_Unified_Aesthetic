"""
邢不行™️选币框架 - 币种/期间筛选器
Python数字货币量化投资课程

版权所有 ©️ 邢不行
微信: xbx8662

根据配置筛选目标交易期间
"""

import pandas as pd
from .viewer_config import StrategyViewerConfig, SelectionMode


class CoinSelector:
    """币种/交易期间筛选器"""
    
    def __init__(self, config: StrategyViewerConfig):
        """
        初始化筛选器
        
        Args:
            config: 策略查看器配置
        """
        self.config = config
    
    def select(self, periods_df: pd.DataFrame) -> pd.DataFrame:
        """
        筛选交易期间
        
        流程：
        1. 按 target_symbols 过滤（如果指定）
        2. 添加原始收益排名（固定，用于标记）
        3. 按 metric_type 排序
        4. 添加当前排序排名
        5. 按 selection_mode 筛选
        
        Args:
            periods_df: 所有交易期间
            
        Returns:
            筛选后的交易期间
        """
        if periods_df.empty:
            print("⚠️ 没有可筛选的交易期间")
            return pd.DataFrame()
        
        # Step 1: 按 target_symbols 过滤（如果指定）
        if self.config.target_symbols:
            filtered_df = periods_df[
                periods_df['symbol'].isin(self.config.target_symbols)
            ]
            print(f"🎯 按指定币种过滤: {len(filtered_df)}/{len(periods_df)} 个期间")
        else:
            filtered_df = periods_df.copy()
        
        if filtered_df.empty:
            print("⚠️ 指定币种无交易期间")
            return pd.DataFrame()
        
        # Step 2: 添加原始收益排名（按收益率降序，固定不变）
        temp_sorted = filtered_df.sort_values('return', ascending=False).reset_index(drop=True)
        temp_sorted['original_rank'] = range(1, len(temp_sorted) + 1)
        
        # Step 3: 按 metric_type 排序
        sorted_df = self._sort_by_metric(temp_sorted)
        
        # Step 4: 添加当前排序排名
        sorted_df['current_rank'] = range(1, len(sorted_df) + 1)
        
        # Step 5: 按 selection_mode 筛选
        selected_df = self._filter_by_mode(sorted_df)
        
        if selected_df.empty:
            print("⚠️ 筛选后无结果")
        else:
            print(f"✅ 筛选完成: {len(selected_df)} 个交易期间")
        
        return selected_df
    
    def _sort_by_metric(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        按指标排序
        
        Args:
            df: 待排序的DataFrame
            
        Returns:
            排序后的DataFrame
        """
        metric_col = self.config.metric_type.value
        
        # 获取排序方向
        ascending = self.config.get_sort_ascending()
        
        # 排序
        sorted_df = df.sort_values(metric_col, ascending=ascending).reset_index(drop=True)
        
        direction_str = "升序" if ascending else "降序"
        print(f"📊 按 {metric_col} {direction_str}排序")
        
        return sorted_df
    
    def _filter_by_mode(self, sorted_df: pd.DataFrame) -> pd.DataFrame:
        """
        按模式筛选
        
        Args:
            sorted_df: 已排序的DataFrame
            
        Returns:
            筛选后的DataFrame
        """
        mode = self.config.selection_mode
        value = self.config.selection_value
        
        if mode == SelectionMode.RANK:
            # 按排名：(1, 10) = 第1-10名
            start_rank, end_rank = value
            
            # 确保索引在有效范围内
            start_idx = max(0, start_rank - 1)
            end_idx = min(len(sorted_df), end_rank)
            
            selected_df = sorted_df.iloc[start_idx:end_idx]
            print(f"🎯 RANK模式: 选择第{start_rank}-{end_rank}名")
        
        elif mode == SelectionMode.PCT:
            # 按百分比：(0.0, 0.1) = 前10%
            start_pct, end_pct = value
            total = len(sorted_df)
            
            start_idx = int(total * start_pct)
            end_idx = int(total * end_pct)
            
            # 确保至少选中一个
            if end_idx <= start_idx:
                end_idx = start_idx + 1
            
            selected_df = sorted_df.iloc[start_idx:end_idx]
            print(f"🎯 PCT模式: 选择{start_pct*100:.1f}%-{end_pct*100:.1f}%")
        
        elif mode == SelectionMode.VAL:
            # 按数值范围：(0.05, 0.2) = 指标值在5%-20%之间
            min_val, max_val = value
            metric_col = self.config.metric_type.value
            
            selected_df = sorted_df[
                (sorted_df[metric_col] >= min_val) &
                (sorted_df[metric_col] <= max_val)
            ]
            print(f"🎯 VAL模式: {metric_col} 在 [{min_val}, {max_val}] 范围")
        
        else:  # SelectionMode.SYMBOL
            # SYMBOL 模式：已在前面按 target_symbols 过滤，这里返回全部
            selected_df = sorted_df
            print(f"🎯 SYMBOL模式: 显示所有指定币种")
        
        return selected_df

