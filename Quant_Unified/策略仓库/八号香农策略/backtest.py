# -*- coding: utf-8 -*-
"""
8号香农策略 - 向量化快速回测脚本

功能：
    1. 使用向量化操作加速回测 (比逐行循环快 10-50 倍)
    2. 调用统一回测指标模块，输出完整绩效指标
    3. 显示进度条，让用户知道回测进度

使用方法：
    在新终端窗口中运行 (不要和数据采集终端混用)：
    cd /Users/chuan/Desktop/xiangmu/客户端/Quant_Unified
    python -X utf8 策略仓库/八号香农策略/backtest.py

核心思路：
    香农再平衡 (Shannon's Demon):
    - 保持 50% 现金 + 50% 资产
    - 当价格波动后，自动调整仓位回到 50:50
    - 通过"低买高卖"在波动中获利
"""

import sys
import os
import pandas as pd
import numpy as np
import logging
from pathlib import Path

# ====== 自动计算项目根目录 ======
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# ====== 导入统一模块 ======
from 策略仓库.八号香农策略.config_live import Config
from 策略仓库.八号香农策略 import config_backtest as cfg  # 回测配置
from 策略仓库.八号香农策略.program.volatility import VolatilityEngine
from 策略仓库.八号香农策略.program.cprp import CPRPEngine

# 导入统一回测指标和进度条
from 基础库.common_core.backtest.metrics import 回测指标计算器
from 基础库.common_core.backtest.进度条 import 分块进度条
from 基础库.common_core.backtest.可视化 import 回测可视化

# ====== 日志配置 ======
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("Backtest")


# ====================================================================
# 数据加载
# ====================================================================

def 加载数据(文件路径: str) -> pd.DataFrame:
    """
    使用 h5py 直接读取 PyTables 格式的 HDF5 文件
    
    **绝对禁止使用模拟数据** - 用户明确禁止
    """
    if not 文件路径 or not os.path.exists(文件路径):
        raise FileNotFoundError(f"❌ 数据文件不存在: {文件路径}")
    
    logger.info(f"📂 正在加载数据文件: {文件路径}")
    
    import h5py
    import hdf5plugin  # 自动注册 BLOSC 等压缩插件
    
    with h5py.File(文件路径, 'r') as f:
        # PyTables 格式: 数据存储在 /klines/table
        if 'klines' in f and 'table' in f['klines']:
            table = f['klines']['table']
            data = table[:]
            
            df = pd.DataFrame({
                'open': data['open'],
                'high': data['high'],
                'low': data['low'],
                'close': data['close'],
                'volume': data['volume'],
                'candle_begin_time': pd.to_datetime(data['candle_begin_time_GMT8'], unit='ns')
            })
        else:
            raise ValueError(f"❌ H5 文件格式不正确，找不到 /klines/table")
    
    # 截取 start_date (2021-01-01)
    开始日期 = pd.Timestamp('2021-01-01')
    df = df[df['candle_begin_time'] >= 开始日期].copy()
    df = df.sort_values('candle_begin_time').reset_index(drop=True)
    
    logger.info(f"✅ 数据加载成功: {len(df):,} 条 | 起始: {df['candle_begin_time'].iloc[0]} | 结束: {df['candle_begin_time'].iloc[-1]}")
    return df


# ====================================================================
# 向量化波动率计算
# ====================================================================

