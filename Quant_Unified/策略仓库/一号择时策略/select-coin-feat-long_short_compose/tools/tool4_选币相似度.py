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
from typing import List

import numpy as np
import pandas as pd

import tools.utils.pfunctions as pf
import tools.utils.tfunctions as tf

warnings.filterwarnings('ignore')
_ = os.path.abspath(os.path.dirname(__file__))  # 返回当前文件路径
root_path = os.path.abspath(os.path.join(_, '..'))  # 返回根目录文件夹


def coins_analysis(strategy_list: List[str]):
    print("开始多策略选币相似度分析")

    # 计算策略选币两两之间的相似度
    pairs_similarity = tf.coins_difference_all_pairs(root_path, strategy_list)

    similarity_df = pd.DataFrame(
        data=np.nan,
        index=strategy_list,
        columns=strategy_list
    )

    for a, b, value in pairs_similarity:
        similarity_df.loc[a, b] = value
        similarity_df.loc[b, a] = value
    # 填充对角线元素为1
    np.fill_diagonal(similarity_df.values, 1)
    similarity_df = similarity_df.round(2)
    similarity_df.replace(np.nan, '', inplace=True)

    print("开始绘制热力图")
    # 画热力图
    fig = pf.draw_params_heatmap_plotly(similarity_df, title='多策略选币相似度')
    output_dir = os.path.join(root_path, 'data/分析结果/选币相似度')
    os.makedirs(output_dir, exist_ok=True)
    html_name = '多策略选币相似度对比.html'
    pf.merge_html_flexible([fig], os.path.join(output_dir, html_name))
    print("多策略选币相似度分析完成")


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
        '2_000纯空BiasQ',
        '2_000纯空MinMax'
    ]

    # 开始分析
    coins_analysis(strategies_list)
