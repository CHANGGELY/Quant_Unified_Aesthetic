# -*- coding: utf-8 -*-
"""
邢不行｜策略分享会
选币策略框架𝓟𝓻𝓸

版权所有 ©️ 邢不行
微信: xbx1717

本代码仅供个人学习使用，未经授权不得复制、修改或用于商业用途。

Author: 邢不行
"""
import os
import warnings
from itertools import combinations
from typing import List

import numpy as np

import tools.utils.pfunctions as pf
import tools.utils.tfunctions as tf

warnings.filterwarnings('ignore')
_ = os.path.abspath(os.path.dirname(__file__))  # 返回当前文件路径
root_path = os.path.abspath(os.path.join(_, '..'))  # 返回根目录文件夹


def curve_pairs_analysis(strategy_list: List[str]):
    # 计算策略资金曲线涨跌幅两两之间的相关性
    print("开始进行策略资金曲线涨跌幅相关性分析")
    curve_return = tf.curve_difference_all_pairs(root_path, strategy_list)
    strategy_pairs = list(combinations(strategy_list, 2))
    for strat1, strat2 in strategy_pairs:
        # 提取策略对数据
        pair_df = curve_return[[strat1, strat2]].copy()
        # 考虑到策略回测时间不同，去除nan值
        pair_df = pair_df.dropna()
        if pair_df.empty:
            print(f'🔔 {strat1}和{strat2} 回测时间无交集，需要核实策略回测config')

    print("开始计算相关性")
    curve_corr = curve_return.corr()
    curve_corr = curve_corr.round(4)
    curve_corr.replace(np.nan, '', inplace=True)

    # 画热力图
    print("开始绘制热力图")
    fig = pf.draw_params_heatmap_plotly(curve_corr, '多策略选币资金曲线涨跌幅相关性')
    output_dir = os.path.join(root_path, 'data/分析结果/资金曲线涨跌幅相关性')
    os.makedirs(output_dir, exist_ok=True)
    html_name = '多策略选币资金曲线涨跌幅相关性.html'
    pf.merge_html_flexible([fig], os.path.join(output_dir, html_name))
    print("多策略资金曲线涨跌幅分析完成")


if __name__ == "__main__":
    # ====== 使用说明 ======
    "https://bbs.quantclass.cn/thread/54137"

    # ====== 配置信息 ======
    # 输入回测策略名称, 与 data/回测结果 下的文件夹名称对应
    strategies_list = [
        '低价币中性策略',
        '浪淘沙策略',
        'BiasQuantile_amount',
        'CCI_amount',
    ]

    # 开始分析
    curve_pairs_analysis(strategies_list)
