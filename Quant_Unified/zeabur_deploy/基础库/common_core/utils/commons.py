"""
Quant Unified 量化交易系统
[通用工具函数库]
功能：包含重试装饰器、时间计算、精度处理等常用辅助功能，是系统稳定运行的基础组件。
"""

import time
import traceback
from datetime import datetime, timedelta

import pandas as pd


# ===重试机制
def retry_wrapper(func, params=None, func_name='', retry_times=5, sleep_seconds=5, if_exit=True):
    """
    需要在出错时不断重试的函数，例如和交易所交互，可以使用本函数调用。
    :param func:            需要重试的函数名
    :param params:          参数
    :param func_name:       方法名称
    :param retry_times:     重试次数
    :param sleep_seconds:   报错后的sleep时间
    :param if_exit:         报错是否退出程序
    :return:
    """
    if params is None:
        params = {}
    for _ in range(retry_times):
        try:
            if 'timestamp' in params:
                from core.binance.base_client import BinanceClient
                params['timestamp'] = int(time.time() * 1000) - BinanceClient.diff_timestamp
            result = func(params=params)
            return result
        except Exception as e:
            print(f'❌{func_name} 报错，程序暂停{sleep_seconds}(秒)')
            print(e)
            print(params)
            msg = str(e).strip()
            # 出现1021错误码之后，刷新与交易所的时差
            if 'binance Account has insufficient balance for requested action' in msg:
                print(f'⚠️{func_name} 现货下单资金不足')
                raise ValueError(func_name, '现货下单资金不足')
            elif '-2022' in msg:
                print(f'⚠️{func_name} ReduceOnly订单被拒绝, 合约仓位已经平完')
                raise ValueError(func_name, 'ReduceOnly订单被拒绝, 合约仓位已经平完')
            elif '-4118' in msg:
                print(f'⚠️{func_name} 统一账户 ReduceOnly订单被拒绝, 合约仓位已经平完')
                raise ValueError(func_name, '统一账户 ReduceOnly订单被拒绝, 合约仓位已经平完')
            elif '-2019' in msg:
                print(f'⚠️{func_name} 合约下单资金不足')
                raise ValueError(func_name, '合约下单资金不足')
            elif '-2015' in msg and 'Invalid API-key' in msg:
                # {"code":-2015,"msg":"Invalid API-key, IP, or permissions for action, request ip: xxx.xxx.xxx.xxx"}
                print(f'❌{func_name} API配置错误，可能写错或未配置权限')
                break
            elif '-1121' in msg and 'Invalid symbol' in msg:
                # {"code":-2015,"msg":"Invalid API-key, IP, or permissions for action, request ip: xxx.xxx.xxx.xxx"}
                print(f'❌{func_name} 没有交易对')
                break
            elif '-5013' in msg and 'Asset transfer failed' in msg:
                print(f'❌{func_name} 余额不足，无法资金划转')
                break
            else:
                print(f'❌{e}，报错内容如下')
                print(traceback.format_exc())
            time.sleep(sleep_seconds)
    else:
        if if_exit:
            raise ValueError(func_name, '报错重试次数超过上限，程序退出。')


