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
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# ====== 自动计算项目根目录 ======
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# 导入执行级回测核心（贴近实盘撮合）
from 策略仓库.八号香农策略 import backtest as 香农回测
from 基础库.common_core.backtest.metrics import 回测指标计算器
from 策略仓库.八号香农策略 import config_backtest as cfg
from 策略仓库.八号香农策略.program.leverage_model import nominal_from_position_leverage


# ============================================================
# 参数配置
# ============================================================

# 🎯 遍历范围：position_leverage 从 1 到 30
杠杆范围 = list(range(1, 31))  # [1, 2, 3, ..., 30]

print(f"📊 将遍历的杠杆参数: {杠杆范围[0]} ~ {杠杆范围[-1]} (共 {len(杠杆范围)} 个)")


# ============================================================
# 单次回测函数
# ============================================================

def 单次杠杆回测(杠杆倍数: float, 固定参数: dict) -> dict:
    """
    用指定的杠杆倍数执行一次回测
    
    参数：
        杠杆倍数: float, position_leverage (逐笔杠杆 Z)
        固定参数: dict, 预先准备好的“不会随杠杆变化”的数据与配置（避免重复计算）
    
    返回：
        dict: 包含杠杆参数、所有指标、以及是否爆仓的结果
    """
    try:
        # 执行级回测：复用“预计算指标”路径（更快，口径与增量一致）
        权益曲线, _, _, 成交次数 = 香农回测._执行级回测_核心循环_预计算指标(
            固定参数["开"],
            固定参数["高"],
            固定参数["低"],
            固定参数["收"],
            int(固定参数["交易起始索引"]),
            float(固定参数["初始资金"]),
            float(固定参数["目标持仓比例"]),
            固定参数["ewma_vol_in"],
            固定参数["ewma_price_in"],
            固定参数["regime_in"],
            float(固定参数["vol_k_factor"]),
            float(固定参数["width_multiplier_spike"]),
            float(固定参数["width_multiplier_crush"]),
            float(固定参数["min_grid_width_bps"]),
            int(固定参数["grid_layers"]),
            float(固定参数["min_qty"]),
            float(固定参数["force_order_band"]),
            float(杠杆倍数),
            float(固定参数["update_threshold_ratio"]),
        )

        # 检查是否爆仓 (权益曲线变成 0)
        权益末值 = float(权益曲线[-1])
        是否爆仓 = bool(权益末值 <= 0 or np.any(权益曲线 <= 0))
        
        if 是否爆仓:
            # 爆仓了，找到第一个爆仓位置
            爆仓位置 = np.where(权益曲线 <= 0)[0]
            爆仓时间索引 = 爆仓位置[0] if len(爆仓位置) > 0 else -1
            return {
                'position_leverage': 杠杆倍数,
                'nominal_leverage': float(nominal_from_position_leverage(杠杆倍数, 固定参数["目标持仓比例"])),
                '年化收益率': None,  # 爆仓无意义
                '最大回撤': None,
                '卡玛比率': None,
                '夏普比率': None,
                '总收益率': None,
                '交易次数': int(成交次数),
                '是否爆仓': True,
                '爆仓时间索引': 爆仓时间索引,
            }
        
        # 正常完成，计算指标
        计算器 = 回测指标计算器(
            权益曲线=权益曲线,
            初始资金=float(固定参数["初始资金"]),
            时间戳=None,  # 杠杆遍历只要收益/回撤即可，不必反复转时间戳
            周期每年数量=525600,
        )
        指标 = 计算器.计算全部指标()
        
        return {
            'position_leverage': 杠杆倍数,
            'nominal_leverage': float(nominal_from_position_leverage(杠杆倍数, 固定参数["目标持仓比例"])),
            '年化收益率': 指标.年化收益率,
            '最大回撤': 指标.最大回撤,  # 负数
            '卡玛比率': 指标.卡玛比率,
            '夏普比率': 指标.夏普比率,
            '总收益率': 指标.总收益率,
            '交易次数': int(成交次数),
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
    
    # 1) 加载数据（真实 HDF5，不是模拟数据）
    数据文件 = str(getattr(cfg, "data_file", "")).strip()
    if not 数据文件:
        raise ValueError("config_backtest.py 里没有配置 data_file")

    开始日期 = str(getattr(cfg, "data_start_date", "2021-01-01"))
    vol_short = int(getattr(cfg, "vol_short_window", 60))
    vol_long = int(getattr(cfg, "vol_long_window", 1440))
    预热分钟 = int(max(vol_short, vol_long) + 10)

    print(f"📂 加载数据: {数据文件}")
    print(f"   - 回测开始日期: {开始日期}")
    print(f"   - 预热分钟数: {预热分钟}")

    import h5py
    import hdf5plugin  # noqa: F401

    开始_ns = int(pd.Timestamp(开始日期).value)
    预热开始_ns = int((pd.Timestamp(开始日期) - pd.Timedelta(minutes=预热分钟)).value)

    with h5py.File(数据文件, "r") as f:
        dset = f["klines"]["table"]
        时间全量 = dset["candle_begin_time_GMT8"][:]
        slice_start = int(np.searchsorted(时间全量, 预热开始_ns))
        data = dset[slice_start:]

    时间 = np.ascontiguousarray(data["candle_begin_time_GMT8"].astype(np.int64))
    开 = np.ascontiguousarray(data["open"].astype(np.float64))
    高 = np.ascontiguousarray(data["high"].astype(np.float64))
    低 = np.ascontiguousarray(data["low"].astype(np.float64))
    收 = np.ascontiguousarray(data["close"].astype(np.float64))

    交易起始索引 = int(max(2, np.searchsorted(时间, 开始_ns)))
    print(f"✅ 数据加载完成: {len(收):,} 条 | 交易起始索引={交易起始索引}")
    print()

    # 2) 预计算指标（这一步与杠杆无关，可以只做一次）
    初始资金 = float(getattr(cfg, "initial_capital", 1000.0))
    目标比例 = float(getattr(cfg, "target_ratio", 0.5))
    vol_ewma_alpha = float(getattr(cfg, "vol_ewma_alpha", 0.05))
    spike阈值 = float(getattr(cfg, "regime_spike_threshold", 1.5))
    crush阈值 = float(getattr(cfg, "regime_crush_threshold", 0.5))

    ewma_vol_in, ewma_price_in, regime_in = 香农回测._预计算_波动率状态序列(
        收,
        int(交易起始索引),
        vol_short,
        vol_long,
        float(vol_ewma_alpha),
        float(spike阈值),
        float(crush阈值),
    )

    # 3) 固定配置（宽度/挂单结构等）
    vol_k_factor = float(getattr(cfg, "vol_k_factor", 1.0))
    min_grid_width_bps = float(getattr(cfg, "min_grid_width_bps", 1.0))
    width_multiplier_spike = float(getattr(cfg, "width_multiplier_spike", 1.5))
    width_multiplier_crush = float(getattr(cfg, "width_multiplier_crush", 0.8))
    grid_layers = int(getattr(cfg, "grid_layers", 3))
    min_qty = float(getattr(cfg, "min_qty", 0.007))
    force_order_band = float(getattr(cfg, "force_order_band", 0.1))
    update_threshold_ratio = float(getattr(cfg, "update_threshold_ratio", 0.05))

    # 把这些“不会随杠杆变化”的东西打包，传进 单次杠杆回测（避免全局变量散落）
    固定参数 = {
        "开": 开,
        "高": 高,
        "低": 低,
        "收": 收,
        "交易起始索引": 交易起始索引,
        "初始资金": 初始资金,
        "目标持仓比例": 目标比例,
        "ewma_vol_in": ewma_vol_in,
        "ewma_price_in": ewma_price_in,
        "regime_in": regime_in,
        "vol_k_factor": vol_k_factor,
        "min_grid_width_bps": min_grid_width_bps,
        "width_multiplier_spike": width_multiplier_spike,
        "width_multiplier_crush": width_multiplier_crush,
        "grid_layers": grid_layers,
        "min_qty": min_qty,
        "force_order_band": force_order_band,
        "update_threshold_ratio": update_threshold_ratio,
    }
    
    # 2. 遍历杠杆参数
    print(f"🔍 开始遍历杠杆参数 [{杠杆范围[0]} ~ {杠杆范围[-1]}]...")
    print("-" * 80)
    
    结果列表 = []
    
    for 杠杆 in 杠杆范围:
        print(f"   🧪 测试杠杆 Z = {杠杆:2}x ... ", end="", flush=True)
        
        结果 = 单次杠杆回测(杠杆, 固定参数)
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
