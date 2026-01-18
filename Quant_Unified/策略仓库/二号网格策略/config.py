# 2 号网格策略 - 基础配置定义
# 这个文件定义了 Config 类，作为回测和实盘配置的基类。
# 请不要直接修改此文件中的类定义，而是在 config_backtest.py 或 config_live.py 中进行实例化和参数配置。

from pathlib import Path
from datetime import datetime
import re

from 基础库.common_core.data_center import 获取历史行情子目录
# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

class Config:
    def __init__(self, **kwargs):
        # 默认参数 (基准值)
        defaults = {
            'symbol': "SOLUSDC",
            'money': 1000,
            'leverage': 1,
            'interval_mode': "geometric_sequence",
            'direction_mode': "long",
            'capital_ratio': 1.0,
            'capital_weight': 1.0,
            'enabled': True,
            'orders_per_side': 1,
            'enable_upward_shift': True,
            'enable_downward_shift': True,
            'stop_up_price': None,
            'stop_down_price': None,
            'num_steps': 20,
            'min_price': 0,
            'max_price': 0,
            'price_range': 0, # 默认关闭动态区间 (0)，避免覆盖 min/max_price
            'enable_compound': True,

            'post_only': False,
            'post_only_tick_offset_buy': 1,
            'post_only_tick_offset_sell': 1,
            'post_only_reject_retry_limit': 2,
            'tick_size': 0.01,
            'qty_precision': None,
            'max_position_ratio': 0.0,
            'max_position_value': 0.0,

            # 对冲督导员 (Supervisor) 参数
            'hedge_diff_threshold': 0.2,       # Delta 失衡阈值 (20%)，即 |L-S|/S > 0.2 时触发平衡
            'auto_build_position': False,      # 是否允许自动构建底仓（用于“趋势卖飞”/对冲补仓）
            'min_hedge_ratio': 0.1,            # 最小对冲比例（低于该比例会触发底仓重置/补仓逻辑）
            'target_hedge_ratio': 0.4,        # 补仓目标对冲比例 (40%)
            'supervisor_check_interval': 30,  # 督导员巡检间隔 (秒)
            
            # 回测专用参数
            'candle_period': "1m",
            'start_time': "2024-01-01 00:00:00",
            'end_time': "2025-01-01 00:00:00",
            'timezone': "Asia/Shanghai",
            'num_hours': 0,
            'data_center_dir': 获取历史行情子目录("分钟K线"),
            'local_data_path': None,
            'run_id': None
        }
        
        # 先设置默认值
        for k, v in defaults.items():
            setattr(self, k, v)
            
        # 再应用传入的参数覆盖默认值
        # 说明：这里选择“接收未知字段”而不是静默忽略。
        # 原因：实盘/回测会不断增加新参数，如果这里忽略了，就会出现：
        #   你以为配置生效了，但其实根本没被写进对象里（最难排查的那种 bug）。
        for k, v in kwargs.items():
            setattr(self, k, v)

        if not getattr(self, 'run_id', None):
            self.run_id = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        
        # 动态计算 result_dir (如果未被覆盖)
        if 'result_dir' not in kwargs:
            # 使用当前文件夹名称，而不是硬编码 "2 号网格策略"
            current_folder = Path(__file__).resolve().parent.name
            self.result_dir = PROJECT_ROOT / current_folder / "data" / "回测结果" / self.get_fullname()

    def get_fullname(self):
        direction_raw = str(getattr(self, 'direction_mode', '')).lower()
        if 'long' in direction_raw:
            direction_cn = '多'
        elif 'short' in direction_raw:
            direction_cn = '空'
        else:
            direction_cn = '中'

        def _fmt_time(value: str) -> str:
            s = str(value).strip()
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
                try:
                    return datetime.strptime(s, fmt).strftime('%Y%m%d-%H%M%S')
                except Exception:
                    pass
            digits = re.sub(r'[^0-9]', '', s)
            return digits[:14] if len(digits) >= 14 else (digits or 'unknown')

        start_fmt = _fmt_time(getattr(self, 'start_time', ''))
        end_fmt = _fmt_time(getattr(self, 'end_time', ''))

        price_range = getattr(self, 'price_range', 0) or 0
        if price_range:
            range_part = f'pr{price_range:g}'
        else:
            min_price = getattr(self, 'min_price', 0)
            max_price = getattr(self, 'max_price', 0)
            range_part = f'{min_price:g}-{max_price:g}'

        raw = (
            f"{self.symbol}{direction_cn}_网格_"
            f"{getattr(self, 'candle_period', 'unknown')}_"
            f"{start_fmt}~{end_fmt}_"
            f"{getattr(self, 'num_steps', 'unknown')}格_"
            f"{range_part}_"
            f"{getattr(self, 'run_id', 'unknown')}"
        )

        safe = re.sub(r'[^0-9A-Za-z\u4e00-\u9fff._+\-~()]', '_', raw)
        return safe.strip('_')

    def to_dict(self):
        # 返回完整字典（更易扩展，也避免“新增字段忘记同步到 to_dict”导致参数失效）
        return dict(self.__dict__)
