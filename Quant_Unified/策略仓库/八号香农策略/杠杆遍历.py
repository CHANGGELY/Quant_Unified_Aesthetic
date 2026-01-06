# -*- coding: utf-8 -*-
"""
8号香农策略 - 杠杆参数遍历脚本

这个脚本是干什么的：
    遍历 position_leverage (逐笔杠杆 Z) 从 3 到 30，
    找出年化收益率最高的杠杆参数，同时观察爆仓风险。

核心逻辑：
    - 从低杠杆 (Z=3) 开始，逐步往高杠杆 (Z=30) 遍历
    - 如果某个杠杆下策略爆仓了，后面更高的杠杆大概率也会爆，就停止遍历
    - 最终按年化收益率从高到低排序输出

使用方法：
    cd /Users/chuan/Desktop/xiangmu/客户端/Quant_Unified
    python -X utf8 策略仓库/八号香农策略/杠杆遍历.py
"""

import sys
import os
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# ====== 自动计算项目根目录 ======
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# 导入回测函数
from 策略仓库.八号香农策略.backtest import 加载数据, 向量化回测
from 基础库.common_core.backtest.metrics import 回测指标计算器
from 策略仓库.八号香农策略 import config_backtest as cfg


# ============================================================
# 参数配置
# ============================================================

# 🎯 遍历范围：position_leverage 从 1 到 30
杠杆范围 = list(range(1, 31))  # [1, 2, 3, ..., 30]

print(f"📊 将遍历的杠杆参数: {杠杆范围[0]} ~ {杠杆范围[-1]} (共 {len(杠杆范围)} 个)")


# ============================================================
# 单次回测函数
# ============================================================

def 单次杠杆回测(杠杆倍数: float, 价格序列: np.ndarray, 时间序列: np.ndarray) -> dict:
    """
    用指定的杠杆倍数执行一次回测
    
    参数：
        杠杆倍数: float, position_leverage (逐笔杠杆 Z)
        价格序列: np.ndarray
        时间序列: np.ndarray
    
    返回：
        dict: 包含杠杆参数、所有指标、以及是否爆仓的结果
    """
    try:
        结果 = 向量化回测(
            价格序列=价格序列,
            时间序列=时间序列,
            初始资金=cfg.initial_capital,
            目标持仓比例=cfg.target_ratio,
            短期窗口=cfg.vol_short_window,
            长期窗口=cfg.vol_long_window,
            ewma_alpha=cfg.vol_ewma_alpha,
            spike阈值=cfg.regime_spike_threshold,
            crush阈值=cfg.regime_crush_threshold,
            vol_k_factor=cfg.vol_k_factor,
            min_grid_width_bps=cfg.min_grid_width_bps,
            杠杆倍数=杠杆倍数,  # 这是核心参数
        )
        
        # 检查是否爆仓 (权益曲线变成 0)
        权益末值 = 结果['权益曲线'][-1]
        是否爆仓 = 权益末值 <= 0 or np.any(结果['权益曲线'] <= 0)
        
        if 是否爆仓:
            # 爆仓了，找到第一个爆仓位置
            爆仓位置 = np.where(结果['权益曲线'] <= 0)[0]
            爆仓时间索引 = 爆仓位置[0] if len(爆仓位置) > 0 else -1
            return {
                'position_leverage': 杠杆倍数,
                'nominal_leverage': 结果['名义杠杆'],
                '年化收益率': None,  # 爆仓无意义
                '最大回撤': None,
                '卡玛比率': None,
                '夏普比率': None,
                '总收益率': None,
                '交易次数': 结果['交易次数'],
                '是否爆仓': True,
                '爆仓时间索引': 爆仓时间索引,
            }
        
        # 正常完成，计算指标
        计算器 = 回测指标计算器(
            权益曲线=结果['权益曲线'],
            初始资金=cfg.initial_capital,
            时间戳=时间序列,
            周期每年数量=525600,
        )
        指标 = 计算器.计算全部指标()
        
        return {
            'position_leverage': 杠杆倍数,
            'nominal_leverage': 结果['名义杠杆'],
            '年化收益率': 指标.年化收益率,
            '最大回撤': 指标.最大回撤,  # 负数
            '卡玛比率': 指标.卡玛比率,
            '夏普比率': 指标.夏普比率,
            '总收益率': 指标.总收益率,
            '交易次数': 结果['交易次数'],
            '是否爆仓': False,
            '爆仓时间索引': None,
        }
        
    except Exception as e:
        return {
            'position_leverage': 杠杆倍数,
            'nominal_leverage': None,
            '年化收益率': None,
            '最大回撤': None,
            '卡玛比率': None,
            '夏普比率': None,
            '总收益率': None,
            '交易次数': 0,
            '是否爆仓': True,
            '爆仓时间索引': None,
            '错误': str(e),
        }


