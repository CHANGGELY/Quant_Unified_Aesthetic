"""
common/utils.py - 二号网格策略用的通用工具函数

这个文件是干嘛的？
    这里放“到处都会用到”的小工具，比如：
    - 重试（网络抖动时自动再试几次）
    - 时间计算（下一次运行时间、睡眠到指定时间点）

怎么用？
    一般不需要直接运行本文件。
    它主要被其它模块 import（导入）使用，例如：
        from 策略仓库.二号网格策略.common.utils import ...
"""
import time
import pandas as pd
from datetime import datetime, timedelta
from math import floor

from 基础库.common_core.utils.commons import retry_wrapper, next_run_time, sleep_until_run_time
