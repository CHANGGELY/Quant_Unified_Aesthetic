"""
策略轮动回测工具
用于快速加载 strategy/ 目录下的策略文件并执行回测。
"""
import sys
import importlib.util
import warnings
import pandas as pd
from pathlib import Path
import re

# 设置 pandas 显示选项
pd.set_option('expand_frame_repr', False)
pd.set_option('display.unicode.ambiguous_as_wide', True)
pd.set_option('display.unicode.east_asian_width', True)
warnings.filterwarnings('ignore')

def get_strategy_files():
    """获取 strategy 目录下所有的 .py 策略文件"""
    strategy_dir = Path(__file__).parent / 'strategy'
    if not strategy_dir.exists():
        print(f"❌ 错误: 找不到策略目录 {strategy_dir}")
        return []
    
    files = list(strategy_dir.glob('*.py'))
    # 排除 __init__.py 和 __pycache__
    files = [f for f in files if f.name != '__init__.py']
    files.sort(key=lambda p: p.name)
    return files

def _extract_strategy_query(raw: str) -> str:
    s = (raw or '').strip()
    if not s:
        return ''
    if 'strategy_backtest.py' in s and (s.lstrip().startswith('&') or 'python' in s.lower()):
        return ''
    s = s.strip('"').strip("'").strip()
    if not s:
        return ''

    py_files = re.findall(r'[^\\/\s"\']+\.py', s)
    if py_files:
        last_py = py_files[-1]
        if last_py == 'strategy_backtest.py':
            return ''
        return last_py

    return s

def _match_strategy_file(strategies, strategy_dir: Path, raw_input: str):
    query = _extract_strategy_query(raw_input)
    if not query:
        return None, []

    if query.isdigit():
        idx = int(query) - 1
        if 0 <= idx < len(strategies):
            return strategies[idx], []
        return None, []

    p = Path(query)
    if p.exists() and p.is_file() and p.suffix.lower() == '.py':
        try:
            resolved = p.resolve()
            if resolved.parent == strategy_dir.resolve():
                return resolved, []
            for f in strategies:
                if f.resolve() == resolved:
                    return f, []
        except Exception:
            pass

    q_lower = query.lower()
    q_stem_lower = Path(query).stem.lower()

    exact = [f for f in strategies if f.name.lower() == q_lower]
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        return None, exact

    stem_exact = [f for f in strategies if f.stem.lower() == q_stem_lower]
    if len(stem_exact) == 1:
        return stem_exact[0], []
    if len(stem_exact) > 1:
        return None, stem_exact

    candidates = [f for f in strategies if (q_lower in f.name.lower()) or (q_stem_lower in f.stem.lower())]
    if len(candidates) == 1:
        return candidates[0], []
    return None, candidates

def load_strategy_config(strategy_file):
    """动态加载策略文件，并将其配置合并到 config 模块中"""
    print(f"🔄 正在加载策略配置: {strategy_file.name} ...")
    
    # 1. 确保原始 config 模块已加载且是干净的
    # 我们需要先导入 config，如果已经导入过，则重新加载以恢复默认值
    try:
        if "config" in sys.modules:
            import config
            importlib.reload(config)
        else:
            import config
    except ImportError as e:
        print(f"❌ 无法加载原始 config.py: {e}")
        raise e

    # 2. 加载策略文件为临时模块
    try:
        spec = importlib.util.spec_from_file_location("temp_strategy_config", strategy_file)
        strategy_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(strategy_module)
    except Exception as e:
        print(f"❌ 策略文件加载失败: {e}")
        raise e
    
    # 3. 将策略模块中的属性覆盖到 config 模块
    # 只覆盖非私有属性
    overridden_keys = []
    for key in dir(strategy_module):
        if not key.startswith("__"):
            value = getattr(strategy_module, key)
            setattr(config, key, value)
            overridden_keys.append(key)
            
    # 4. 路径兼容性处理 (String -> Path)
    if hasattr(config, 'spot_path') and isinstance(config.spot_path, str):
        config.spot_path = Path(config.spot_path)
    if hasattr(config, 'swap_path') and isinstance(config.swap_path, str):
        config.swap_path = Path(config.swap_path)
        
    print(f"✅ 策略配置加载成功 (已覆盖 {len(overridden_keys)} 个配置项)")
    return config

