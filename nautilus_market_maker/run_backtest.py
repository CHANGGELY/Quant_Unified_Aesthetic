"""
Backtest Runner (回测执行脚本)
----------------------------
这就是我们的“模拟人生”启动器。
它负责搭建整个虚拟世界：
1. 创建 BacktestEngine (上帝)。
2. 配置 Venue (交易所，比如 BINANCE)。
3. 定义 Instrument (交易标的，比如 BTCUSDC 永续合约)。
4. 喂数据 (Data Loading)。
5. 启动策略 (Strategy)。

运行方式：
python run_backtest.py --depth <你的depth.parquet> --trades <你的trades.parquet>
"""

from __future__ import annotations

import argparse
import warnings
# 忽略烦人的 sklearn 警告 (Feature names check)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
from decimal import Decimal
from typing import Iterable

from nautilus_trader.backtest.config import BacktestEngineConfig, BacktestVenueConfig
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.model.currencies import BTC, USDC
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Price, Quantity, Money

from data_loader import load_depth5_parquet, load_trades_parquet, merge_tick_streams
from strategy import MarketMakerConfig, MarketMakerStrategy


def build_instrument() -> CryptoPerpetual:
    """
    定义我们要交易的合约规格。
    这里尽量模仿真实的 Binance BTCUSDC Perpetual 规格。
    """
    instrument_id = InstrumentId(Symbol("BTCUSDC"), Venue("BINANCE"))
    return CryptoPerpetual(
        instrument_id,
        raw_symbol=Symbol("BTCUSDC"),
        base_currency=BTC,
        quote_currency=USDC,
        settlement_currency=USDC,
        is_inverse=False,
        price_precision=2,       # 价格那是相当精确，到 0.01 (10^2)
        size_precision=3,        # 数量精确到 0.001
        
        price_increment=Price(0.1, 2),  # 最小跳动价格 tick size
        size_increment=Quantity(0.001, 3), # 最小交易数量 step size
        min_quantity=Quantity(0.001, 3),
        max_quantity=Quantity(100.0, 3),
        min_price=Price(0.1, 2),
        max_price=Price(1_000_000.0, 2),
        max_notional=None,
        min_notional=Money(5.0, USDC),
        
        margin_init=Decimal("0.05"),
        margin_maint=Decimal("0.02"),
        
        maker_fee=Decimal("0.0002"), # 挂单手续费万2
        taker_fee=Decimal("0.0004"), # 吃单手续费万4
        ts_event=0,
        ts_init=0,
    )


def _engine_add_data(engine: BacktestEngine, data: Iterable[object]) -> None:
    """兼容不同版本的 Nautilus add_data API"""
    if hasattr(engine, "add_data"):
        # 新版可能支持直接传 iterator，也可能需要 list
        # 为了稳妥，先转 list，虽然内存占用大点，但在小规模回测没问题
        engine.add_data(list(data))
        return
    if hasattr(engine, "add_data_list"):
        engine.add_data_list(list(data))
        return
    raise RuntimeError("BacktestEngine data ingestion API not found")