def 向量化计算波动率(
    价格序列: np.ndarray,
    短期窗口: int = 60,
    长期窗口: int = 1440,
    ewma_alpha: float = 0.05
) -> dict:
    """
    向量化计算波动率相关指标
    
    这个函数把原来逐条处理的循环，改成一次性批量计算，速度提升 10-50 倍。
    
    类比：
        原来的方式 = 一张一张算工资单
        向量化方式 = 用 Excel 公式一次算完所有员工的工资
    """
    logger.info(f"🔢 向量化计算波动率 | 短周期: {短期窗口}m | 长周期: {长期窗口}m")
    
    # 1. 计算对数收益率 (向量化)
    对数收益率 = np.log(价格序列[1:] / 价格序列[:-1])
    对数收益率 = np.concatenate([[0], 对数收益率])  # 补齐第一个位置
    
    # 2. 计算滚动标准差 (用 pandas rolling，底层是 C 优化的)
    收益率序列 = pd.Series(对数收益率)
    
    短期波动率 = 收益率序列.rolling(window=短期窗口, min_periods=短期窗口).std().fillna(0).values
    长期波动率 = 收益率序列.rolling(window=长期窗口, min_periods=长期窗口).std().fillna(0).values
    
    # 3. 计算波动率比率 (安全除法，避免除零警告)
    比率 = np.ones(len(价格序列))
    有效索引 = 长期波动率 > 1e-9
    比率[有效索引] = 短期波动率[有效索引] / 长期波动率[有效索引]
    
    # 4. 计算 EWMA 波动率 (用 pandas ewm)
    ewma波动率 = 收益率序列.ewm(alpha=ewma_alpha, min_periods=短期窗口).std().fillna(0).values
    
    # 5. 计算 EWMA 价格 (平滑中心价)
    价格序列_pd = pd.Series(价格序列)
    ewma价格 = 价格序列_pd.ewm(alpha=ewma_alpha, min_periods=1).mean().values
    
    return {
        '对数收益率': 对数收益率,
        '短期波动率': 短期波动率,
        '长期波动率': 长期波动率,
        '波动率比率': 比率,
        'EWMA波动率': ewma波动率,
        'EWMA价格': ewma价格,
    }


def 判定市场状态(
    波动率比率: np.ndarray,
    spike阈值: float = 1.5,
    crush阈值: float = 0.5
) -> np.ndarray:
    """
    向量化判定市场状态
    
    状态说明：
        0 = NORMAL (正常波动)
        1 = SPIKE (暴涨暴跌，波动放大)
        2 = CRUSH (波动枯竭，极度平静)
    """
    状态 = np.zeros(len(波动率比率), dtype=np.int8)
    状态[波动率比率 > spike阈值] = 1  # SPIKE
    状态[波动率比率 < crush阈值] = 2  # CRUSH
    return 状态


# ====================================================================
# 向量化 CPRP 再平衡模拟
# ====================================================================

