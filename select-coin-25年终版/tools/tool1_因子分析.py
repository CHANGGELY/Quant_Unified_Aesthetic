# -*- coding: utf-8 -*-
"""
使用方法：
        直接运行文件即可
"""
import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import warnings

import pandas as pd

import tools.utils.pfunctions as pf
import tools.utils.tfunctions as tf
from core.model.strategy_config import FilterFactorConfig, filter_common
from core.utils.path_kit import get_file_path, get_folder_path

warnings.filterwarnings('ignore')

# ====== 因子分析主函数 ======
def factors_analysis(factor_dict_info, filter_list_info, mode_info):
    print("开始进行因子分析...")

    # ====== 整合所有因子数据 ======
    # 生成所有因子名称
    factor_name_list = [
        f'factor_{factor}_{param}'
        for factor, params in factor_dict_info.items()
        for param in params
    ]

    print("读取处理后的所有币K线数据...")
    # 读取处理后所有币的K线数据
    all_factors_kline = pd.read_pickle(get_file_path('data', 'cache', 'all_factors_df.pkl'))

    for factor_name in factor_name_list:
        print(f"读取因子数据：{factor_name}...")
        factor = pd.read_pickle(get_file_path('data', 'cache', f'{factor_name}.pkl'))
        if factor.empty:
            raise ValueError(f"{factor_name} 数据为空，请检查因子数据")
        all_factors_kline[factor_name] = factor

    filter_factor_list = [FilterFactorConfig.init(item) for item in filter_list_info]
    for filter_config in filter_factor_list:
        filter_path = get_file_path(
            "data", "cache", f"factor_{filter_config.col_name}.pkl"
        )
        print(f"读取过滤因子数据：{filter_config.col_name}...")
        filter_factor = pd.read_pickle(filter_path)
        if filter_factor.empty:
            raise ValueError(f"{filter_config.col_name} 数据为空，请检查因子数据")
        all_factors_kline[filter_config.col_name] = filter_factor

    # 过滤币种
    if mode_info == 'spot':  # 只用现货
        mode_kline = all_factors_kline[all_factors_kline['is_spot'] == 1]
        if mode_kline.empty:
            raise ValueError("现货数据为空，请检查数据")
    elif mode_info == 'swap':
        mode_kline = all_factors_kline[(all_factors_kline['is_spot'] == 0)]
        if mode_kline.empty:
            raise ValueError("合约数据为空，请检查数据")
    elif mode_info == 'spot+swap':
        mode_kline = all_factors_kline
        if mode_kline.empty:
            raise ValueError("现货及合约数据为空，请检查数据")
    else:
        raise ValueError('mode错误，只能选择 spot / swap / spot+swap')

    # ====== 在计算分组净值之前进行过滤操作 ======
    filter_condition = filter_common(mode_kline, filter_factor_list)
    mode_kline = mode_kline[filter_condition]

    # ====== 分别绘制每个因子不同参数的分箱图和分组净值曲线，并逐个保存 ======
    for factor_name in factor_name_list:
        print(f"开始绘制因子 {factor_name} 的分箱图和分组净值曲线...")
        # 计算分组收益率和分组最终净值，默认10分组，也可通过bins参数调整
        group_curve, bar_df, labels = tf.group_analysis(mode_kline, factor_name)
        # resample 1D
        group_curve = group_curve.resample('D').last()

        fig_list = []
        # 公共条件判断
        is_spot_mode = mode in ('spot', 'spot+swap')

        # 分箱图处理
        if not is_spot_mode:
            labels += ['多空净值']
        bar_df = bar_df[bar_df['groups'].isin(labels)]
        # 构建因子值标识列表
        factor_labels = ['因子值最小'] + [''] * 3 + ['因子值最大']
        if not is_spot_mode:
            factor_labels.append('')
        bar_df['因子值标识'] = factor_labels

        group_fig = pf.draw_bar_plotly(x=bar_df['groups'], y=bar_df['asset'], text_data=bar_df['因子值标识'],
                                       title='分组净值')
        fig_list.append(group_fig)

        # 分组资金曲线处理
        cols_list = [col for col in group_curve.columns if '第' in col]
        y2_data = group_curve[['多空净值']] if not is_spot_mode else pd.DataFrame()
        group_fig = pf.draw_line_plotly(x=group_curve.index, y1=group_curve[cols_list], y2=y2_data, if_log=True,
                                        title='分组资金曲线')
        fig_list.append(group_fig)

        # 输出结果
        output_dir = get_folder_path("data", "分析结果", "因子分析", path_type=True)
        # 分析区间
        start_time = group_curve.index[0].strftime('%Y/%m/%d')
        end_time = group_curve.index[-1].strftime('%Y/%m/%d')

        html_path = output_dir / f'{factor_name}分析报告.html'
        title = f'{factor_name}分析报告 分析区间 {start_time}-{end_time} 分析周期 1H'
        link_url = "https://bbs.quantclass.cn/thread/54137"
        link_text = '如何看懂这些图？'
        pf.merge_html_flexible(fig_list, html_path, title=title, link_url=link_url, link_text=link_text)
        print(f"因子 {factor_name} 的分析结果已完成。")


if __name__ == "__main__":
    # ====== 使用说明 ======
    "https://bbs.quantclass.cn/thread/54137"

    # ====== 配置信息 ======
    # 读取所有因子数据，因子和K线数据是分开保存的，data/cache目录下
    # 注意点：data/cache目录下是最近一次策略的相关结果，如果想运行之前策略下相关因子的分析，需要将该策略整体运行一遍

    # 输入策略因子及每个因子对应的参数，支持单参数和多参数
    # 注意点：多参数需要以列表内元组的方式输入，比如 [(10, 20, ...), (24, 96)]
    # 注意点：原始分箱图分组排序默认从小到大，即第一组为因子值最小的一组，最后一组为因子值最大的一组
    factor_dict = {
        'VWapBias': [1000],
    }

    # 配置前置过滤因子。配置方式和config中一致
    filter_list = [
        # ('QuoteVolumeMean', 48, 'pct:>0.8', True),
    ]

    # 数据模式, 只用现货：'spot'，只用合约：'swap'，现货和合约都用：'spot+swap'
    mode = 'spot'

    # 开始进行因子分析
    factors_analysis(factor_dict, filter_list, mode)
