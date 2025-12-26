"""
Quant Unified 量化交易系统
path_kit.py
"""

import os
from pathlib import Path

from common_core.utils.path_kit import get_folder_by_root as _get_folder_by_root


PROJECT_ROOT = os.path.abspath(os.path.join(__file__, os.path.pardir, os.path.pardir))


# ====================================================================================================
# ** 功能函数 **
# - get_folder_by_root: 获取基于某一个地址的绝对路径
# - get_folder_path: 获取相对于项目根目录的，文件夹的绝对路径
# - get_file_path: 获取相对于项目根目录的，文件的绝对路径
# ====================================================================================================
def get_folder_by_root(root, *paths, auto_create=True) -> str:
    """
    获取基于某一个地址的绝对路径
    :param root: 相对的地址，默认为运行脚本同目录
    :param paths: 路径
    :param auto_create: 是否自动创建需要的文件夹们
    :return: 绝对路径
    """
    return _get_folder_by_root(root, *paths, auto_create=auto_create)


def get_folder_path(*paths, auto_create=True, as_path_type=True) -> str | Path:
    """
    获取相对于项目根目录的，文件夹的绝对路径
    :param paths: 文件夹路径
    :param auto_create: 是否自动创建
    :param as_path_type: 是否返回Path对象
    :return: 文件夹绝对路径
    """
    _p = get_folder_by_root(PROJECT_ROOT, *paths, auto_create=auto_create)
    if as_path_type:
        return Path(_p)
    return _p


def get_file_path(*paths, auto_create=True, as_path_type=True) -> str | Path:
    """
    获取相对于项目根目录的，文件的绝对路径
    :param paths: 文件路径
    :param auto_create: 是否自动创建
    :param as_path_type: 是否返回Path对象
    :return: 文件绝对路径
    """
    parent = get_folder_path(*paths[:-1], auto_create=auto_create, as_path_type=True)
    _p = parent / paths[-1]
    if as_path_type:
        return _p
    return str(_p)


if __name__ == '__main__':
    """
    DEMO
    """
    print(get_file_path('data', 'xxx.pkl'))
    print(get_folder_path('系统日志'))
    print(get_folder_by_root('data', 'center', 'yyds', auto_create=False))
