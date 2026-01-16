"""
Quant Unified 量化交易系统
因子中心.py

功能：
    动态加载和管理选币因子。
"""
from __future__ import annotations
import importlib
import pandas as pd


class 虚拟因子:
    """
    ！！！！抽象因子对象，仅用于代码提示！！！！
    """

    def signal(self, *args) -> pd.DataFrame:
        raise NotImplementedError

    def signal_multi_params(self, df, param_list: list | set | tuple) -> dict:
        raise NotImplementedError


class 因子中心:
    _factor_cache = {}

    # noinspection PyTypeChecker
    @staticmethod
    def 获取因子(factor_name) -> 虚拟因子:
        if factor_name in 因子中心._factor_cache:
            return 因子中心._factor_cache[factor_name]

        try:
            # 构造模块名
            # 假设因子库位于: Quant_Unified.基础库.通用选币回测框架.因子库
            module_name = f"Quant_Unified.基础库.通用选币回测框架.因子库.{factor_name}"

            # 动态导入模块
            factor_module = importlib.import_module(module_name)

            # 创建一个包含模块变量和函数的字典
            factor_content = {
                name: getattr(factor_module, name) for name in dir(factor_module)
                if not name.startswith("__")
            }

            # 创建一个包含这些变量和函数的对象
            factor_instance = type(factor_name, (), factor_content)

            # 缓存策略对象
            因子中心._factor_cache[factor_name] = factor_instance

            return factor_instance
        except ModuleNotFoundError as e:
            # 尝试回退到相对导入或 shorter path (如果是在 PYTHONPATH 中)
            try:
                module_name = f"基础库.通用选币回测框架.因子库.{factor_name}"
                factor_module = importlib.import_module(module_name)
                 # 创建一个包含模块变量和函数的字典
                factor_content = {
                    name: getattr(factor_module, name) for name in dir(factor_module)
                    if not name.startswith("__")
                }
                factor_instance = type(factor_name, (), factor_content)
                因子中心._factor_cache[factor_name] = factor_instance
                return factor_instance
            except ModuleNotFoundError:
                raise ValueError(f"Factor {factor_name} not found. (Original error: {e})")
                
        except AttributeError:
            raise ValueError(f"Error accessing factor content in module {factor_name}.")

# Alias
FactorHub = 因子中心
FactorHub.get_by_name = 因子中心.获取因子