def main() -> None:
    parser = argparse.ArgumentParser(description="Nautilus Trader HFT Backtester")
    parser.add_argument("--depth", required=True, help="深度数据 Parquet 文件路径 (depth5)")
    parser.add_argument("--trades", required=True, help="成交数据 Parquet 文件路径 (trades)")
    parser.add_argument("--timestamp-unit", default="ms", choices=["s", "ms", "us", "ns"], help="原始数据的时间单位")
    args = parser.parse_args()

    # 1. 创建上帝 (Engine)
    from nautilus_trader.config import LoggingConfig
    from nautilus_trader.model.identifiers import Venue
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="BACKTESTER-001",
            logging=LoggingConfig(log_level="INFO"),
        )
    )

    # 2. 创建交易所 (Venue)
    from nautilus_trader.backtest.models import MakerTakerFeeModel
    
    # 我们模拟一个 Margin (全仓杠杆) 账户，起始资金 100,000 USDC
    engine.add_venue(
        venue=Venue("BINANCE"),
        oms_type=OmsType.NETTING, # 净网格模式 (单向持仓)，适合合约
        account_type=AccountType.MARGIN,
        base_currency=USDC,
        starting_balances=[Money(100_000, USDC)],
        default_leverage=Decimal("5.0"),     # 给个5倍杠杆
        fee_model=MakerTakerFeeModel(),
    )

    # 3. 注册合约
    instrument = build_instrument()
    engine.add_instrument(instrument)

    # 4. 加载并合并数据
    print("开始加载数据...")
    quotes = load_depth5_parquet(args.depth, instrument.id, args.timestamp_unit, instrument=instrument)
    trades = load_trades_parquet(args.trades, instrument.id, args.timestamp_unit, instrument=instrument)
    
    # 这一步很关键：把两路数据按时间混在一起喂给引擎
    merged_data = merge_tick_streams(quotes, trades)
    _engine_add_data(engine, merged_data)

    # 5. 初始化策略
    print("初始化策略...")
    strategy_config = MarketMakerConfig(instrument_id=instrument.id)
    strategy = MarketMakerStrategy(strategy_config)
    engine.add_strategy(strategy)

    # 6. 启动！
    print("回测开始 (Run) ...")
    engine.run()
    print("回测结束。")

    # 7. 打印战绩
    print("\n" + "="*40)
    print("📊 回测结果统计")
    print("="*40)

    # 尝试多种方式获取 Portfolio
    portfolio = getattr(engine, "portfolio", None)
    if portfolio is None and hasattr(engine, "trader"):
        portfolio = getattr(engine.trader, "portfolio", None)

    if portfolio:
        # 1. 打印账户余额 (最准的 PnL)
        # 假设只有一个 Venue "BINANCE" 和一个 Base Currency "USDC"
        # 也可以遍历 portfolio.accounts()
        try:
            # 这里的 venue 是 InstrumentId 的一部分? 还是直接 str? 
            # 我们在 add_venue 时用的 "BINANCE"
            # Venue 已经在全局导入了
            account = portfolio.account(Venue("BINANCE"))
            if not account:
                print("未找到 BINANCE 账户信息")
            else:
                base_currency = account.base_currency
                total_balance = account.balance_total(base_currency)
                
                # starting_balances 通常是一个 list[Money]
                start_balance = None
                if hasattr(account, "starting_balances"):
                    balances = account.starting_balances
                    if callable(balances):
                        balances = balances()
                    
                    # 如果是 dict {Currency: Money}
                    if isinstance(balances, dict):
                        start_balance = balances.get(base_currency)
                    # 如果是 list [Money]
                    else:
                        for money in balances:
                            if getattr(money, "currency", None) == base_currency:
                                start_balance = money
                                break
                
                if start_balance:
                    pnl = total_balance - start_balance
                    pnl_pct = (pnl / start_balance) * 100
                    print(f"账户: {account.id}")
                    print(f"初始余额: {start_balance}")
                    print(f"最终余额: {total_balance}")
                    print(f"总盈亏 (PnL): {pnl:+.4f} ({pnl_pct:+.2f}%)")
                else:
                    print(f"账户: {account.id}")
                    print(f"最终余额: {total_balance}")
                    print("无法找到初始余额信息")

        except Exception as e:
            print(f"读取账户余额失败: {e}")

        # 2. 打印持仓
        # Portfolio 对象可能没有 positions() 方法，尝试从 Trader 的 Cache 获取
        try:
            positions = []
            if hasattr(engine, "trader") and hasattr(engine.trader, "cache"):
                 positions = engine.trader.cache.positions()
            elif hasattr(engine, "cache"):
                 positions = engine.cache.positions()
            
            print(f"\n最终持仓 ({len(positions)}):")
            for p in positions:
                print(f"  - {p}")
        except Exception as e:
            print(f"读取持仓失败: {e}")

    else:
        print("无法获取 Portfolio 对象。")

    print("="*40 + "\n")

    # 3. 生成可视化报表 (Tearsheet)
    try:
        from nautilus_trader.analysis import TearsheetConfig
        from nautilus_trader.analysis.tearsheet import create_tearsheet
        
        print("正在生成官方可视化分析报表 (Tearsheet)...")
        tearsheet_config = TearsheetConfig(theme="plotly_dark")
        output_path = "backtest_report_market_maker.html"
        
        create_tearsheet(
            engine=engine,
            output_path=output_path,
            config=tearsheet_config,
        )
        print(f"🎉 官方报表已保存至: {output_path}")
    except Exception as e:
        print(f"无法生成官方报表: {e}")
        print("尝试生成自定义 PnL 报表...")
        _generate_custom_report(engine, "backtest_report_custom.html")

    # 重置并销毁引擎
    engine.reset()
    engine.dispose()


