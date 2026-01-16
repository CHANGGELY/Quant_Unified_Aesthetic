"""
这份文件定义了【3号对冲策略】的配置类，用来统一管理策略参数。
作用：
1. 提供回测与实盘通用的参数容器（交易对、网格间距、仓位规模等）
2. 约定结果输出目录，方便查看回测报告
3. 与二号网格策略保持一致的风格，但更适配对冲与内部账本逻辑
"""

from pathlib import Path
import hashlib

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Config:
    def __init__(self, **kwargs):
        # 默认参数
        defaults = {
            'symbol': 'ETHUSDC',
            'money': 1000.0,
            'leverage': 3,
            'capital_ratio': 1.0,

            # 网格与对冲核心参数
            'grid_percent': 0.0016,   # 网格间距 0.16%
            'grid_levels': 5,         # 上5格、下5格
            'initial_long_size': 0.005,  # 初始多头开仓规模（单位：ETH）
            'initial_short_size': 0.005, # 初始空头开仓规模（单位：ETH）

            # maker 相关
            'post_only': True,
            'post_only_tick_offset_buy': 1,
            'post_only_tick_offset_sell': 1,
            'post_only_reject_retry_limit': 2,
            'tick_size': 0.01,

            # 回测专用参数
            'candle_period': '1m',
            'start_time': '2025-07-01 00:00:00',
            'end_time': '2025-10-09 00:00:00',
            'timezone': 'Asia/Shanghai',
            'num_hours': 0,
            'data_center_dir': PROJECT_ROOT / '一号择时策略/select-coin-feat-long_short_compose/data/swap',
            'local_data_path': None,

            # 安全阀
            'max_net_exposure_limit': None,         # 最大净头寸 (ETH) 上限
            'max_account_drawdown_percent': None,   # 最大账户回撤百分比
            'max_individual_position_size': None,   # 单边规模上限 (ETH)
        }

        for k, v in defaults.items():
            setattr(self, k, v)
        for k, v in kwargs.items():
            setattr(self, k, v)

        if 'result_dir' not in kwargs:
            current_folder = Path(__file__).resolve().parent.name
            self.result_dir = PROJECT_ROOT / current_folder / 'data' / '回测结果' / self.get_fullname()

    def get_fullname(self):
        params = [
            self.symbol,
            self.candle_period,
            str(self.money),
            str(self.leverage),
            str(self.grid_percent),
            str(self.grid_levels),
            self.start_time,
            self.end_time,
        ]
        unique_str = '_'.join(params)
        md5_hash = hashlib.md5(unique_str.encode('utf-8')).hexdigest()[:8]
        return f"{self.symbol}-对冲-{md5_hash}"

    def to_dict(self):
        return {
            'symbol': self.symbol,
            'money': self.money,
            'leverage': self.leverage,
            'capital_ratio': self.capital_ratio,
            'grid_percent': self.grid_percent,
            'grid_levels': self.grid_levels,
            'initial_long_size': self.initial_long_size,
            'initial_short_size': self.initial_short_size,
            'post_only': self.post_only,
            'post_only_tick_offset_buy': self.post_only_tick_offset_buy,
            'post_only_tick_offset_sell': self.post_only_tick_offset_sell,
            'post_only_reject_retry_limit': self.post_only_reject_retry_limit,
            'tick_size': self.tick_size,
        }

