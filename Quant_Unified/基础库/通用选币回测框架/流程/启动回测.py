"""
Quant Unified 量化交易系统
启动回测.py

功能：
    回测全流程控制脚本。
"""
import warnings
import pandas as pd

from ..核心.模型.配置 import 回测配置
from .步骤01_准备数据 import 准备数据
from .步骤02_计算因子 import 计算因子
from .步骤03_选币 import 选币, 聚合选币结果
from .步骤04_模拟回测 import 模拟回测

# 忽略不必要的警告
warnings.filterwarnings('ignore')

# 设置 pandas 显示选项
pd.set_option('expand_frame_repr', False)
pd.set_option('display.unicode.ambiguous_as_wide', True)
pd.set_option('display.unicode.east_asian_width', True)


def 运行回测(config_module_or_dict):
    """
    ** 回测主程序 **
    """
    print('🌀 回测系统启动中，稍等...')

    # 1. 初始化配置
    conf = 回测配置.从配置初始化(config_module_or_dict)
    
    # 注入全局路径配置 (如果 config module 中有的话)
    if isinstance(config_module_or_dict, dict):
        conf.spot_path = config_module_or_dict.get('spot_path')
        conf.swap_path = config_module_or_dict.get('swap_path')
        conf.max_workers = config_module_or_dict.get('max_workers', 4)
    else:
        conf.spot_path = getattr(config_module_or_dict, 'spot_path', None)
        conf.swap_path = getattr(config_module_or_dict, 'swap_path', None)
        conf.max_workers = getattr(config_module_or_dict, 'max_workers', 4)

    # 2. 数据准备
    准备数据(conf)

    # 3. 因子计算
    计算因子(conf)

    # 4. 选币
    选币(conf)
    if conf.strategy_short is not None:
        选币(conf, is_short=True)

    # 5. 聚合选币结果
    select_results = 聚合选币结果(conf)
    
    if select_results is None or select_results.empty:
        print("⚠️ 选币结果为空，停止回测。")
        return

    # 6. 模拟回测
    模拟回测(conf, select_results)


if __name__ == '__main__':
    # 示例：从当前目录导入 config (如果存在)
    try:
        import config
        运行回测(config)
    except ImportError:
        print("未找到默认配置文件 config.py，请手动传入配置运行。")