def _generate_custom_report(engine: BacktestEngine, output_path: str) -> None:
    """
    专业级回测可视化报表 (A2UI 哲学启发) - 修正版
    =============================================
    修正点：
    1. 使用 analyzer.get_performance_stats_pnls() 获取真实交易统计，解决 N/A 问题。
    2. 优化 Plotly 坐标轴缩放，解决"一条直线"问题。
    3. 修复回撤图填充显示问题。
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        import pandas as pd
        import numpy as np
        
        # =============================================
        # 1. 数据提取 (Data Extraction)
        # =============================================
        analyzer = engine.portfolio.analyzer
        
        # A. 收益率与资金曲线
        returns = analyzer.returns()
        if returns.empty:
            print("❌ 错误：没有产生收益数据(returns empty)，无法绘图。")
            return

        # 核心修复: 强制按时间排序并去重，防止出现"两条线"的回溯乱象
        returns = returns.sort_index()
        # 如果同一微秒有多个数据，取最后一个
        if returns.index.duplicated().any():
             returns = returns[~returns.index.duplicated(keep='last')]

        # 累计收益 (Equity Curve)
        equity_curve = (1 + returns).cumprod()
        
        # B. 回撤 (Drawdown)
        # 确保 running_max > 0 以避免除零
        running_max = equity_curve.cummax()
        drawdown = (equity_curve - running_max) / running_max * 100
        
        # C. 统计指标 (使用官方 Analyzer 计算)
        # analyzer.get_performance_stats_pnls() 返回一个字典，包含 总盈亏、胜率等
        # 如果有多个币种，可能需要指定 currency，这里尝试获取默认或首个
        pnl_stats = {}
        # 尝试获取首个被交易的币种统计
        currencies = analyzer.currencies
        if currencies:
            curr = list(currencies)[0]
            pnl_stats = analyzer.get_performance_stats_pnls(currency=curr) or {}
        
        # 提取关键指标
        total_pnl = pnl_stats.get("PnL (total)", 0.0)
        win_rate = pnl_stats.get("Win Rate", 0.0) * 100
        total_trades = pnl_stats.get("Total Trades", 0)
        profit_factor = pnl_stats.get("Profit Factor", 0.0)
        sharpe = analyzer.get_performance_stats_returns().get("Sharpe Ratio (252 days)", 0.0)
        
        stats = {
            "总收益率": f"{(equity_curve.iloc[-1] - 1) * 100:.4f}%",
            "最大回撤": f"{drawdown.min():.2f}%",
            "总盈亏 (Val)": f"{total_pnl:.2f}",
            "交易次数": f"{total_trades}",
            "胜率": f"{win_rate:.1f}%",
            "盈亏比 (PF)": f"{profit_factor:.2f}",
            "夏普比率": f"{sharpe:.2f}",
        }

        # D. 单笔盈亏 (从 Analyzer 或 Fills 获取)
        # 官方 analyzer 内部可以访问 _fills 或者通过 pnl_stats 获取分布?
        # 如果难以直接获取单笔列表，我们尝试从 Order/Position 历史推断，或使用 diff
        # 这里为了稳健，如果无法获取单笔明细，我们生成基于 equity 变化的"近似每日/每Tick盈亏"
        # 或者尝试访问 engine.trader.cache.fills() (如果存在)
        
        # 尝试从 return series 反推每笔变动 (Rough Approximation)
        # 过滤掉 0 的点
        nonzero_returns = returns[returns != 0]
        # PnL distribution (approx)
        pnl_distribution = nonzero_returns.values # 这其实是收益率分布，非绝对金额
        
        # =============================================
        # 2. 创建 2x2 子图布局
        # =============================================
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                "📈 资金曲线 (Equity Curve)",
                "📉 回撤 (Drawdown)",
                "💰 收益分布 (Return Dist)",  # 改为收益分布，更准确
                "📊 统计汇总 (Statistics)"
            ),
            specs=[
                [{"type": "scatter"}, {"type": "scatter"}],
                [{"type": "histogram"}, {"type": "table"}] # 改为直方图
            ],
            vertical_spacing=0.12,
            horizontal_spacing=0.08
        )
        
        # =============================================
        # Panel 1: 资金曲线
        # =============================================
        fig.add_trace(
            go.Scatter(
                x=equity_curve.index,
                y=equity_curve.values,
                mode='lines',
                name='累计净值',
                line=dict(color='#00d4aa', width=2),
                hovertemplate='<b>%{x}</b><br>净值: %{y:.5f}<extra></extra>'
            ),
            row=1, col=1
        )
        # 添加基准线
        fig.add_hline(y=1.0, line_dash="dash", line_color="gray", opacity=0.5, row=1, col=1)
        
        # 强制 Y 轴范围自适应，防止太扁
        y_min = equity_curve.min()
        y_max = equity_curve.max()
        y_range = y_max - y_min
        if y_range == 0: y_range = 0.01
        fig.update_yaxes(range=[y_min - y_range*0.1, y_max + y_range*0.1], row=1, col=1)

        # =============================================
        # Panel 2: 回撤图
        # =============================================
        fig.add_trace(
            go.Scatter(
                x=drawdown.index,
                y=drawdown.values,
                mode='lines',
                name='回撤%',
                fill='tozeroy', # 填充到 0 轴
                line=dict(color='#ff6b6b', width=1),
                fillcolor='rgba(255, 107, 107, 0.3)',
                hovertemplate='<b>%{x}</b><br>回撤: %{y:.2f}%<extra></extra>'
            ),
            row=1, col=2
        )
        
        # =============================================
        # Panel 3: 收益率分布直方图 (替代单笔PnL)
        # =============================================
        # 因为直接获取单笔 PnL 比较困难，用收益率分布来展示策略盈亏特征
        fig.add_trace(
            go.Histogram(
                x=pnl_distribution,
                name='收益分布',
                marker_color='#5c9eff',
                opacity=0.75,
                nbinsx=50,
                hovertemplate='收益率: %{x:.4f}<br>频次: %{y}<extra></extra>'
            ),
            row=2, col=1
        )
        fig.update_xaxes(title_text="单次变动收益率", row=2, col=1)
        fig.update_yaxes(title_text="频次", row=2, col=1)
        
        # =============================================
        # Panel 4: 统计汇总表
        # =============================================
        fig.add_trace(
            go.Table(
                header=dict(
                    values=["<b>指标</b>", "<b>数值</b>"],
                    fill_color='#2d2d2d',
                    align='left',
                    font=dict(color='white', size=12)
                ),
                cells=dict(
                    values=[list(stats.keys()), list(stats.values())],
                    fill_color=[['#1e1e1e'] * len(stats), ['#1e1e1e'] * len(stats)],
                    align='left',
                    font=dict(color=['#00d4aa', 'white'], size=11),
                    height=28
                )
            ),
            row=2, col=2
        )
        
        # =============================================
        # 3. 整体布局美化
        # =============================================
        fig.update_layout(
            title=dict(
                text="<b>🚀 Market Maker 回测分析报告 (Fix v2)</b>",
                font=dict(size=20, color='white'),
                x=0.5
            ),
            template='plotly_dark',
            height=800,
            showlegend=False,
            margin=dict(t=80, b=40, l=60, r=40),
            paper_bgcolor='#121212',
            plot_bgcolor='#1e1e1e'
        )
        
        # 保存报表
        fig.write_html(output_path)
        print(f"🎉 专业报表(修复版)已生成: {output_path}")
        print("已修复：数据统计 N/A 及图表显示问题。")
        
    except Exception as ex:
        import traceback
        print(f"报表生成失败: {ex}")
        traceback.print_exc()



if __name__ == "__main__":
    main()