# ============================================================
# 主函数
# ============================================================

def 主函数():
    print()
    print("⚡" * 20)
    print("    8号香农策略 - 杠杆参数遍历")
    print("⚡" * 20)
    print()
    print("📋 策略规则：")
    print("   - 从杠杆 Z=3 开始，逐步往上遍历到 Z=30")
    print("   - 如果策略爆仓，停止后续遍历（更高杠杆也会爆）")
    print("   - 最终按年化收益率排序输出")
    print()
    
    # 1. 加载数据 (只加载一次)
    数据文件 = cfg.data_file
    print(f"📂 加载数据: {数据文件}")
    df = 加载数据(数据文件)
    价格 = df['close'].values
    时间 = df['candle_begin_time'].values
    print(f"✅ 数据加载完成: {len(价格):,} 条")
    print()
    
    # 2. 遍历杠杆参数
    print(f"🔍 开始遍历杠杆参数 [{杠杆范围[0]} ~ {杠杆范围[-1]}]...")
    print("-" * 80)
    
    结果列表 = []
    
    for 杠杆 in 杠杆范围:
        print(f"   🧪 测试杠杆 Z = {杠杆:2}x ... ", end="", flush=True)
        
        结果 = 单次杠杆回测(杠杆, 价格, 时间)
        结果列表.append(结果)
        
        if 结果['是否爆仓']:
            print(f"💥 爆仓! (第 {结果.get('爆仓时间索引', '?')} 根K线)")
            print()
            print("⚠️  检测到爆仓，停止后续遍历（更高杠杆风险更大）")
            print()
            break
        else:
            年化 = 结果['年化收益率']
            回撤 = 结果['最大回撤']
            print(f"✅ 年化: {年化:.1%}, 回撤: {回撤:.1%}, 卡玛: {结果['卡玛比率']:.2f}")
    
    print("-" * 80)
    print()
    
    # 3. 整理结果 (只保留未爆仓的)
    df_结果 = pd.DataFrame(结果列表)
    df_有效 = df_结果[df_结果['是否爆仓'] == False].copy()
    
    if len(df_有效) == 0:
        print("❌ 所有杠杆参数都爆仓了！请考虑更保守的策略参数。")
        return
    
    # 按卡玛比率排序 (从高到低)
    df_有效 = df_有效.sort_values('卡玛比率', ascending=False)
    
    # 4. 显示结果
    print("🏆" * 20)
    print("    遍历结果 (按卡玛比率排序)")
    print("🏆" * 20)
    print()
    
    表头 = f"{'排名':<4} {'杠杆Z':<6} {'名义杠杆W':<10} {'年化收益率':<12} {'最大回撤':<12} {'卡玛比率':<10} {'交易次数':<10}"
    print(表头)
    print("-" * len(表头))
    
    for 序号, (索引, row) in enumerate(df_有效.iterrows(), 1):
        print(f"{序号:<4} {row['position_leverage']:<6.0f}x {row['nominal_leverage']:<10.4f} {row['年化收益率']:<12.1%} {row['最大回撤']:<12.1%} {row['卡玛比率']:<10.2f} {int(row['交易次数']):<10}")
    
    # 5. 保存结果
    时间戳 = datetime.now().strftime("%Y%m%d_%H%M%S")
    输出文件 = PROJECT_ROOT / f"策略仓库/八号香农策略/杠杆遍历结果_{时间戳}.csv"
    df_结果.to_csv(输出文件, index=False, encoding='utf-8-sig')
    print()
    print(f"📁 完整结果已保存: {输出文件}")
    
    # 6. 给出推荐
    最优 = df_有效.iloc[0]
    print()
    print("=" * 60)
    print("🎯 按卡玛比率推荐的最优杠杆:")
    print("=" * 60)
    print(f"   position_leverage = {最优['position_leverage']:.0f}")
    print(f"   名义杠杆 W = {最优['nominal_leverage']:.4f}")
    print()
    print(f"   预期年化收益: {最优['年化收益率']:.1%}")
    print(f"   预期最大回撤: {最优['最大回撤']:.1%}")
    print(f"   卡玛比率:     {最优['卡玛比率']:.2f}")
    print("=" * 60)
    
    # 7. 如果有爆仓，给出警告
    已爆仓 = df_结果[df_结果['是否爆仓'] == True]
    if len(已爆仓) > 0:
        第一个爆仓杠杆 = 已爆仓.iloc[0]['position_leverage']
        print()
        print(f"⚠️  警告: 杠杆 Z ≥ {第一个爆仓杠杆:.0f} 时策略会爆仓!")
        print(f"   建议最大杠杆: Z = {第一个爆仓杠杆 - 1:.0f} (留安全边际)")


if __name__ == "__main__":
    主函数()