def 向量化回测(
    价格序列: np.ndarray,
    时间序列: np.ndarray,
    初始资金: float = 1000.0,
    目标持仓比例: float = 0.5,
    短期窗口: int = 60,
    长期窗口: int = 1440,
    ewma_alpha: float = 0.05,
    spike阈值: float = 1.5,
    crush阈值: float = 0.5,
    # ====== 与实盘统一的参数 ======
    vol_k_factor: float = 1.0,       # 波动率K系数 (网格宽度 = EWMA_Vol * K)
    min_grid_width_bps: float = 5.0, # 最小网格宽度 (基点)
    spike宽度倍数: float = 1.5,
    crush宽度倍数: float = 0.8,
    杠杆倍数: float = 1.0,  # 新增杠杆参数
) -> dict:
    """
    向量化香农再平衡回测
    
    原理：
        1. 在「总资产」维度做 CPRP：维持 目标持仓比例 的 ETH/现金配比
        2. 杠杆使用「借贷杠杆」建模：
           - 借款 = 初始资金 * (杠杆倍数 - 1)
           - 总资产 = 现金 + ETH市值
           - 权益 = 总资产 - 借款
        2. 每个周期检查是否需要再平衡
        3. 当价格偏离中心价超过网格宽度时，执行买入/卖出
        4. 权益 <= 0 时触发爆仓
    
    向量化优化：
        - 预先计算所有波动率、中心价、网格宽度
        - 只在最后统计权益曲线时遍历（必须的，因为仓位有路径依赖）
    """
    n = len(价格序列)
    
    if 杠杆倍数 < 1.0:
        raise ValueError(f"杠杆倍数 必须 >= 1.0, 当前={杠杆倍数}")

    初始总资产 = 初始资金 * 杠杆倍数
    借款 = 初始总资产 - 初始资金
    logger.info(
        f"⚙️ 杠杆回测配置: 初始资金={初始资金:.2f}, 杠杆={杠杆倍数:.2f}x | "
        f"借款={借款:.2f} | 初始总资产={初始总资产:.2f} | Target={目标持仓比例:.2f}"
    )
    
    # ========== 步骤1: 向量化计算指标 ==========
    波动率结果 = 向量化计算波动率(价格序列, 短期窗口, 长期窗口, ewma_alpha)
    市场状态 = 判定市场状态(波动率结果['波动率比率'], spike阈值, crush阈值)
    
    # 计算动态网格宽度 (与实盘逻辑统一)
    # 基础宽度 = EWMA波动率 * vol_k_factor
    基础网格宽度 = 波动率结果['EWMA波动率'] * vol_k_factor
    
    # 应用物理下限
    最小宽度 = min_grid_width_bps / 10000.0  # 转换为小数
    基础网格宽度 = np.maximum(基础网格宽度, 最小宽度)
    
    # 根据市场状态调整
    网格宽度 = 基础网格宽度.copy()
    网格宽度[市场状态 == 1] = 基础网格宽度[市场状态 == 1] * spike宽度倍数  # SPIKE 时放宽
    网格宽度[市场状态 == 2] = 基础网格宽度[市场状态 == 2] * crush宽度倍数  # CRUSH 时收窄
    
    # 中心价 = 0.5 * 当前价 + 0.5 * EWMA价格
    中心价 = 0.5 * 价格序列 + 0.5 * 波动率结果['EWMA价格']
    
    # ========== 步骤2: 模拟交易 (这部分必须顺序执行) ==========
    # 初始化账户
    起始价格 = 价格序列[0]
    
    # 初始建仓：在「总资产」上按目标比例配平；借款固定不随交易变化（不计利息/资金费）
    eth数量 = (初始总资产 * 目标持仓比例) / 起始价格
    现金 = 初始总资产 - (eth数量 * 起始价格)
    
    # 权益曲线
    权益曲线 = np.zeros(n)
    
    # 交易计数
    交易次数 = 0
    
    # 使用 numba 加速的话更快，这里先用纯 Python 循环
    for i in range(n):
        p = 价格序列[i]
        总资产 = 现金 + eth数量 * p
        权益 = 总资产 - 借款
        权益曲线[i] = 权益
        
        # 跳过最后一个周期 (无法成交)
        if i >= n - 1:
            continue
        
        if 权益 <= 0:
            logger.warning(f"❌ 账户已爆仓 (Liquidation) @ index {i}, Price={p:.2f}")
            权益曲线[i:] = 0  # 后续全部为0
            break  # 停止回测
        
        # 计算当前 ETH 持仓价值占比
        eth价值 = eth数量 * p
        当前持仓比例 = eth价值 / 总资产 if 总资产 > 0 else 0.0
        
        # 计算偏离 (相对于目标持仓比例；杠杆只影响借款与总资产规模)
        偏离 = 当前持仓比例 - 目标持仓比例
        
        # 判断是否需要再平衡 (偏离超过网格宽度)
        当前网格宽度 = 网格宽度[i]
        
        if abs(偏离) > 当前网格宽度:
            # 需要再平衡
            # 执行交易 (使用下一根 K 线价格模拟成交)，以「下一根成交前的总资产」计算目标，避免现金为负
            下一价格 = 价格序列[i + 1]
            预估总资产_下根 = 现金 + eth数量 * 下一价格
            目标eth价值 = 预估总资产_下根 * 目标持仓比例
            delta_eth价值 = 目标eth价值 - (eth数量 * 下一价格)
            delta_eth = delta_eth价值 / 下一价格
            
            if delta_eth > 0:
                # 买入 ETH
                买入成本 = delta_eth * 下一价格
                if 买入成本 > 现金:  # 仅处理浮点误差的极小超出
                    delta_eth = 现金 / 下一价格
                    买入成本 = delta_eth * 下一价格
                if delta_eth > 0:
                    现金 -= 买入成本
                    eth数量 += delta_eth
                    交易次数 += 1
            else:
                # 卖出 ETH
                卖出数量 = min(abs(delta_eth), eth数量)
                if 卖出数量 > 0:
                    eth数量 -= 卖出数量
                    现金 += 卖出数量 * 下一价格
                    交易次数 += 1
    
    # ========== 步骤3: 返回结果 ==========
    return {
        '权益曲线': 权益曲线,
        '时间序列': 时间序列,
        '价格序列': 价格序列,
        '市场状态': 市场状态,
        '网格宽度': 网格宽度,
        '初始资金': 初始资金,
        '杠杆倍数': 杠杆倍数,
        '借款': 借款,
        '交易次数': 交易次数,
        '波动率结果': 波动率结果,
    }


