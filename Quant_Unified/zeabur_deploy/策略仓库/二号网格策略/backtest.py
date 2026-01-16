# 这个文件是二号网格策略的回测入口：加载配置、准备数据、运行模拟，并输出报告
import os
import sys
from pathlib import Path
import pandas as pd

# 将项目根目录和关键目录加入搜索路径
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

for folder in ['基础库', '服务', '策略仓库', '应用']:
    p = PROJECT_ROOT / folder
    if p.exists() and str(p) not in sys.path:
        sys.path.append(str(p))

from firm.grid_core.simulator import 网格回测模拟器 as GridBacktestSimulator
from firm.grid_core.portfolio_simulator import PortfolioBacktestSimulator
# 尝试导入策略列表，如果不存在则尝试导入旧的单个配置
try:
    from 策略仓库.二号网格策略.config_backtest import backtest_strategies
    has_strategy_list = True
except ImportError:
    from 策略仓库.二号网格策略.config_backtest import backtest_config
    backtest_strategies = [backtest_config]
    has_strategy_list = False

from 策略仓库.二号网格策略.program.step1_prepare_data import prepare_data
from 策略仓库.二号网格策略.program.step2_strategy import GridStrategy

def run_single_backtest(conf, index, total):
    """
    运行单个策略回测
    """
    print(f"\n========================================")
    print(f"      正在回测策略 {index}/{total}      ")
    print(f"========================================")
    print(f"交易对: {conf.symbol}")
    print(f"方向: {conf.direction_mode}")
    print(f"网格模式: {conf.interval_mode}")

    # 2. 准备数据
    print(f"\n[策略 {index}] 正在准备数据...")
    df = prepare_data(conf)
    
    if df.empty:
        print(f"错误: 策略 {index} 未找到数据或数据为空。")
        return None

    print(f"数据加载完成: {len(df)} 行")
    print(f"时间范围: {df['candle_begin_time'].iloc[0]} 至 {df['candle_begin_time'].iloc[-1]}")

    # 3. 初始化策略
    print(f"\n[策略 {index}] 正在初始化策略...")
    strategy = GridStrategy(conf)

    # 4. 初始化模拟器
    print(f"\n[策略 {index}] 正在设置模拟器...")
    simulator = GridBacktestSimulator(config=conf)
    simulator.set_strategy(strategy)
    simulator.load_data(df)

    # 5. 运行回测
    print(f"\n[策略 {index}] 正在运行回测...")
    try:
        simulator.run()
        
        # 提取回测结果
        acc = strategy.account_dict
        money = strategy.money
        pl_pair = acc.get("pair_profit", 0)
        pl_pos = acc.get("positions_profit", 0)
        pl_total = pl_pair + pl_pos
        
        return {
            "money": money,
            "pair_profit": pl_pair,
            "positions_profit": pl_pos,
            "total_profit": pl_total,
            "unit_return": (pl_total / money) if money else 0,
            "pairing_count": acc.get("pairing_count", 0),
            "max_drawdown": getattr(strategy, 'max_drawdown', 0)
        }
    except KeyboardInterrupt:
        print("\n用户中断了回测。")
        raise
    except Exception as e:
        print(f"\n回测过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    print("========================================")
    print("        2号网格策略 - Firm架构版        ")
    print("        (组合策略同步回测模式)          ")
    print("========================================")

    total_strategies = len(backtest_strategies)
    print(f"共检测到 {total_strategies} 个待回测策略配置。\n")
    
    # 切换到 Portfolio 模式
    strategies = []
    data_list = []
    
    print("正在准备组合回测数据...")
    for i, conf in enumerate(backtest_strategies):
        print(f"Loading data for Strategy {i+1}: {conf.symbol} ({conf.direction_mode})...")
        df = prepare_data(conf)
        if df.empty:
            print(f"Error: No data for Strategy {i+1}")
            continue # Skip this one? Or fail? Better fail to avoid partial portfolio.
            
        strategy = GridStrategy(conf)
        strategies.append(strategy)
        data_list.append(df)
        
    if not strategies:
        print("没有有效的策略可运行。")
        return

    # Initialize Portfolio Simulator
    simulator = PortfolioBacktestSimulator(backtest_strategies)
    simulator.set_strategies(strategies)
    simulator.load_data(data_list)
    
    # Run
    print("\n开始执行组合回测 (时间轴同步)...")
    try:
        simulator.run()
    except KeyboardInterrupt:
        print("\n用户中断了回测。")
    except Exception as e:
        print(f"\n回测过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
