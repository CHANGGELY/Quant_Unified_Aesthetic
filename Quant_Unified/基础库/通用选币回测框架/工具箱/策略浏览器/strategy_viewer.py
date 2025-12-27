"""
邢不行™️选币框架 - 策略查看器主程序
Python数字货币量化投资课程

版权所有 ©️ 邢不行
微信: xbx8662

策略查看器主程序：协调各模块完成分析流程
"""

import pandas as pd
from pathlib import Path
import webbrowser

from .viewer_config import StrategyViewerConfig
from .period_generator import PeriodGenerator
from .metrics_calculator import MetricsCalculator
from .coin_selector import CoinSelector
from .html_reporter import HTMLReporter


def run_strategy_viewer(conf, viewer_config_dict: dict, output_filename: str = None):
    """
    策略查看器主函数
    
    Args:
        conf: 回测配置对象（BacktestConfig实例）
        viewer_config_dict: 策略查看器配置字典（从config.py读取）
        output_filename: 可选的输出文件名（不含扩展名），默认为'策略查看器报告'
    """
    # 1. 解析配置
    viewer_config = StrategyViewerConfig.from_dict(viewer_config_dict)
    
    if not viewer_config.enabled:
        print("⚠️ 策略查看器未启用（enabled=0）")
        return
    
    print("\n" + "="*70)
    print("🔍 策略查看器启动...")
    print("="*70)
    
    print(f"\n{viewer_config}")
    
    # 2. 确定数据路径
    result_folder = conf.get_result_folder()
    select_result_path = result_folder / 'final_select_results.pkl'  # 当前项目使用final_select_results.pkl
    kline_data_path = Path('data') / 'candle_data_dict.pkl'
    
    # 3. 检查文件是否存在
    if not select_result_path.exists():
        print(f"\n❌ 选币结果文件不存在: {select_result_path}")
        print("   请先运行完整回测（Step 1-4）生成选币结果")
        return
    
    if not kline_data_path.exists():
        print(f"\n❌ K线数据文件不存在: {kline_data_path}")
        print("   请先运行 Step 1 准备数据")
        return
    
    try:
        # 4. 读取选币结果
        print(f"\n📂 读取选币结果...")
        select_results = pd.read_pickle(select_result_path)
        print(f"✅ 加载选币结果: {len(select_results)} 条记录")
        
        # 5. 生成连续交易期间
        print(f"\n📊 生成连续交易期间...")
        
        # 根据持仓周期推断K线周期
        # 规则：持仓周期是xH -> K线周期1H；持仓周期是yD -> K线周期1D
        hold_period = conf.strategy.hold_period
        if hold_period.upper().endswith('H'):
            kline_period = '1h'
        elif hold_period.upper().endswith('D'):
            kline_period = '1d'
        else:
            kline_period = '1h'  # 默认1小时
        
        print(f"   持仓周期: {hold_period}, K线周期: {kline_period}")
        
        generator = PeriodGenerator(hold_period, kline_period)
        periods_df = generator.generate(select_results)
        
        if periods_df.empty:
            print("❌ 未生成任何交易期间")
            return
        
        # 6. 加载K线数据
        print(f"\n📈 加载K线数据...")
        kline_data_dict = pd.read_pickle(kline_data_path)
        print(f"✅ 加载 {len(kline_data_dict)} 个币种的K线数据")
        
        # 7. 计算指标
        print(f"\n🧮 计算交易指标...")
        calculator = MetricsCalculator()
        periods_df = calculator.calculate(periods_df, kline_data_dict)
        
        # 8. 筛选目标期间
        print(f"\n🎯 筛选目标交易期间...")
        selector = CoinSelector(viewer_config)
        selected_periods = selector.select(periods_df)
        
        if selected_periods.empty:
            print("❌ 筛选后无结果，请调整筛选参数")
            return
        
        # 9. 生成HTML报告
        print(f"\n📝 生成HTML报告...")
        reporter = HTMLReporter()
        html_content = reporter.generate(
            periods_df=periods_df,
            selected_periods=selected_periods,
            kline_data_dict=kline_data_dict,
            config=viewer_config,
            strategy_name=conf.name,
            kline_period=kline_period
        )
        
        # 10. 保存报告
        filename = output_filename if output_filename else '策略查看器报告'
        output_path = result_folder / f'{filename}.html'
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"✅ 报告已生成: {output_path}")
        
        # 11. 自动打开报告
        try:
            webbrowser.open(f'file:///{output_path.absolute()}')
            print("🌐 已在浏览器中打开报告")
        except Exception as e:
            print(f"⚠️ 自动打开浏览器失败: {e}")
            print(f"   请手动打开: {output_path}")
        
        print("\n" + "="*70)
        print("🎉 策略查看器运行完成！")
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"\n❌ 策略查看器运行出错: {e}")
        import traceback
        traceback.print_exc()
        raise

