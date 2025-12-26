"""
【3号对冲策略】回测入口：
1. 加载配置并准备数据
2. 逐根K线驱动引擎，模拟网格触发与账本平劣
3. 输出基础评价指标与资金曲线
"""

import sys
from pathlib import Path
import pandas as pd

# 将项目根目录加入搜索路径
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

for folder in ['基础库', '服务', '策略仓库', '应用']:
    p = PROJECT_ROOT / folder
    if p.exists() and str(p) not in sys.path:
        sys.path.append(str(p))

from 策略仓库.三号对冲策略.config_backtest import backtest_strategies
from 策略仓库.三号对冲策略.program.engine import HedgeStrategy
# 复用二号策略的数据准备模块
from 策略仓库.二号网格策略.program.step1_prepare_data import prepare_data
from common_core.backtest.figure import draw_equity_curve_plotly


def run_one(conf):
    df = prepare_data(conf)
    if df.empty:
        print(f"❌ 数据为空: {conf.symbol}")
        return None

    strat = HedgeStrategy(conf)
    equity_curve = []
    times = []
    price_list = []

    # 初始权益估算：按 money 作为对冲账户基准
    初始权益 = float(conf.money)
    当前权益 = 初始权益

    # 逐根K线，以收盘价驱动
    for _, row in df.iterrows():
        t = row['candle_begin_time']
        close = float(row['close'])
        strat.处理价格(close)
        times.append(t)
        price_list.append(close)

        # 权益 = 初始资金 + 已实现利润 + 浮动盈亏
        浮动盈亏 = strat.计算浮动盈亏(close)
        当前权益 = 初始权益 + strat.累计利润_USDC + 浮动盈亏
        
        if 当前权益 <= 0:
            print(f"⚠️ 爆仓触发 at {t} | Price: {close}")
            当前权益 = 0
            equity_curve.append(当前权益)
            break
            
        equity_curve.append(当前权益)

    期末收益 = 当前权益 - 初始权益
    浮盈_多 = strat.计算浮动盈亏(close)
    
    print(f"--- 最终状态检查 ---")
    print(f"累计利润 (已实现): {strat.累计利润_USDC:.2f}")
    print(f"最终浮动盈亏: {浮盈_多:.2f}")
    print(f"多头持仓: {strat.汇总持仓()[0]:.4f} ETH")
    print(f"空头持仓: {strat.汇总持仓()[1]:.4f} ETH")
    print(f"当前价: {close}")
    
    指标 = {
        'symbol': conf.symbol,
        'grid_percent': conf.grid_percent,
        'grid_levels': conf.grid_levels,
        'final_profit_usdc': round(期末收益, 6),
        'unit_return': (期末收益 / 初始权益) if 初始权益 > 0 else 0.0,
        'total_trades': strat.累计成交次数,
    }

    # 输出资金曲线 CSV
    out_dir = Path(conf.result_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({'time': times, 'equity': equity_curve}).to_csv(out_dir / '资金曲线_对冲.csv', index=False)
    pd.DataFrame([指标]).to_csv(out_dir / '策略评价_对冲.csv', index=False)
    # 输出 HTML
    df_draw = pd.DataFrame({'time': times, '对冲资金曲线': equity_curve, '价格': price_list})
    draw_equity_curve_plotly(
        df_draw,
        data_dict={'对冲资金曲线': '对冲资金曲线'},
        date_col='time',
        right_axis={'价格': '价格'},
        title=f"3号对冲 | {conf.symbol} | grid={conf.grid_percent:.4%}, levels={conf.grid_levels}",
        path=out_dir / '对冲资金曲线.html',
        show=False,
    )
    print(f"✅ 完成回测: {conf.symbol} | 期末权益: {当前权益:.4f} | 单位资金收益: {指标['unit_return']:.4%}")
    return 指标


def main():
    print("========================================")
    print("         3号对冲策略 - 回测入口          ")
    print("========================================")
    results = []
    for conf in backtest_strategies:
        r = run_one(conf)
        if r:
            results.append(r)
    if results:
        df = pd.DataFrame(results)
        print(df)


if __name__ == '__main__':
    main()
