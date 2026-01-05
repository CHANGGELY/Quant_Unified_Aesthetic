# -*- coding: utf-8 -*-
"""
8号香农策略 - 参数遍历优化脚本

目标：
    通过网格搜索找出卡玛比率最高（收益/回撤比最优）的参数组合
    让最大回撤控制在合理范围内，方便加杠杆

重点优化参数：
    1. 短期波动率窗口 (vol_short_window): 影响对波动的反应速度
    2. 长期波动率窗口 (vol_long_window): 影响基准波动率
    3. 网格宽度基数 (grid_width_base): 影响交易频率和成本
    4. 目标持仓比例 (target_ratio): 现金/ETH 比例

使用方法：
    cd /Users/chuan/Desktop/xiangmu/客户端/Quant_Unified
    python -X utf8 策略仓库/八号香农策略/参数遍历.py
"""

import sys
import os
import itertools
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

# ====== 自动计算项目根目录 ======
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# 导入回测函数 (从 backtest.py 导入核心函数)
from 策略仓库.八号香农策略.backtest import 加载数据, 向量化回测
from 基础库.common_core.backtest.metrics import 回测指标计算器
from 基础库.common_core.backtest.进度条 import 回测进度条


# ============================================================
# 参数空间定义
# ============================================================

# 🎯 重点优化参数
参数空间 = {
    # 短期波动率窗口 (分钟)
    # 越短 = 对波动越敏感，可能过度反应
    # 越长 = 反应越慢，可能错过机会
    'short_window': [30, 60, 120, 240],
    
    # 长期波动率窗口 (分钟)
    # 越短 = 基准更活跃
    # 越长 = 基准更稳定
    'long_window': [720, 1440, 2880],
    
    # 网格宽度基数 (比例)
    # 越小 = 交易越频繁，成本越高
    # 越大 = 交易越少，接近买入持有
    'grid_width': [0.001, 0.003, 0.005, 0.008, 0.01, 0.02],
    
    # 目标持仓比例 (固定 0.5, 策略核心逻辑不可变)
    'target_ratio': [0.5],
}

# 计算总组合数
总组合数 = 1
for v in 参数空间.values():
    总组合数 *= len(v)
print(f"📊 参数空间总组合数: {总组合数}")


# ============================================================
# 单次回测包装函数
# ============================================================

def 执行单次回测(参数组合: dict, 价格序列: np.ndarray, 时间序列: np.ndarray) -> dict:
    """
    执行单次回测并返回结果
    
    参数：
        参数组合: dict, 包含 short_window, long_window, grid_width, target_ratio
        价格序列: np.ndarray
        时间序列: np.ndarray
    
    返回：
        dict: 包含参数和所有指标的结果
    """
    try:
        结果 = 向量化回测(
            价格序列=价格序列,
            时间序列=时间序列,
            初始资金=1000.0,
            目标持仓比例=参数组合['target_ratio'],
            短期窗口=参数组合['short_window'],
            长期窗口=参数组合['long_window'],
            网格宽度基数=参数组合['grid_width'],
        )
        
        # 计算指标
        计算器 = 回测指标计算器(
            权益曲线=结果['权益曲线'],
            初始资金=1000.0,
            时间戳=时间序列,
            周期每年数量=525600,
        )
        指标 = 计算器.计算全部指标()
        
        return {
            # 参数
            'short_window': 参数组合['short_window'],
            'long_window': 参数组合['long_window'],
            'grid_width': 参数组合['grid_width'],
            'target_ratio': 参数组合['target_ratio'],
            # 核心指标
            '年化收益率': 指标.年化收益率,
            '最大回撤': 指标.最大回撤,  # 负数
            '卡玛比率': 指标.卡玛比率,
            '夏普比率': 指标.夏普比率,
            '总收益率': 指标.总收益率,
            '交易次数': 结果['交易次数'],
        }
    except Exception as e:
        return {
            'short_window': 参数组合['short_window'],
            'long_window': 参数组合['long_window'],
            'grid_width': 参数组合['grid_width'],
            'target_ratio': 参数组合['target_ratio'],
            '年化收益率': -999,
            '最大回撤': -999,
            '卡玛比率': -999,
            '夏普比率': -999,
            '总收益率': -999,
            '交易次数': 0,
            '错误': str(e),
        }


# ============================================================
# 主函数
# ============================================================

