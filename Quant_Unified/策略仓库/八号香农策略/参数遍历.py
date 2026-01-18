# -*- coding: utf-8 -*-
"""
8号香农策略 - 参数遍历优化脚本

目标：
    用“执行级回测”（贴近实盘：挂单被价格撞上才成交）做参数遍历，
    找出卡玛比率最高（年化收益 / 最大回撤）的参数组合。

重点优化参数：
    1. vol_short_window：短期波动率窗口（分钟），影响“反应速度”
    2. vol_long_window：长期波动率窗口（分钟），影响“基准稳定性”
    3. vol_k_factor：网格宽度系数（宽度 = EWMA波动率 * K）
    4. min_grid_width_bps：最小网格宽度下限（bp：基点；1bp=0.01%）

使用方法：
    cd /Users/chuan/Desktop/xiangmu/客户端/Quant_Unified
    python -X utf8 策略仓库/八号香农策略/参数遍历.py
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
from 策略仓库.八号香农策略 import config_backtest as cfg
from 基础库.common_core.backtest.metrics import 回测指标计算器
from 基础库.common_core.backtest.进度条 import 回测进度条
from 策略仓库.八号香农策略.program.leverage_model import resolve_leverage_spec


# ============================================================
# 参数空间定义
# ============================================================

# 🎯 重点优化参数
参数空间 = {
    # 短期波动率窗口 (分钟)
    # 越短 = 对波动越敏感，可能过度反应
    # 越长 = 反应越慢，可能错过机会
    'vol_short_window': [30, 60, 120, 240],
    
    # 长期波动率窗口 (分钟)
    # 越短 = 基准更活跃
    # 越长 = 基准更稳定
    'vol_long_window': [720, 1440, 2880],
    
    # vol_k_factor：把“EWMA 波动率”放大/缩小成网格宽度
    # 越大 = 网格越宽，交易越少
    'vol_k_factor': [0.8, 1.0, 1.2, 1.5],
    
    # min_grid_width_bps：最小网格宽度下限（bp=基点）
    # 例如 1bp = 0.01% = 0.0001
    'min_grid_width_bps': [0.5, 1.0, 2.0, 5.0],
}

# 计算总组合数
总组合数 = 1
for v in 参数空间.values():
    总组合数 *= len(v)
print(f"📊 参数空间总组合数: {总组合数}")


# ============================================================
# 单次回测包装函数
# ============================================================

def _读取分钟K线切片到数组(
    文件路径: str,
    *,
    开始日期: str,
    结束日期: str | None,
    预热分钟: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """
    从 HDF5 文件读取分钟 K 线（/klines/table），并截取到：
        [开始日期 - 预热分钟, 结束日期]
    返回：
        开/高/低/收（float64 连续数组） + 时间戳ns（int64） + 交易起始索引

    说明：
        - 这里不用 pandas 读整表，是为了省内存、提速度（参数遍历会跑很多次）。
        - 仍然是真实数据，不是模拟数据。
    """
    import h5py
    import hdf5plugin  # noqa: F401  # 注册 HDF5 压缩插件（否则可能读不出来）

    文件路径 = str(文件路径)
    if not 文件路径:
        raise ValueError("数据文件路径不能为空")

    开始_ns = int(pd.Timestamp(开始日期).value)
    预热开始_ns = int((pd.Timestamp(开始日期) - pd.Timedelta(minutes=int(预热分钟))).value)
    结束_ns = int(pd.Timestamp(结束日期).value) if 结束日期 else None

    with h5py.File(文件路径, "r") as f:
        dset = f["klines"]["table"]
        时间全量 = dset["candle_begin_time_GMT8"][:]

        slice_start = int(np.searchsorted(时间全量, 预热开始_ns))
        slice_end = int(np.searchsorted(时间全量, 结束_ns, side="right")) if 结束_ns else int(len(时间全量))

        data = dset[slice_start:slice_end]

    时间 = np.ascontiguousarray(data["candle_begin_time_GMT8"].astype(np.int64))
    开 = np.ascontiguousarray(data["open"].astype(np.float64))
    高 = np.ascontiguousarray(data["high"].astype(np.float64))
    低 = np.ascontiguousarray(data["low"].astype(np.float64))
    收 = np.ascontiguousarray(data["close"].astype(np.float64))

    交易起始索引 = int(np.searchsorted(时间, 开始_ns))
    交易起始索引 = int(max(2, 交易起始索引))
    if len(收) - 交易起始索引 < 10:
        raise ValueError("交易起始点之后数据太少，无法做参数遍历（请检查日期范围/数据文件）")

    return 开, 高, 低, 收, 时间, 交易起始索引


def 执行单次回测(
    参数组合: dict,
    *,
    开: np.ndarray,
    高: np.ndarray,
    低: np.ndarray,
    收: np.ndarray,
    交易起始索引: int,
    ewma_vol_in: np.ndarray,
    ewma_price_in: np.ndarray,
    regime_in: np.ndarray,
    初始资金: float,
    目标持仓比例: float,
    width_multiplier_spike: float,
    width_multiplier_crush: float,
    grid_layers: int,
    min_qty: float,
    force_order_band: float,
    update_threshold_ratio: float,
    position_leverage_z: float,
) -> dict:
    """
    执行单次回测并返回结果
    
    参数：
        参数组合: dict, 包含 vol_short_window / vol_long_window / vol_k_factor / min_grid_width_bps
    
    返回：
        dict: 包含参数和所有指标的结果
    """
    try:
        vol_short = int(参数组合["vol_short_window"])
        vol_long = int(参数组合["vol_long_window"])
        vol_k_factor = float(参数组合["vol_k_factor"])
        min_grid_width_bps = float(参数组合["min_grid_width_bps"])

        权益曲线, _, _, 成交次数 = 香农回测._执行级回测_核心循环_预计算指标(
            开,
            高,
            低,
            收,
            int(交易起始索引),
            float(初始资金),
            float(目标持仓比例),
            ewma_vol_in,
            ewma_price_in,
            regime_in,
            float(vol_k_factor),
            float(width_multiplier_spike),
            float(width_multiplier_crush),
            float(min_grid_width_bps),
            int(grid_layers),
            float(min_qty),
            float(force_order_band),
            float(position_leverage_z),
            float(update_threshold_ratio),
        )

        是否爆仓 = bool(权益曲线[-1] <= 0 or np.any(权益曲线 <= 0))
        if 是否爆仓:
            return {
                "vol_short_window": vol_short,
                "vol_long_window": vol_long,
                "vol_k_factor": vol_k_factor,
                "min_grid_width_bps": min_grid_width_bps,
                "年化收益率": -999,
                "最大回撤": -999,
                "卡玛比率": -999,
                "夏普比率": -999,
                "总收益率": -999,
                "成交次数": int(成交次数),
                "是否爆仓": True,
            }

        # 计算指标
        计算器 = 回测指标计算器(
            权益曲线=权益曲线,
            初始资金=float(初始资金),
            时间戳=None,  # 参数遍历不需要转时间戳（省很多时间）
            周期每年数量=525600,
        )
        指标 = 计算器.计算全部指标()
        
        return {
            # 参数
            "vol_short_window": vol_short,
            "vol_long_window": vol_long,
            "vol_k_factor": vol_k_factor,
            "min_grid_width_bps": min_grid_width_bps,
            # 核心指标
            "年化收益率": 指标.年化收益率,
            "最大回撤": 指标.最大回撤,  # 负数
            "卡玛比率": 指标.卡玛比率,
            "夏普比率": 指标.夏普比率,
            "总收益率": 指标.总收益率,
            "成交次数": int(成交次数),
            "是否爆仓": False,
        }
    except Exception as e:
        return {
            "vol_short_window": 参数组合.get("vol_short_window"),
            "vol_long_window": 参数组合.get("vol_long_window"),
            "vol_k_factor": 参数组合.get("vol_k_factor"),
            "min_grid_width_bps": 参数组合.get("min_grid_width_bps"),
            "年化收益率": -999,
            "最大回撤": -999,
            "卡玛比率": -999,
            "夏普比率": -999,
            "总收益率": -999,
            "成交次数": 0,
            "是否爆仓": True,
            "错误": str(e),
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
    
    # 1) 加载数据（真实 HDF5，不是模拟数据）
    数据文件 = str(getattr(cfg, "data_file", "")).strip()
    if not 数据文件:
        raise ValueError("config_backtest.py 里没有配置 data_file")

    开始日期 = str(getattr(cfg, "data_start_date", "2021-01-01"))
    结束日期 = None  # 参数遍历默认跑到数据末尾

    最大预热窗口 = max(max(参数空间["vol_short_window"]), max(参数空间["vol_long_window"]))
    预热分钟 = int(最大预热窗口) + 10

    print(f"📂 加载数据: {数据文件}")
    print(f"   - 回测开始日期: {开始日期}")
    print(f"   - 预热分钟数: {预热分钟}")

    开, 高, 低, 收, 时间, 交易起始索引 = _读取分钟K线切片到数组(
        数据文件,
        开始日期=开始日期,
        结束日期=结束日期,
        预热分钟=预热分钟,
    )
    print(f"✅ 数据加载完成: {len(收):,} 条 | 交易起始索引={交易起始索引}")

    # 2) 固定配置（与回测/实盘对齐）
    初始资金 = float(getattr(cfg, "initial_capital", 1000.0))
    目标比例 = float(getattr(cfg, "target_ratio", 0.5))
    vol_ewma_alpha = float(getattr(cfg, "vol_ewma_alpha", 0.05))
    spike阈值 = float(getattr(cfg, "regime_spike_threshold", 1.5))
    crush阈值 = float(getattr(cfg, "regime_crush_threshold", 0.5))
    width_multiplier_spike = float(getattr(cfg, "width_multiplier_spike", 1.5))
    width_multiplier_crush = float(getattr(cfg, "width_multiplier_crush", 0.8))
    grid_layers = int(getattr(cfg, "grid_layers", 3))
    min_qty = float(getattr(cfg, "min_qty", 0.007))
    force_order_band = float(getattr(cfg, "force_order_band", 0.1))
    update_threshold_ratio = float(getattr(cfg, "update_threshold_ratio", 0.05))

    杠杆信息 = resolve_leverage_spec(
        cfg,
        target_ratio=目标比例,
        max_position_leverage=getattr(cfg, "max_position_leverage", None),
    )
    position_leverage_z = float(杠杆信息.position_leverage)
    
    # 3) 遍历回测（关键优化：同一组 vol_short/vol_long 只预计算一次指标）
    短窗列表 = list(参数空间["vol_short_window"])
    长窗列表 = list(参数空间["vol_long_window"])
    K系数列表 = list(参数空间["vol_k_factor"])
    最小宽度bps列表 = list(参数空间["min_grid_width_bps"])

    总组合 = len(短窗列表) * len(长窗列表) * len(K系数列表) * len(最小宽度bps列表)
    print(f"🎯 开始遍历 {总组合} 种参数组合...")
    print()

    结果列表 = []

    with 回测进度条(总数=总组合, 描述="参数遍历") as 进度:
        for vol_short in 短窗列表:
            for vol_long in 长窗列表:
                # 预计算：只跟窗口/阈值有关，跟 K 系数/最小宽度无关
                ewma_vol_in, ewma_price_in, regime_in = 香农回测._预计算_波动率状态序列(
                    收,
                    int(交易起始索引),
                    int(vol_short),
                    int(vol_long),
                    float(vol_ewma_alpha),
                    float(spike阈值),
                    float(crush阈值),
                )

                for vol_k_factor in K系数列表:
                    for min_grid_width_bps in 最小宽度bps列表:
                        参数 = {
                            "vol_short_window": int(vol_short),
                            "vol_long_window": int(vol_long),
                            "vol_k_factor": float(vol_k_factor),
                            "min_grid_width_bps": float(min_grid_width_bps),
                        }
                        结果 = 执行单次回测(
                            参数,
                            开=开,
                            高=高,
                            低=低,
                            收=收,
                            交易起始索引=交易起始索引,
                            ewma_vol_in=ewma_vol_in,
                            ewma_price_in=ewma_price_in,
                            regime_in=regime_in,
                            初始资金=初始资金,
                            目标持仓比例=目标比例,
                            width_multiplier_spike=width_multiplier_spike,
                            width_multiplier_crush=width_multiplier_crush,
                            grid_layers=grid_layers,
                            min_qty=min_qty,
                            force_order_band=force_order_band,
                            update_threshold_ratio=update_threshold_ratio,
                            position_leverage_z=position_leverage_z,
                        )
                        结果列表.append(结果)

                        当前最优 = max(
                            [r for r in 结果列表 if r.get("卡玛比率", -999) > -100],
                            key=lambda x: x["卡玛比率"],
                            default=None,
                        )
                        if 当前最优:
                            进度.设置后缀(
                                最优卡玛=f"{当前最优['卡玛比率']:.2f}",
                                最优回撤=f"{当前最优['最大回撤']:.1%}",
                            )

                        进度.更新(1)
    
    # 4. 整理结果
    df_结果 = pd.DataFrame(结果列表)
    
    # 过滤无效结果
    df_有效 = df_结果[df_结果["卡玛比率"] > -100].copy()
    
    # 按卡玛比率排序
    df_有效 = df_有效.sort_values("卡玛比率", ascending=False)
    
    # 5. 显示 Top 10 结果
    print()
    print("🏆" * 20)
    print("    最优参数组合 Top 10 (按卡玛比率排序)")
    print("🏆" * 20)
    print()
    
    print(f"{'排名':<4} {'短窗':<6} {'长窗':<6} {'K系数':<6} {'min_bps':<8} {'年化收益':<10} {'最大回撤':<10} {'卡玛比率':<10} {'成交次数':<10}")
    print("-" * 90)
    
    for i, row in df_有效.head(10).iterrows():
        排名 = df_有效.index.get_loc(i) + 1
        print(
            f"{排名:<4} "
            f"{int(row['vol_short_window']):<6} {int(row['vol_long_window']):<6} "
            f"{row['vol_k_factor']:<6.2f} {row['min_grid_width_bps']:<8.2f} "
            f"{row['年化收益率']:<10.1%} {row['最大回撤']:<10.1%} {row['卡玛比率']:<10.2f} {int(row['成交次数']):<10}"
        )
    
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
    print(f"  vol_short_window     = {int(最优['vol_short_window'])}")
    print(f"  vol_long_window      = {int(最优['vol_long_window'])}")
    print(f"  vol_k_factor         = {float(最优['vol_k_factor']):.4f}")
    print(f"  min_grid_width_bps   = {float(最优['min_grid_width_bps']):.2f}")
    print()
    print(f"  预期年化收益: {最优['年化收益率']:.1%}")
    print(f"  预期最大回撤: {最优['最大回撤']:.1%}")
    print(f"  卡玛比率:     {最优['卡玛比率']:.2f}")
    print("=" * 60)
    
    # 8. 找出回撤 < 30% 的最优参数 (适合加杠杆)
    df_低回撤 = df_有效[df_有效["最大回撤"] > -0.30]  # 回撤小于30%
    if len(df_低回撤) > 0:
        最优低回撤 = df_低回撤.iloc[0]
        print()
        print("💪 适合加杠杆的低回撤参数 (回撤 < 30%):")
        print("=" * 60)
        print(f"  vol_short_window   = {int(最优低回撤['vol_short_window'])}")
        print(f"  vol_long_window    = {int(最优低回撤['vol_long_window'])}")
        print(f"  vol_k_factor       = {float(最优低回撤['vol_k_factor']):.4f}")
        print(f"  min_grid_width_bps = {float(最优低回撤['min_grid_width_bps']):.2f}")
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
