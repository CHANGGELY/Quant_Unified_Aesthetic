"""
Quant Unified 量化交易系统
策略配置.py

功能：
    定义选币策略的详细参数配置，包括因子列表、过滤条件、持仓周期等。
"""
from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass
from functools import cached_property
from typing import List, Tuple, Union, Set

import numpy as np
import pandas as pd


def 范围过滤(series, range_str):
    operator = range_str[:2] if range_str[:2] in ['>=', '<=', '==', '!='] else range_str[0]
    value = float(range_str[len(operator):])

    if operator == '>=':
        return series >= value
    if operator == '<=':
        return series <= value
    if operator == '==':
        return series == value
    if operator == '!=':
        return series != value
    if operator == '>':
        return series > value
    if operator == '<':
        return series < value
    raise ValueError(f"Unsupported operator: {operator}")


@dataclass(frozen=True)
class 因子配置:
    name: str = 'Bias'  # 选币因子名称
    is_sort_asc: bool = True  # 是否正排序 (True=从小到大, False=从大到小)
    param: int = 3  # 选币因子参数
    weight: float = 1  # 选币因子权重

    @classmethod
    def 解析配置列表(cls, config_list: List[tuple]):
        all_long_factor_weight = sum([factor[3] for factor in config_list])
        factor_list = []
        for factor_name, is_sort_asc, parameter_list, weight in config_list:
            new_weight = weight / all_long_factor_weight
            factor_list.append(cls(name=factor_name, is_sort_asc=is_sort_asc, param=parameter_list, weight=new_weight))
        return factor_list

    @cached_property
    def 列名(self):
        return f'{self.name}_{str(self.param)}'

    def __repr__(self):
        return f'{self.列名}{"↑" if self.is_sort_asc else "↓"}权重:{self.weight}'

    def 转元组(self):
        return self.name, self.is_sort_asc, self.param, self.weight


@dataclass(frozen=True)
class 过滤方法:
    how: str = ''  # 过滤方式 (rank, pct, val)
    range: str = ''  # 过滤值

    def __repr__(self):
        if self.how == 'rank':
            name = '排名'
        elif self.how == 'pct':
            name = '百分比'
        elif self.how == 'val':
            name = '数值'
        else:
            raise ValueError(f'不支持的过滤方式：`{self.how}`')

        return f'{name}:{self.range}'

    def 转字符串(self):
        return f'{self.how}:{self.range}'


@dataclass(frozen=True)
class 过滤因子配置:
    name: str = 'Bias'  # 选币因子名称
    param: int = 3  # 选币因子参数
    method: 过滤方法 = None  # 过滤方式
    is_sort_asc: bool = True  # 是否正排序

    def __repr__(self):
        _repr = self.列名
        if self.method:
            _repr += f'{"↑" if self.is_sort_asc else "↓"}{self.method}'
        return _repr

    @cached_property
    def 列名(self):
        return f'{self.name}_{str(self.param)}'

    @classmethod
    def 初始化(cls, filter_factor: tuple):
        # 仔细看，结合class的默认值，这个和默认策略中使用的过滤是一模一样的
        config = dict(name=filter_factor[0], param=filter_factor[1])
        if len(filter_factor) > 2:
            # 可以自定义过滤方式
            _how, _range = re.sub(r'\s+', '', filter_factor[2]).split(':')
            cls.检查数值(_range)
            config['method'] = 过滤方法(how=_how, range=_range)
        if len(filter_factor) > 3:
            # 可以自定义排序
            config['is_sort_asc'] = filter_factor[3]
        return cls(**config)

    def 转元组(self, full_mode=False):
        if full_mode:
            return self.name, self.param, self.method.转字符串(), self.is_sort_asc
        else:
            return self.name, self.param

    @staticmethod
    def 检查数值(range_str):
        _operator = range_str[:2] if range_str[:2] in ['>=', '<=', '==', '!='] else range_str[0]
        try:
            _ = float(range_str[len(_operator):])
        except ValueError:
            raise ValueError(f'过滤配置暂不支持表达式：`{range_str}`')


