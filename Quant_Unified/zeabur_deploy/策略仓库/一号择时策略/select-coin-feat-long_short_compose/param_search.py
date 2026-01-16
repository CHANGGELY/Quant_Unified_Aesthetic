"""
Quant Unified 量化交易系统
param_search.py
"""
import time
import warnings

import pandas as pd

from core.model.backtest_config import create_factory
from program.step1_prepare_data import prepare_data
from program.step2_calculate_factors import calc_factors
from program.step3_select_coins import select_coins, aggregate_select_results
from program.step4_simulate_performance import simulate_performance

# ====================================================================================================
# ** 脚本运行前配置 **
# 主要是解决各种各样奇怪的问题们
# ====================================================================================================
warnings.filterwarnings('ignore')  # 过滤一下warnings，不要吓到老实人

# pandas相关的显示设置，基础课程都有介绍
pd.set_option('expand_frame_repr', False)  # 当列太多时不换行
pd.set_option('display.unicode.ambiguous_as_wide', True)  # 设置命令行输出时的列对齐功能
pd.set_option('display.unicode.east_asian_width', True)


def find_best_params(factory):
    """
    寻找最优参数
    :return:
    """
    # ====================================================================================================
    # 1. 准备工作
    # ====================================================================================================
    print('参数遍历开始', '*' * 64)

    conf_list = factory.config_list
    for index, conf in enumerate(conf_list):
        print(f'参数组合{index + 1}｜共{len(conf_list)}')
        print(f'{conf.get_fullname()}')
        print()
    print('✅ 一共需要回测的参数组合数：{}'.format(len(conf_list)))
    print()

    # ====================================================================================================
    # 2. 读取回测所需数据，并做简单的预处理
    # ====================================================================================================
    dummy_conf_with_all_factors = factory.generate_all_factor_config()  # 生成一个conf，拥有所有策略的因子
    # 读取数据
    # prepare_data(dummy_conf_with_all_factors)

    # ====================================================================================================
    # 3. 计算因子
    # ====================================================================================================
    # 然后用这个配置计算的话，我们就能获得所有策略的因子的结果，存储在 `data/cache/all_factors_df.pkl`
    calc_factors(dummy_conf_with_all_factors)

    # ====================================================================================================
    # 4. 选币
    # - 注意：选完之后，每一个策略的选币结果会被保存到硬盘
    # ====================================================================================================
    reports = []
    for backtest_config in factory.config_list:
        select_coins(backtest_config)  # 选币
        if backtest_config.strategy_short is not None:
            select_coins(backtest_config, is_short=True)  # 选币
        select_results = aggregate_select_results(backtest_config)
        report = simulate_performance(backtest_config, select_results, show_plot=False)
        reports.append(report)

    return reports


if __name__ == '__main__':
    print(f'🌀 系统启动中，稍等...')
    r_time = time.time()
    # ====================================================================================================
    # 1. 配置需要遍历的参数
    # ====================================================================================================
    # 因子遍历的参数范围
    strategies = []
    for param in range(100, 1000, 100):
        strategy = {
            "hold_period": "8H",  # 持仓周期，可以是H小时，或者D天。例如：1H，8H，24H，1D，3D，7D...
            # 在这里增加类似market参数，是交易现货还是合约，代替is_pure_long这个参数
            "market": "swap_swap",
            "cap_weight": 1,
            "offset_list": range(0, 8, 1),
            "long_select_coin_num": 0.2,  # 多头选币数量，可为整数或百分比。2 表示 2 个，10 / 100 表示前 10%
            "short_select_coin_num": 0,  # 空头选币数量。除和多头相同外，还支持 'long_nums' 表示与多头数量一致。效

            "factor_list": [  # 选币因子列表
                # 因子名称（与 factors 文件中的名称一致），排序方式（True 为升序，从小到大排，False 为降序，从大到小排），因子参数，因子权重
                ('VWapBias', False, 1000, 1),
                # 可添加多个选币因子
                # ('PctChange', False, 7, 1),
            ],
            "filter_list": [  # 过滤因子列表
                # 因子名称（与 factors 文件中的名称一致），因子参数，因子过滤规则，排序方式
                ('QuoteVolumeMean', 168, 'pct:>=0.8'),
            ],
            "filter_list_post": [  # 过滤因子列表
                # 因子名称（与 factors 文件中的名称一致），因子参数，因子过滤规则，排序方式
                ('UpTimeRatio', param, 'val:>=0.5'),
            ],
        }
        strategies.append(strategy)

    # ====================================================================================================
    # 2. 生成策略配置
    # ====================================================================================================
    print(f'🌀 生成策略配置...')
    backtest_factory = create_factory(strategies)

    # ====================================================================================================
    # 3. 寻找最优参数
    # ====================================================================================================
    report_list = find_best_params(backtest_factory)

    # ====================================================================================================
    # 6. 根据回测参数列表，展示最优参数
    # ====================================================================================================
    s_time = time.time()
    print(f'🌀 展示最优参数...')
    all_params_map = pd.concat(report_list, ignore_index=True)
    report_columns = all_params_map.columns  # 缓存列名

    # 合并参数细节
    sheet = backtest_factory.get_name_params_sheet()
    all_params_map = all_params_map.merge(sheet, left_on='param', right_on='fullname', how='left')

    # 按照累积净值排序，并整理结果
    all_params_map.sort_values(by='累积净值', ascending=False, inplace=True)
    all_params_map = all_params_map[[*sheet.columns, *report_columns]].drop(columns=['param'])
    all_params_map.to_excel(backtest_factory.result_folder / f'最优参数.xlsx', index=False)
    print(all_params_map)
    print(f'✅ 完成展示最优参数，花费时间：{time.time() - s_time:.3f}秒，累计时间：{(time.time() - r_time):.3f}秒')
    print()
