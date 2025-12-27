"""
Quant Unified 量化交易系统
配置.py

功能：
    定义回测的全局配置，包括时间范围、资金、手续费、以及策略列表的管理。
"""
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Set, Union

import pandas as pd

from ..工具.路径 import 获取文件夹路径
from .策略配置 import 策略配置


class 回测配置:
    data_file_fingerprint: str = ''  # 记录数据文件的指纹

    def __init__(self, name: str, **config):
        self.name: str = name  # 账户名称
        self.start_date: str = config.get("start_date", '2021-01-01')  # 回测开始时间
        self.end_date: str = config.get("end_date", '2024-03-30')  # 回测结束时间

        # 账户回测交易模拟配置
        self.initial_usdt: Union[int, float] = config.get("initial_usdt", 10000)  # 初始现金
        self.leverage: Union[int, float] = config.get("leverage", 1)  # 杠杆
        self.margin_rate = 5 / 100  # 维持保证金率，净值低于这个比例会爆仓

        self.swap_c_rate: float = config.get("swap_c_rate", 6e-4)  # 合约买卖手续费
        self.spot_c_rate: float = config.get("spot_c_rate", 2e-3)  # 现货买卖手续费

        self.swap_min_order_limit: int = 5  # 合约最小下单量
        self.spot_min_order_limit: int = 10  # 现货最小下单量

        # 策略配置
        # 拉黑名单
        self.black_list: List[str] = config.get('black_list', [])
        # 最少上市多久
        self.min_kline_num: int = config.get('min_kline_num', 168)

        self.select_scope_set: Set[str] = set()
        self.order_first_set: Set[str] = set()
        self.is_use_spot: bool = False  # 是否包含现货策略
        self.is_day_period: bool = False  # 是否是日盘
        self.is_hour_period: bool = False  # 是否是小时盘
        self.factor_params_dict: Dict[str, set] = {}
        self.factor_col_name_list: List[str] = []
        self.hold_period: str = '1h'  # 最大的持仓周期

        # 策略列表，包含每个策略的详细配置
        self.strategy: Optional[策略配置] = None
        self.strategy_raw: Optional[dict] = None
        # 空头策略列表
        self.strategy_short: Optional[策略配置] = None
        self.strategy_short_raw: Optional[dict] = None
        # 策略评价
        self.report: Optional[pd.DataFrame] = None

        # 遍历标记
        self.iter_round: Union[int, str] = 0  # 遍历的INDEX

    def __repr__(self):
        return f"""{'+' * 56}
# {self.name} 配置信息如下：
+ 回测时间: {self.start_date} ~ {self.end_date}
+ 手续费: 合约{self.swap_c_rate * 100:.2f}%，现货{self.spot_c_rate * 100:.2f}%
+ 杠杆: {self.leverage:.2f}
+ 最小K线数量: {self.min_kline_num}
+ 拉黑名单: {self.black_list}
+ 策略配置如下:
{self.strategy}
{self.strategy_short if self.strategy_short is not None else ''}
{'+' * 56}
"""

    @property
    def 持仓周期类型(self):
        return 'D' if self.is_day_period else 'H'

    def info(self):
        print(self)

    def 获取全名(self, as_folder_name=False):
        fullname_list = [self.name, f"{self.strategy.获取全名(as_folder_name)}"]

        fullname = ' '.join(fullname_list)
        md5_hash = hashlib.md5(fullname.encode('utf-8')).hexdigest()
        return f'{self.name}-{md5_hash[:8]}' if as_folder_name else fullname

    def 加载策略配置(self, strategy_dict: dict, is_short=False):
        if is_short:
            self.strategy_short_raw = strategy_dict
        else:
            self.strategy_raw = strategy_dict

        strategy_cfg = 策略配置.初始化(**strategy_dict)

        if strategy_cfg.是否日线:
            self.is_day_period = True
        else:
            self.is_hour_period = True

        # 缓存持仓周期的事情
        self.hold_period = strategy_cfg.hold_period.lower()

        self.is_use_spot = strategy_cfg.is_use_spot

        self.select_scope_set.add(strategy_cfg.选币范围)
        self.order_first_set.add(strategy_cfg.优先下单)
        if not {'spot', 'mix'}.isdisjoint(self.select_scope_set) and self.leverage >= 2:
            print(f'现货策略不支持杠杆大于等于2的情况，请重新配置')
            exit(1)

        if strategy_cfg.long_select_coin_num == 0 and (strategy_cfg.short_select_coin_num == 0 or
                                                       strategy_cfg.short_select_coin_num == 'long_nums'):
            print('❌ 策略中的选股数量都为0，忽略此策略配置')
            exit(1)
        if is_short:
            self.strategy_short = strategy_cfg
        else:
            self.strategy = strategy_cfg
        self.factor_col_name_list += strategy_cfg.因子列名列表

        # 针对当前策略的因子信息，整理之后的列名信息，并且缓存到全局
        for factor_config in strategy_cfg.所有因子集合:
            # 添加到并行计算的缓存中
            if factor_config.name not in self.factor_params_dict:
                self.factor_params_dict[factor_config.name] = set()
            self.factor_params_dict[factor_config.name].add(factor_config.param)

        self.factor_col_name_list = list(set(self.factor_col_name_list))

    @classmethod
    def 从配置初始化(cls, config_module, load_strategy_list: bool = True) -> "回测配置":
        """
        :param config_module: 配置对象（module or dict-like object）
        :param load_strategy_list: 是否加载策略列表
        """
        
        # 兼容 dict 和 module
        def get_cfg(key, default=None):
            if isinstance(config_module, dict):
                return config_module.get(key, default)
            return getattr(config_module, key, default)

        backtest_config = cls(
            get_cfg('backtest_name', '未命名回测'),
            start_date=get_cfg('start_date'),  # 回测开始时间
            end_date=get_cfg('end_date'),  # 回测结束时间
            # ** 交易配置 **
            initial_usdt=get_cfg('initial_usdt', 10000),  # 初始usdt
            leverage=get_cfg('leverage', 1),  # 杠杆
            swap_c_rate=get_cfg('swap_c_rate', 6e-4),  # 合约买入手续费
            spot_c_rate=get_cfg('spot_c_rate', 2e-3),  # 现货买卖手续费
            # ** 数据参数 **
            black_list=get_cfg('black_list', []),  # 拉黑名单
            min_kline_num=get_cfg('min_kline_num', 168),  # 最小K线数量
        )

        # ** 策略配置 **
        # 初始化策略，默认都是需要初始化的
        if load_strategy_list:
            strategy = get_cfg('strategy')
            if strategy:
                backtest_config.加载策略配置(strategy)
            
            strategy_short = get_cfg('strategy_short')
            if strategy_short:
                backtest_config.加载策略配置(strategy_short, is_short=True)

        return backtest_config

    def 设置回测报告(self, report: pd.DataFrame):
        report['param'] = self.获取全名()
        self.report = report

    def 获取结果文件夹(self) -> Path:
        backtest_path = 获取文件夹路径('data', '回测结果', path_type=True)
        if self.iter_round == 0:
            return 获取文件夹路径(backtest_path, self.name, path_type=True)
        else:
            return 获取文件夹路径(
                获取文件夹路径('data', '遍历结果'),
                self.name,
                f'参数组合_{self.iter_round}' if isinstance(self.iter_round, int) else self.iter_round,
                path_type=True
            )

    def 获取策略配置表(self, with_factors=True) -> dict:
        factor_dict = {'hold_period': self.strategy.hold_period}
        ret = {
            '策略': self.name,
            'fullname': self.获取全名(),
        }
        if with_factors:
            # 按照逻辑顺序遍历因子
            factor_groups = [
                (self.strategy.long_factor_list, '#LONG-'),
                (self.strategy.long_filter_list, '#LONG-FILTER-'),
                (self.strategy.long_filter_list_post, '#LONG-POST-'),
                (self.strategy.short_factor_list, '#SHORT-'),
                (self.strategy.short_filter_list, '#SHORT-FILTER-'),
                (self.strategy.short_filter_list_post, '#SHORT-POST-'),
            ]
            
            for factor_list, prefix in factor_groups:
                for factor_config in factor_list:
                    _name = f'{prefix}{factor_config.name}'
                    _val = factor_config.param
                    factor_dict[_name] = _val
            
            ret.update(**factor_dict)

        return ret