def 计算通用因子(df, factor_list: List[因子配置]):
    factor_val = np.zeros(df.shape[0])
    for factor_config in factor_list:
        col_name = f'{factor_config.name}_{str(factor_config.param)}'
        # 计算单个因子的排名
        _rank = df.groupby('candle_begin_time')[col_name].rank(ascending=factor_config.is_sort_asc, method='min')
        # 将因子按照权重累加
        factor_val += _rank * factor_config.weight
    return factor_val


def 通用过滤(df, filter_list: List[过滤因子配置]):
    condition = pd.Series(True, index=df.index)

    for filter_config in filter_list:
        col_name = f'{filter_config.name}_{str(filter_config.param)}'
        if filter_config.method.how == 'rank':
            rank = df.groupby('candle_begin_time')[col_name].rank(ascending=filter_config.is_sort_asc, pct=False)
            condition = condition & 范围过滤(rank, filter_config.method.range)
        elif filter_config.method.how == 'pct':
            rank = df.groupby('candle_begin_time')[col_name].rank(ascending=filter_config.is_sort_asc, pct=True)
            condition = condition & 范围过滤(rank, filter_config.method.range)
        elif filter_config.method.how == 'val':
            condition = condition & 范围过滤(df[col_name], filter_config.method.range)
        else:
            raise ValueError(f'不支持的过滤方式：{filter_config.method.how}')

    return condition