# ====================================================================
# 主函数
# ====================================================================

def 运行回测(显示图表: bool = True):
    """主回测函数"""
    print()
    print("🚀" * 20)
    print("    8号香农策略 - 向量化快速回测")
    print("🚀" * 20)
    print()
    
    # 创建分块进度条
    进度 = 分块进度条(总步骤=5, 描述="回测进度")
    
    try:
        # ====== 1. 配置 ======
        # 从 config_backtest.py 读取配置
        config = Config(
            vol_short_window=cfg.vol_short_window,
            vol_long_window=cfg.vol_long_window,
            target_ratio=cfg.target_ratio,
            regime_spike_threshold=cfg.regime_spike_threshold,
            regime_crush_threshold=cfg.regime_crush_threshold,
            verbose_regime_switch=cfg.verbose_regime_switch,
            vol_ewma_alpha=cfg.vol_ewma_alpha,
        )
        进度.完成步骤("加载配置")
        
        # ====== 2. 加载数据 ======
        数据文件 = cfg.data_file  # 从配置读取数据文件路径
        df = 加载数据(数据文件)
        价格 = df['close'].values
        时间 = df['candle_begin_time'].values
        进度.完成步骤("加载数据")
        
        # ====== 3. 向量化回测 ======
        logger.info(f"⚡ 开始向量化回测 | 数据量: {len(价格):,} 条")
        
        结果 = 向量化回测(
            价格序列=价格,
            时间序列=时间,
            初始资金=cfg.initial_capital,
            目标持仓比例=cfg.target_ratio,
            短期窗口=cfg.vol_short_window,
            长期窗口=cfg.vol_long_window,
            ewma_alpha=cfg.vol_ewma_alpha,
            spike阈值=cfg.regime_spike_threshold,
            crush阈值=cfg.regime_crush_threshold,
            # 与实盘统一的参数
            vol_k_factor=cfg.vol_k_factor,
            min_grid_width_bps=cfg.min_grid_width_bps,
            # 新增杠杆参数
            杠杆倍数=getattr(cfg, 'leverage', 1.0),
        )
        进度.完成步骤("执行回测")
        
        # ====== 4. 计算并输出指标 ======
        计算器 = 回测指标计算器(
            权益曲线=结果['权益曲线'],
            初始资金=cfg.initial_capital,
            时间戳=结果['时间序列'],
            周期每年数量=525600,  # 分钟级
        )
        
        # 打印完整报告
        指标结果 = 计算器.打印报告(策略名称="8号香农策略 (CPRP)")
        进度.完成步骤("生成报告")
        
        # 额外信息
        print(f"🔄 总交易次数: {结果['交易次数']}")
        
        # 状态分布统计
        市场状态 = 结果['市场状态']
        状态名称 = {0: 'NORMAL', 1: 'SPIKE', 2: 'CRUSH'}
        print("\n📊 市场状态分布:")
        for 状态码 in [0, 1, 2]:
            数量 = np.sum(市场状态 == 状态码)
            占比 = 数量 / len(市场状态) * 100
            print(f"   {状态名称[状态码]}: {数量:,} ({占比:.1f}%)")
        
        # ====== 5. 生成可视化图表 ======
        if 显示图表:
            可视化器 = 回测可视化(
                权益曲线=结果['权益曲线'],
                时间序列=结果['时间序列'],
                初始资金=cfg.initial_capital,
                价格序列=结果['价格序列'],
                显示图表=True,  # 单次回测自动打开浏览器
                保存路径=PROJECT_ROOT / "策略仓库/八号香农策略"
            )
            可视化器.生成报告(策略名称="8号香农策略 (CPRP)")
        
        进度.结束()
        
    except Exception as e:
        进度.结束()
        logger.error(f"❌ 回测失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="8号香农策略回测")
    parser.add_argument("--no-chart", action="store_true", help="不显示图表（批量遍历时使用）")
    args = parser.parse_args()
    
    运行回测(显示图表=not args.no_chart)