class 回测配置工厂:
    """
    遍历参数的时候，动态生成配置
    """

    def __init__(self):
        # 存储生成好的config list
        self.config_list: List[回测配置] = []

    @property
    def 结果文件夹(self) -> Path:
        return 获取文件夹路径('data', '遍历结果', self.config_list[0].name if self.config_list else 'unknown', path_type=True)

    def 生成全因子配置(self, base_config_module=None):
        """
        产生一个conf，拥有所有策略的因子，用于因子加速并行计算
        """
        # 如果没有提供基础配置，尝试默认加载 (这在工具脚本中可能需要处理)
        if base_config_module is None:
             # 尝试动态获取 config，或者抛出异常
             pass

        # 创建一个空的基础配置
        # 这里假设 factory 使用场景下，可以通过第一个 config 来获取基础信息
        if not self.config_list:
            raise ValueError("配置列表为空，无法生成全因子配置")
        
        # 使用第一个配置作为模板
        template_conf = self.config_list[0]
        # 创建一个新的配置对象 (深拷贝或重新初始化)
        # 这里简化处理，直接用一个新的实例，但保留基础参数
        backtest_config = 回测配置(
            template_conf.name,
            start_date=template_conf.start_date,
            end_date=template_conf.end_date,
            initial_usdt=template_conf.initial_usdt,
            leverage=template_conf.leverage,
            swap_c_rate=template_conf.swap_c_rate,
            spot_c_rate=template_conf.spot_c_rate,
            black_list=template_conf.black_list,
            min_kline_num=template_conf.min_kline_num
        )
        
        factor_list = set()
        filter_list = set()
        filter_list_post = set()
        
        for conf in self.config_list:
            if conf.strategy:
                factor_list |= set(conf.strategy.factor_list)
                filter_list |= set(conf.strategy.filter_list)
                filter_list_post |= set(conf.strategy.filter_list_post)
            if conf.strategy_short:
                factor_list |= set(conf.strategy_short.factor_list)
                filter_list |= set(conf.strategy_short.filter_list)
                filter_list_post |= set(conf.strategy_short.filter_list_post)
        
        # 构造合并后的策略字典
        # 注意：这里只合并因子，其他参数用模板的
        strategy_all = template_conf.strategy_raw.copy() if template_conf.strategy_raw else {}
        # 移除原有的因子列表
        for k in list(strategy_all.keys()):
            if k.endswith(('factor_list', 'filter_list', 'filter_list_post')):
                del strategy_all[k]
        
        # 重新转换回 list of tuples，因为 加载策略配置 期望的是 list
        # 但我们这里存储的是 localized objects (因子配置), 需要转换回 tuples 或者让 加载策略配置 支持 objects
        # 现有的 加载策略配置 支持 tuple list.
        
        # 我们的 因子配置 对象有 转元组() 方法
        # 但这里的 factor_list 是 set of tuples (因为 因子配置.转元组 返回 tuple)
        # Wait, in 策略配置, factor_list is List[tuple].
        
        strategy_all['factor_list'] = list(factor_list)
        strategy_all['filter_list'] = list(filter_list)
        strategy_all['filter_list_post'] = list(filter_list_post)

        backtest_config.加载策略配置(strategy_all)
        return backtest_config

    def 获取参数表(self) -> pd.DataFrame:
        rows = []
        for config in self.config_list:
            rows.append(config.获取策略配置表())

        sheet = pd.DataFrame(rows)
        # 确保目录存在
        self.结果文件夹.parent.mkdir(parents=True, exist_ok=True)
        sheet.to_excel(self.结果文件夹.parent / '策略回测参数总表.xlsx', index=False)
        return sheet

    def 生成策略列表(self, strategies: List[dict], base_config_module=None) -> List[回测配置]:
        """
        :param strategies: 策略字典列表
        :param base_config_module: 基础配置模块 (提供 start_date 等全局参数)
        """
        config_list = []
        iter_round = 0

        for strategy in strategies:
            iter_round += 1
            # 初始化配置
            if base_config_module:
                backtest_config = 回测配置.从配置初始化(base_config_module, load_strategy_list=False)
            else:
                # 如果没有基础配置，使用默认值或第一个策略作为基础（不推荐）
                 backtest_config = 回测配置('遍历回测')
            
            backtest_config.加载策略配置(strategy)
            backtest_config.iter_round = iter_round

            config_list.append(backtest_config)

        self.config_list = config_list

        return config_list

# Alias
BacktestConfigFactory = 回测配置工厂
BacktestConfigFactory.generate_all_factor_config = 回测配置工厂.生成全因子配置
BacktestConfigFactory.get_name_params_sheet = 回测配置工厂.获取参数表
BacktestConfigFactory.generate_by_strategies = 回测配置工厂.生成策略列表