def 主函数():
    print()
    print("🔍" * 20)
    print("    8号香农策略 - 参数遍历优化")
    print("🔍" * 20)
    print()
    
    # 1. 加载数据 (只加载一次)
    数据文件 = "/Users/chuan/Desktop/xiangmu/客户端/Quant_Unified/策略仓库/二号网格策略/data_center/ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5"
    print("📂 加载数据...")
    df = 加载数据(数据文件)
    价格 = df['close'].values
    时间 = df['candle_begin_time'].values
    print(f"✅ 数据加载完成: {len(价格):,} 条")
    
    # 2. 生成所有参数组合
    参数键 = list(参数空间.keys())
    参数值列表 = list(参数空间.values())
    所有组合 = list(itertools.product(*参数值列表))
    
    print(f"🎯 开始遍历 {len(所有组合)} 种参数组合...")
    print()
    
    # 3. 遍历回测
    结果列表 = []
    
    with 回测进度条(总数=len(所有组合), 描述="参数遍历") as 进度:
        for 组合 in 所有组合:
            参数 = dict(zip(参数键, 组合))
            结果 = 执行单次回测(参数, 价格, 时间)
            结果列表.append(结果)
            
            # 显示当前最优
            if len(结果列表) > 0:
                当前最优 = max([r for r in 结果列表 if r.get('卡玛比率', -999) > -100], 
                             key=lambda x: x['卡玛比率'], default=None)
                if 当前最优:
                    进度.设置后缀(
                        最优卡玛=f"{当前最优['卡玛比率']:.2f}",
                        最优回撤=f"{当前最优['最大回撤']:.1%}"
                    )
            
            进度.更新(1)
    
    # 4. 整理结果
    df_结果 = pd.DataFrame(结果列表)
    
    # 过滤无效结果
    df_有效 = df_结果[df_结果['卡玛比率'] > -100].copy()
    
    # 按卡玛比率排序
    df_有效 = df_有效.sort_values('卡玛比率', ascending=False)
    
    # 5. 显示 Top 10 结果
    print()
    print("🏆" * 20)
    print("    最优参数组合 Top 10 (按卡玛比率排序)")
    print("🏆" * 20)
    print()
    
    print(f"{'排名':<4} {'短窗口':<8} {'长窗口':<8} {'网格宽度':<10} {'持仓比例':<8} {'年化收益':<10} {'最大回撤':<10} {'卡玛比率':<10} {'交易次数':<10}")
    print("-" * 90)
    
    for i, row in df_有效.head(10).iterrows():
        排名 = df_有效.index.get_loc(i) + 1
        print(f"{排名:<4} {row['short_window']:<8} {row['long_window']:<8} {row['grid_width']:<10.3f} {row['target_ratio']:<8.1f} {row['年化收益率']:<10.1%} {row['最大回撤']:<10.1%} {row['卡玛比率']:<10.2f} {int(row['交易次数']):<10}")
    
    # 6. 保存完整结果
    时间戳 = datetime.now().strftime("%Y%m%d_%H%M%S")
    输出文件 = PROJECT_ROOT / f"策略仓库/八号香农策略/参数遍历结果_{时间戳}.csv"
    df_有效.to_csv(输出文件, index=False, encoding='utf-8-sig')
    print()
    print(f"📁 完整结果已保存: {输出文件}")
    
    # 7. 给出最优参数建议
    最优 = df_有效.iloc[0]
    print()
    print("=" * 60)
    print("🎯 推荐最优参数:")
    print("=" * 60)
    print(f"  vol_short_window = {int(最优['short_window'])}")
    print(f"  vol_long_window  = {int(最优['long_window'])}")
    print(f"  grid_width_base  = {最优['grid_width']}")
    print(f"  target_ratio     = {最优['target_ratio']}")
    print()
    print(f"  预期年化收益: {最优['年化收益率']:.1%}")
    print(f"  预期最大回撤: {最优['最大回撤']:.1%}")
    print(f"  卡玛比率:     {最优['卡玛比率']:.2f}")
    print("=" * 60)
    
    # 8. 找出回撤 < 30% 的最优参数 (适合加杠杆)
    df_低回撤 = df_有效[df_有效['最大回撤'] > -0.30]  # 回撤小于30%
    if len(df_低回撤) > 0:
        最优低回撤 = df_低回撤.iloc[0]
        print()
        print("💪 适合加杠杆的低回撤参数 (回撤 < 30%):")
        print("=" * 60)
        print(f"  vol_short_window = {int(最优低回撤['short_window'])}")
        print(f"  vol_long_window  = {int(最优低回撤['long_window'])}")
        print(f"  grid_width_base  = {最优低回撤['grid_width']}")
        print(f"  target_ratio     = {最优低回撤['target_ratio']}")
        print()
        print(f"  预期年化收益: {最优低回撤['年化收益率']:.1%}")
        print(f"  预期最大回撤: {最优低回撤['最大回撤']:.1%}")
        print(f"  卡玛比率:     {最优低回撤['卡玛比率']:.2f}")
        print(f"  ⚡ 如果加2倍杠杆: 年化 {最优低回撤['年化收益率']*2:.1%}, 回撤 {最优低回撤['最大回撤']*2:.1%}")
        print("=" * 60)
    else:
        print()
        print("⚠️ 没有找到回撤 < 30% 的参数组合，建议尝试更保守的参数范围")


if __name__ == "__main__":
    主函数()