@dataclass
class 策略配置:
    # 持仓周期。目前回测支持日线级别、小时级别。例：1H，6H，3D，7D......
    # 当持仓周期为D时，选币指标也是按照每天一根K线进行计算。
    # 当持仓周期为H时，选币指标也是按照每小时一根K线进行计算。
    hold_period: str = '1D'.replace('h', 'H').replace('d', 'D')

    # 配置offset
    offset_list: List[int] = (0,)

    # 是否使用现货
    is_use_spot: bool = False  # True：使用现货。False：不使用现货，只使用合约。

    # 选币市场范围 & 交易配置
    #   配置解释： 选币范围 + '_' + 优先交易币种类型
    #
    #   spot_spot: 在 '现货' 市场中进行选币。如果现货币种含有'合约'，优先交易 '现货'。
    #   swap_swap: 在 '合约' 市场中进行选币。如果现货币种含有'现货'，优先交易 '合约'。
    market: str = 'swap_swap'

    # 多头选币数量。1 表示做多一个币; 0.1 表示做多10%的币
    long_select_coin_num: Union[int, float] = 0.1
    # 空头选币数量。1 表示做空一个币; 0.1 表示做空10%的币，'long_nums'表示和多头一样多的数量
    short_select_coin_num: Union[int, float, str] = 'long_nums'  # 注意：多头为0的时候，不能配置'long_nums'

    # 多头的选币因子列名。
    long_factor: str = '因子'  # 因子：表示使用复合因子，默认是 factor_list 里面的因子组合。需要修改 calc_factor 函数配合使用
    # 空头的选币因子列名。多头和空头可以使用不同的选币因子
    short_factor: str = '因子'

    # 选币因子信息列表，用于`2_选币_单offset.py`，`3_计算多offset资金曲线.py`共用计算资金曲线
    factor_list: List[tuple] = ()  # 因子名（和factors文件中相同），排序方式，参数，权重。

    long_factor_list: List[因子配置] = ()  # 多头选币因子
    short_factor_list: List[因子配置] = ()  # 空头选币因子

    # 确认过滤因子及其参数，用于`2_选币_单offset.py`进行过滤
    filter_list: List[tuple] = ()  # 因子名（和factors文件中相同），参数

    long_filter_list: List[过滤因子配置] = ()  # 多头过滤因子
    short_filter_list: List[过滤因子配置] = ()  # 空头过滤因子

    # 后置过滤因子及其参数，用于`2_选币_单offset.py`进行过滤
    filter_list_post: List[tuple] = ()  # 因子名（和factors文件中相同），参数

    long_filter_list_post: List[过滤因子配置] = ()  # 多头后置过滤因子
    short_filter_list_post: List[过滤因子配置] = ()  # 空头后置过滤因子

    # 后置过滤后是否重新分配仓位（满仓模式）
    # True：剩余币种平分原来的总仓位（保持满仓）
    # False：保持每个币的原权重（过滤掉的仓位闲置，部分仓位）
    reallocate_after_filter: bool = True

    cap_weight: float = 1  # 策略权重

    @cached_property
    def 选币范围(self):
        return self.market.split('_')[0]

    @cached_property
    def 优先下单(self):
        return self.market.split('_')[1]

    @cached_property
    def 是否日线(self):
        return self.hold_period.endswith('D')

    @cached_property
    def 是否小时线(self):
        return self.hold_period.endswith('H')

    @cached_property
    def 周期数(self) -> int:
        return int(self.hold_period.upper().replace('H', '').replace('D', ''))

    @cached_property
    def 周期类型(self) -> str:
        return self.hold_period[-1]

    @cached_property
    def 因子列名列表(self) -> List[str]:
        factor_columns = set()  # 去重

        # 针对当前策略的因子信息，整理之后的列名信息，并且缓存到全局
        for factor_config in set(self.long_factor_list + self.short_factor_list):
            # 策略因子最终在df中的列名
            factor_columns.add(factor_config.列名)  # 添加到当前策略缓存信息中

        # 针对当前策略的过滤因子信息，整理之后的列名信息，并且缓存到全局
        for filter_factor in set(self.long_filter_list + self.short_filter_list):
            # 策略过滤因子最终在df中的列名
            factor_columns.add(filter_factor.列名)  # 添加到当前策略缓存信息中

        # 针对当前策略的过滤因子信息，整理之后的列名信息，并且缓存到全局
        for filter_factor in set(self.long_filter_list_post + self.short_filter_list_post):
            # 策略过滤因子最终在df中的列名
            factor_columns.add(filter_factor.列名)  # 添加到当前策略缓存信息中

        return list(factor_columns)

    @cached_property
    def 所有因子集合(self) -> set:
        return (set(self.long_factor_list + self.short_factor_list) |
                set(self.long_filter_list + self.short_filter_list) |
                set(self.long_filter_list_post + self.short_filter_list_post))

    @classmethod
    def 初始化(cls, **config):
        # 自动补充因子列表
        config['long_select_coin_num'] = config.get('long_select_coin_num', 0.1)
        config['short_select_coin_num'] = config.get('short_select_coin_num', 'long_nums')

        # 初始化多空分离策略因子
        factor_list = config.get('factor_list', [])
        if 'long_factor_list' in config or 'short_factor_list' in config:
            # 如果设置过的话，默认单边是挂空挡
            factor_list = []
        long_factor_list = 因子配置.解析配置列表(config.get('long_factor_list', factor_list))
        short_factor_list = 因子配置.解析配置列表(config.get('short_factor_list', factor_list))

        # 初始化多空分离过滤因子
        filter_list = config.get('filter_list', [])
        if 'long_filter_list' in config or 'short_filter_list' in config:
            # 如果设置过的话，则默认单边是挂空挡
            filter_list = []
        long_filter_list = [过滤因子配置.初始化(item) for item in config.get('long_filter_list', filter_list)]
        short_filter_list = [过滤因子配置.初始化(item) for item in config.get('short_filter_list', filter_list)]

        # 初始化后置过滤因子
        filter_list_post = config.get('filter_list_post', [])
        if 'long_filter_list_post' in config or 'short_filter_list_post' in config:
            # 如果设置过的话，则默认单边是挂空挡
            filter_list_post = []

        # 就按好的list赋值
        config['long_factor_list'] = long_factor_list
        config['short_factor_list'] = short_factor_list
        config['long_filter_list'] = long_filter_list
        config['short_filter_list'] = short_filter_list
        config['long_filter_list_post'] = [过滤因子配置.初始化(item) for item in
                                           config.get('long_filter_list_post', filter_list_post)]
        config['short_filter_list_post'] = [过滤因子配置.初始化(item) for item in
                                            config.get('short_filter_list_post', filter_list_post)]

        # 多空分离因子字段
        if config['long_factor_list'] != config['short_factor_list']:
            config['long_factor'] = '多头因子'
            config['short_factor'] = '空头因子'

        # 检查配置是否合法
        if (len(config['long_factor_list']) == 0) and (config.get('long_select_coin_num', 0) != 0):
            raise ValueError('多空分离因子配置有误，多头因子不能为空')
        if (len(config['short_factor_list']) == 0) and (config.get('short_select_coin_num', 0) != 0):
            raise ValueError('多空分离因子配置有误，空头因子不能为空')

        # 开始初始化策略对象
        stg_conf = cls(**config)

        # 重新组合一下原始的tuple list
        stg_conf.factor_list = list(dict.fromkeys(
            [factor_config.转元组() for factor_config in stg_conf.long_factor_list + stg_conf.short_factor_list]))
        stg_conf.filter_list = list(dict.fromkeys(
            [filter_factor.转元组() for filter_factor in stg_conf.long_filter_list + stg_conf.short_filter_list]))
        
        # 后置过滤
        stg_conf.filter_list_post = list(dict.fromkeys(
            [filter_list_post.转元组() for filter_list_post in stg_conf.long_filter_list_post + stg_conf.short_filter_list_post]))

        return stg_conf

    def 获取全名(self, as_folder_name=False):
        factor_desc_list = [f'{self.long_factor_list}', f'前滤{self.long_filter_list}',
                            f'后滤{self.long_filter_list_post}']
        long_factor_desc = '&'.join(factor_desc_list)

        factor_desc_list = [f'{self.short_factor_list}', f'前滤{self.short_filter_list}',
                            f'后滤{self.short_filter_list_post}']
        short_factor_desc = '&'.join(factor_desc_list)

        # ** 回测特有 ** 因为需要计算hash，因此包含的信息不同
        fullname = f"""{self.hold_period}-{self.is_use_spot}-{self.market}"""
        fullname += f"""-多|数量:{self.long_select_coin_num},因子{long_factor_desc}"""
        fullname += f"""-空|数量:{self.short_select_coin_num},因子{short_factor_desc}"""

        md5_hash = hashlib.md5(f'{fullname}-{self.offset_list}'.encode('utf-8')).hexdigest()
        return f'{md5_hash[:8]}' if as_folder_name else fullname

    def __repr__(self):
        return f"""策略配置信息：
- 持仓周期: {self.hold_period}
- offset: ({len(self.offset_list)}个) {self.offset_list}
- 选币范围: {self.选币范围}
- 优先下单: {self.优先下单}
- 多头选币设置:
  * 选币数量: {self.long_select_coin_num}
  * 策略因子: {self.long_factor_list}
  * 前置过滤: {self.long_filter_list}
  * 后置过滤: {self.long_filter_list_post}
- 空头选币设置:
  * 选币数量: {self.short_select_coin_num}
  * 策略因子: {self.short_factor_list}
  * 前置过滤: {self.short_filter_list}
  * 后置过滤: {self.short_filter_list_post}"""

    def 计算选币因子(self, df) -> pd.DataFrame:
        # 计算多头因子
        new_cols = {self.long_factor: 计算通用因子(df, self.long_factor_list)}

        # 如果单独设置了空头过滤因子
        if self.short_factor != self.long_factor:
            new_cols[self.short_factor] = 计算通用因子(df, self.short_factor_list)

        return pd.DataFrame(new_cols, index=df.index)

    def 选币前过滤(self, df):
        # 过滤多空因子
        long_filter_condition = 通用过滤(df, self.long_filter_list)

        # 如果单独设置了空头过滤因子
        if self.long_filter_list != self.short_filter_list:
            short_filter_condition = 通用过滤(df, self.short_filter_list)
        else:
            short_filter_condition = long_filter_condition

        return df[long_filter_condition].copy(), df[short_filter_condition].copy()

    def 选币后过滤(self, df):
        """
        后置过滤（选币后过滤）
        返回多空分离的DataFrame，以支持满仓模式的仓位重新分配
        
        :param df: 选币后的DataFrame
        :return: (long_df, short_df) 多头和空头的DataFrame
        """
        long_filter_condition = (df['方向'] == 1) & 通用过滤(df, self.long_filter_list_post)
        short_filter_condition = (df['方向'] == -1) & 通用过滤(df, self.short_filter_list_post)

        return df[long_filter_condition].copy(), df[short_filter_condition].copy()

# Alias
StrategyConfig = 策略配置
FactorConfig = 因子配置
FilterFactorConfig = 过滤因子配置
