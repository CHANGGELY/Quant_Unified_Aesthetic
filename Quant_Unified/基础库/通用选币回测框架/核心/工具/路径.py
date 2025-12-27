"""
Quant Unified 量化交易系统
路径.py

功能：
    提供项目根目录和常用路径的获取功能。
"""
from __future__ import annotations
import os
from pathlib import Path

# 通过当前文件的位置，获取项目根目录 (Quant_Unified)
# 假设当前文件位于: Quant_Unified/基础库/通用选币回测框架/核心/工具/路径.py
PROJECT_ROOT = os.path.abspath(os.path.join(
    __file__, 
    os.path.pardir, 
    os.path.pardir, 
    os.path.pardir, 
    os.path.pardir, 
    os.path.pardir
))


# ====================================================================================================
# ** 功能函数 **
# ====================================================================================================
def 获取基于根目录的文件夹(root, *paths, auto_create=True) -> str:
    """
    获取基于某一个地址的绝对路径
    :param root: 相对的地址，默认为运行脚本同目录
    :param paths: 路径
    :param auto_create: 是否自动创建需要的文件夹们
    :return: 绝对路径
    """
    _full_path = os.path.join(root, *paths)
    if auto_create and (not os.path.exists(_full_path)):  # 判断文件夹是否存在
        try:
            os.makedirs(_full_path)  # 不存在则创建
        except FileExistsError:
            pass  # 并行过程中，可能造成冲突
    return str(_full_path)


def 获取文件夹路径(*paths, auto_create=True, path_type=False) -> str | Path:
    """
    获取相对于项目根目录的，文件夹的绝对路径
    :param paths: 文件夹路径
    :param auto_create: 是否自动创建
    :param path_type: 是否返回Path对象
    :return: 文件夹绝对路径
    """
    _p = 获取基于根目录的文件夹(PROJECT_ROOT, *paths, auto_create=auto_create)
    if path_type:
        return Path(_p)
    return _p


def 获取文件路径(*paths, auto_create=True, as_path_type=False) -> str | Path:
    """
    获取相对于项目根目录的，文件的绝对路径
    :param paths: 文件路径
    :param auto_create: 是否自动创建
    :param as_path_type: 是否返回Path对象
    :return: 文件绝对路径
    """
    parent = 获取文件夹路径(*paths[:-1], auto_create=auto_create, path_type=True)
    _p_119 = parent / paths[-1]
    if as_path_type:
        return _p_119
    return str(_p_119)

# Alias for compatibility
get_folder_path = 获取文件夹路径
get_file_path = 获取文件路径

MIN_QTY_PATH = 获取文件夹路径('data', 'min_qty')
