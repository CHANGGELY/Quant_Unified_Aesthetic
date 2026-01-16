"""
Python 环境初始化钩子

此文件会被 Python 的 site 模块自动加载（只要它在 sys.path 中）。
它的主要作用是动态配置 sys.path，将项目的 libs, services, strategies, apps 等目录
加入到模块搜索路径中。

这样做的目的是：
1. 允许项目内的代码直接通过 import 导入这些目录下的模块（如 import common_core）。
2. 避免在每个脚本中手动编写 sys.path.append(...)。
3. 简化开发环境配置，无需强制设置 PYTHONPATH 环境变量。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_EXTRA = [
    os.path.join(_ROOT, '基础库'),
    os.path.join(_ROOT, '服务'),
    os.path.join(_ROOT, '策略仓库'),
    os.path.join(_ROOT, '4 号做市策略'),
    os.path.join(_ROOT, '应用'),
    os.path.join(_ROOT, '应用', 'qronos'),
]
for p in _EXTRA:
    if os.path.isdir(p) and p not in sys.path:
        sys.path.append(p)
