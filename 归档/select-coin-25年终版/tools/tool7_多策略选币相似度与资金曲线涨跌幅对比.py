"""
多策略选币相似度与资金曲线涨跌幅对比工具

使用方法：
        直接运行文件即可
"""

import os
import sys
import warnings
from itertools import combinations
from typing import List
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import tools.utils.pfunctions as pf
import tools.utils.tfunctions as tf

warnings.filterwarnings("ignore")
_ = os.path.abspath(os.path.dirname(__file__))
root_path = os.path.abspath(os.path.join(_, ".."))


def coins_analysis(strategy_list: List[str]):
    print("开始多策略选币相似度分析")

    pairs_similarity = tf.coins_difference_all_pairs(root_path, strategy_list)

    similarity_df = pd.DataFrame(
        data=np.nan,
        index=strategy_list,
        columns=strategy_list,
    )

    for a, b, value in pairs_similarity:
        similarity_df.loc[a, b] = value
        similarity_df.loc[b, a] = value
    np.fill_diagonal(similarity_df.values, 1)
    similarity_df = similarity_df.round(2)
    similarity_df.replace(np.nan, "", inplace=True)

    print("开始绘制多策略选币相似度热力图")
    fig = pf.draw_params_heatmap_plotly(similarity_df, title="多策略选币相似度")
    output_dir = os.path.join(root_path, "data/分析结果/选币相似度")
    os.makedirs(output_dir, exist_ok=True)
    html_name = "多策略选币相似度对比.html"
    pf.merge_html_flexible([fig], os.path.join(output_dir, html_name))
    print("多策略选币相似度分析完成")


def curve_pairs_analysis(strategy_list: List[str]):
    print("开始进行策略资金曲线涨跌幅相关性分析")
    curve_return = tf.curve_difference_all_pairs(root_path, strategy_list)
    strategy_pairs = list(combinations(strategy_list, 2))
    for strat1, strat2 in strategy_pairs:
        pair_df = curve_return[[strat1, strat2]].copy()
        pair_df = pair_df.dropna()
        if pair_df.empty:
            print(f"提示: {strat1} 和 {strat2} 回测时间无交集，请检查回测配置")

    print("开始计算资金曲线涨跌幅相关性")
    curve_corr = curve_return.corr()
    curve_corr = curve_corr.round(4)
    curve_corr.replace(np.nan, "", inplace=True)

    print("开始绘制资金曲线涨跌幅相关性热力图")
    fig = pf.draw_params_heatmap_plotly(curve_corr, "多策略选币资金曲线涨跌幅相关性")
    output_dir = os.path.join(root_path, "data/分析结果/资金曲线涨跌幅相关性")
    os.makedirs(output_dir, exist_ok=True)
    html_name = "多策略选币资金曲线涨跌幅相关性.html"
    pf.merge_html_flexible([fig], os.path.join(output_dir, html_name))
    print("多策略资金曲线涨跌幅分析完成")


if __name__ == "__main__":
    strategies_list = [
        # "CCI_amount",
        # "2_000纯空BiasQ",
        # "2_000纯空MinMax",
    ]

    coins_analysis(strategies_list)
    curve_pairs_analysis(strategies_list)

