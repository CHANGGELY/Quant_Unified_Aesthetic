"""
邢不行™️选币框架 - 策略查看器配置模块
Python数字货币量化投资课程

版权所有 ©️ 邢不行
微信: xbx8662

策略查看器配置类和枚举定义
"""

from enum import Enum
from dataclasses import dataclass
from typing import List, Tuple, Optional, Union


class SelectionMode(Enum):
    """选择模式枚举"""
    RANK = "rank"      # 按排名选择
    PCT = "pct"        # 按百分比选择
    VAL = "val"        # 按数值范围选择
    SYMBOL = "symbol"  # 按指定币种选择


class MetricType(Enum):
    """指标类型枚举"""
    RETURN = "return"                              # 收益率
    MAX_DRAWDOWN = "max_drawdown"                  # 最大回撤
    VOLATILITY = "volatility"                      # 波动率
    RETURN_DRAWDOWN_RATIO = "return_drawdown_ratio"  # 收益回撤比


class SortDirection(Enum):
    """排序方向枚举"""
    DESC = "desc"  # 降序
    ASC = "asc"    # 升序
    AUTO = "auto"  # 自动（根据指标类型自动选择最优方向）


@dataclass
class StrategyViewerConfig:
    """策略查看器配置类"""
    
    enabled: bool = False                              # 是否启用策略查看器
    selection_mode: SelectionMode = SelectionMode.RANK # 选择模式
    metric_type: MetricType = MetricType.RETURN        # 排序指标类型
    sort_direction: SortDirection = SortDirection.AUTO # 排序方向
    selection_value: Tuple = (1, 10)                   # 选择参数值
    target_symbols: List[str] = None                   # 目标币种列表
    chart_days: Union[int, str] = 7                    # K线图显示范围：
                                                       # >=1H周期: 整数表示天数（'auto'或其他字符串默认为7天）
                                                       # <1H周期: 整数表示百分比，'auto'表示智能模式，'Nk'表示N根K线
    show_volume: bool = True                           # 是否显示成交量
    
    def __post_init__(self):
        """初始化后处理"""
        if self.target_symbols is None:
            self.target_symbols = []
    
    @classmethod
    def from_dict(cls, config_dict: dict) -> 'StrategyViewerConfig':
        """
        从字典创建配置对象
        
        Args:
            config_dict: 配置字典（来自 config.py）
            
        Returns:
            StrategyViewerConfig 实例
        """
        return cls(
            enabled=bool(config_dict.get('enabled', 0)),
            selection_mode=SelectionMode(config_dict.get('selection_mode', 'rank')),
            metric_type=MetricType(config_dict.get('metric_type', 'return')),
            sort_direction=SortDirection(config_dict.get('sort_direction', 'auto')),
            selection_value=config_dict.get('selection_value', (1, 10)),
            target_symbols=config_dict.get('target_symbols', []),
            chart_days=config_dict.get('chart_days', 7),
            show_volume=config_dict.get('show_volume', True),
        )
    
    def get_sort_ascending(self) -> bool:
        """
        获取实际的排序方向（升序/降序）
        
        Returns:
            True=升序，False=降序
        """
        if self.sort_direction == SortDirection.AUTO:
            # 自动模式：收益率和收益回撤比降序，其他升序
            if self.metric_type in [MetricType.RETURN, MetricType.RETURN_DRAWDOWN_RATIO]:
                return False  # 降序（高收益优先）
            else:
                return True   # 升序（低回撤、低波动优先）
        else:
            return self.sort_direction == SortDirection.ASC
    
    def __str__(self) -> str:
        """字符串表示"""
        return (
            f"StrategyViewerConfig(\n"
            f"  enabled={self.enabled}\n"
            f"  selection_mode={self.selection_mode.value}\n"
            f"  metric_type={self.metric_type.value}\n"
            f"  sort_direction={self.sort_direction.value}\n"
            f"  selection_value={self.selection_value}\n"
            f"  target_symbols={self.target_symbols}\n"
            f"  chart_days={self.chart_days}\n"
            f"  show_volume={self.show_volume}\n"
            f")"
        )