def run_backtest():
    """执行回测流程"""
    # 注意：必须在注入 config 之后再导入这些模块，以确保它们使用新的配置
    # 如果这些模块已经被导入过（例如在循环中），我们需要重新加载它们吗？
    # 通常情况下，如果是第一次运行，或者每次运行都是独立的进程，这没问题。
    # 但在这个交互式工具中，如果用户运行两次，第二次可能仍然使用旧的导入。
    # 然而，program.stepX 模块主要是函数，它们使用传入的 conf 对象，或者在内部 import config。
    # 如果它们在内部 import config，由于 sys.modules['config'] 已经被替换，它们应该获取到新的 config。
    # 唯一的问题是如果它们使用了 `from config import X` 并且是在模块级别执行的。
    # 让我们检查 step1_prepare_data.py: `from config import spot_path...`
    # 这些是模块级别的导入。如果 step1_prepare_data 已经被导入过，再次调用 prepare_data 时，它仍然使用旧的 spot_path。
    
    # 解决方案：我们需要重新加载 program 相关模块，或者在每次运行前清理 sys.modules 中的相关模块。
    # 为了简单起见，我们尝试重新加载关键模块。
    
    modules_to_reload = [
        'core.model.backtest_config',
        'program.step1_prepare_data',
        'program.step2_calculate_factors',
        'program.step3_select_coins',
        'program.step4_simulate_performance'
    ]
    
    for mod_name in modules_to_reload:
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
            
    # 重新导入
    from core.model.backtest_config import load_config
    from program.step1_prepare_data import prepare_data
    from program.step2_calculate_factors import calc_factors
    from program.step3_select_coins import select_coins, aggregate_select_results
    from program.step4_simulate_performance import simulate_performance

    print('\n🌀 回测系统启动中...')

    # 1. 初始化配置
    conf = load_config()

    # 2. 数据准备
    prepare_data(conf)

    # 3. 因子计算
    calc_factors(conf)

    # 4. 选币
    select_coins(conf)
    if conf.strategy_short is not None:
        select_coins(conf, is_short=True)

    # 聚合选币结果
    select_results = aggregate_select_results(conf)

    # 5. 模拟资金曲线
    simulate_performance(conf, select_results)

def main():
    print("="*50)
    print("   邢不行策略轮动回测工具")
    print("="*50)

    strategies = get_strategy_files()
    if not strategies:
        print("没有找到策略文件。")
        return

    strategy_dir = Path(__file__).parent / 'strategy'

    print(f"在 strategy/ 目录下发现 {len(strategies)} 个策略文件:")
    for idx, f in enumerate(strategies):
        print(f"  [{idx+1}] {f.name}")
    print("="*50)

    arg_input = None
    if len(sys.argv) > 1:
        arg_input = " ".join(sys.argv[1:]).strip()

    while True:
        raw_user_input = arg_input if arg_input is not None else input("\n请输入要回测的策略序号或文件名 (输入 q 退出): ")
        arg_input = None
        user_input = (raw_user_input or '').strip()
        
        if user_input.lower() == 'q':
            break
            
        selected_file, candidates = _match_strategy_file(strategies, strategy_dir, user_input)
        if (not selected_file) and (not candidates) and ('strategy_backtest.py' in user_input) and (user_input.lstrip().startswith('&') or 'python' in user_input.lower()):
            print("⚠️ 检测到你粘贴了启动命令，请直接输入策略序号或策略文件名。")
            continue
        
        if selected_file:
            print(f"\n🚀 选中策略: {selected_file.name}")
            try:
                # 加载配置
                load_strategy_config(selected_file)
                # 运行回测
                run_backtest()
                print("\n✨ 回测完成!")
            except Exception as e:
                print(f"\n❌ 回测运行出错: {e}")
                import traceback
                traceback.print_exc()
            
            # 询问是否继续
            cont = input("\n是否继续回测其他策略? (y/n): ").strip().lower()
            if cont != 'y':
                break
        elif candidates:
            print("❌ 匹配到多个策略文件，请输入更精确的序号或文件名：")
            for idx, f in enumerate(candidates):
                print(f"  - {f.name}")
        else:
            print("❌ 未找到匹配的策略文件，请重新输入。")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n程序已终止。")