# ===下次运行时间
def next_run_time(time_interval, ahead_seconds=5):
    """
    根据time_interval，计算下次运行的时间。
    PS：目前只支持分钟和小时。
    :param time_interval: 运行的周期，15m，1h
    :param ahead_seconds: 预留的目标时间和当前时间之间计算的间隙
    :return: 下次运行的时间

    案例：
    15m  当前时间为：12:50:51  返回时间为：13:00:00
    15m  当前时间为：12:39:51  返回时间为：12:45:00

    10m  当前时间为：12:38:51  返回时间为：12:40:00
    10m  当前时间为：12:11:01  返回时间为：12:20:00

    5m  当前时间为：12:33:51  返回时间为：12:35:00
    5m  当前时间为：12:34:51  返回时间为：12:40:00

    30m  当前时间为：21日的23:33:51  返回时间为：22日的00:00:00
    30m  当前时间为：14:37:51  返回时间为：14:56:00

    1h  当前时间为：14:37:51  返回时间为：15:00:00
    """
    # 检测 time_interval 是否配置正确，并将 时间单位 转换成 可以解析的时间单位
    if time_interval.endswith('m') or time_interval.endswith('h'):
        pass
    elif time_interval.endswith('T'):  # 分钟兼容使用T配置，例如  15T 30T
        time_interval = time_interval.replace('T', 'm')
    elif time_interval.endswith('H'):  # 小时兼容使用H配置， 例如  1H  2H
        time_interval = time_interval.replace('H', 'h')
    else:
        print('⚠️time_interval格式不符合规范。程序exit')
        exit()

    # 将 time_interval 转换成 时间类型
    ti = pd.to_timedelta(time_interval)
    # 获取当前时间
    now_time = datetime.now()
    # 计算当日时间的 00：00：00
    this_midnight = now_time.replace(hour=0, minute=0, second=0, microsecond=0)
    # 每次计算时间最小时间单位1分钟
    min_step = timedelta(minutes=1)
    # 目标时间：设置成默认时间，并将 秒，毫秒 置零
    target_time = now_time.replace(second=0, microsecond=0)

    while True:
        # 增加一个最小时间单位
        target_time = target_time + min_step
        # 获取目标时间已经从当日 00:00:00 走了多少时间
        delta = target_time - this_midnight
        # delta 时间可以整除 time_interval，表明时间是 time_interval 的倍数，是一个 整时整分的时间
        # 目标时间 与 当前时间的 间隙超过 ahead_seconds，说明 目标时间 比当前时间大，是最靠近的一个周期时间
        if int(delta.total_seconds()) % int(ti.total_seconds()) == 0 and int(
                (target_time - now_time).total_seconds()) >= ahead_seconds:
            break

    return target_time


# ===依据时间间隔, 自动计算并休眠到指定时间
def sleep_until_run_time(time_interval, ahead_time=1, if_sleep=True, cheat_seconds=0):
    """
    根据next_run_time()函数计算出下次程序运行的时候，然后sleep至该时间
    :param time_interval: 时间周期配置，用于计算下个周期的时间
    :param if_sleep: 是否进行sleep
    :param ahead_time: 最小时间误差
    :param cheat_seconds: 相对于下个周期时间，提前或延后多长时间， 100： 提前100秒； -50：延后50秒
    :return:
    """
    # 计算下次运行时间
    run_time = next_run_time(time_interval, ahead_time)
    # 计算延迟之后的目标时间
    target_time = run_time
    # 配置 cheat_seconds ，对目标时间进行 提前 或者 延后
    if cheat_seconds != 0:
        target_time = run_time - timedelta(seconds=cheat_seconds)
    print(f'⏳程序等待下次运行，下次时间：{target_time}')

    # sleep
    if if_sleep:
        # 计算获得的 run_time 小于 now, sleep就会一直sleep
        _now = datetime.now()
        if target_time > _now:  # 计算的下个周期时间超过当前时间，直接追加一个时间周期
            time.sleep(max(0, (target_time - _now).seconds))
        while True:  # 在靠近目标时间时
            if datetime.now() > target_time:
                time.sleep(1)
                break

    return run_time


# ===根据精度对数字进行就低不就高处理
def apply_precision(number: int | float, decimals: int) -> float:
    """
    根据精度对数字进行就低不就高处理
    :param number:      数字
    :param decimals:    精度
    :return:
        (360.731, 0)结果是360，
        (123.65, 1)结果是123.6
    """
    multiplier = 10 ** decimals
    return int(number * multiplier) / multiplier


def bool_str(true_or_false):
    return '🔵[OK]' if true_or_false else '🟡[NO]'
