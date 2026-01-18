"""
Quant Unified 量化交易系统
极速下载.py

这个文件是干嘛的？
    用多线程并行从交易所拉取分钟 K 线，并保存到历史行情中心。
    适合临时补数据或快速拉一段区间。

为什么这么写？
    - 分块并行：把时间区间切成小块并行拉取，速度更快也更稳。
    - 统一落盘：所有历史行情统一放在“历史行情中心”，避免路径分散。
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path

import ccxt
import pandas as pd

from 基础库.common_core.data_center import 获取历史行情子目录

# =========================
# 配置区
# =========================
交易所代号 = "binance"
交易对 = "ETH/USDT"
开始时间 = "2021-01-01 00:00:00"
结束时间 = "2025-12-12 00:00:00"
周期 = "1m"
最大线程数 = 8  # 保守线程数，避免触发交易所限速

输出目录 = 获取历史行情子目录("分钟K线")
输出文件名 = f"{交易对.replace('/', '')}_{周期}.csv"
输出文件 = 输出目录 / 输出文件名


def 下载区间(交易所代号: str, 交易对: str, 起始毫秒: int, 结束毫秒: int) -> list:
    """下载一个时间区间的 K 线数据"""
    try:
        # 每个线程创建一个独立的交易所实例，避免连接被共享导致异常
        交易所 = getattr(ccxt, 交易所代号)({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })

        全部K线 = []
        当前游标 = 起始毫秒

        while 当前游标 < 结束毫秒:
            try:
                # Binance futures 单次最多 1500 根 K 线
                K线 = 交易所.fetch_ohlcv(交易对, 周期, since=当前游标, limit=1500)
                if not K线:
                    break

                全部K线.extend(K线)

                最新时间戳 = K线[-1][0]
                当前游标 = 最新时间戳 + 60000  # +1 分钟

                if 当前游标 >= 结束毫秒:
                    break

                time.sleep(0.1)  # 适度休眠，降低触发限频的概率
            except Exception as 错误:
                print(f"  ⚠️ 区间拉取异常({起始毫秒}): {错误}")
                time.sleep(2)
                continue

        return 全部K线
    except Exception as 错误:
        print(f"  ❌ 线程初始化失败: {错误}")
        return []


def 运行():
    print(f"🚀 启动极速并行下载: {交易对} ({开始时间} - {结束时间})")

    开始时间_dt = pd.to_datetime(开始时间)
    结束时间_dt = pd.to_datetime(结束时间)

    # 分块（例如每 60 天一块）
    分块列表 = []
    当前时间 = 开始时间_dt
    分块天数 = 60

    while 当前时间 < 结束时间_dt:
        下一块 = 当前时间 + timedelta(days=分块天数)
        if 下一块 > 结束时间_dt:
            下一块 = 结束时间_dt
        分块列表.append((当前时间, 下一块))
        当前时间 = 下一块

    print(f"📦 任务拆分: 共 {len(分块列表)} 个数据块，使用 {最大线程数} 个线程并行下载...")

    全部数据 = []

    with ThreadPoolExecutor(max_workers=最大线程数) as 执行器:
        任务列表 = []
        for 起点, 终点 in 分块列表:
            起点毫秒 = int(起点.timestamp() * 1000)
            终点毫秒 = int(终点.timestamp() * 1000)
            任务列表.append(执行器.submit(下载区间, 交易所代号, 交易对, 起点毫秒, 终点毫秒))

        已完成 = 0
        for 任务 in as_completed(任务列表):
            结果 = 任务.result()
            全部数据.extend(结果)
            已完成 += 1
            print(f"  ✅ 进度: {已完成}/{len(任务列表)} 块完成 (当前累计 {len(全部数据)} 条)")

    if not 全部数据:
        print("❌ 未下载到任何数据")
        return

    # 合并与去重
    print("🔄 正在处理数据合并与去重...")
    数据框 = pd.DataFrame(全部数据, columns=["timestamp", "open", "high", "low", "close", "volume"])

    数据框.drop_duplicates(subset="timestamp", inplace=True)
    数据框.sort_values("timestamp", inplace=True)

    # 过滤精确区间
    起始毫秒 = int(开始时间_dt.timestamp() * 1000)
    结束毫秒 = int(结束时间_dt.timestamp() * 1000)
    数据框 = 数据框[(数据框["timestamp"] >= 起始毫秒) & (数据框["timestamp"] <= 结束毫秒)]

    # 转成北京时间（UTC+8）
    数据框["candle_begin_time"] = pd.to_datetime(数据框["timestamp"], unit="ms") + timedelta(hours=8)

    # 输出列顺序
    输出数据框 = 数据框[["candle_begin_time", "open", "high", "low", "close", "volume"]].copy()

    # 保存
    输出文件.parent.mkdir(parents=True, exist_ok=True)
    输出数据框.to_csv(输出文件, index=False)
    print(f"🎉 数据下载完成！已保存 {len(输出数据框)} 条K线至 {输出文件}")
    print(f"📅 数据范围: {输出数据框['candle_begin_time'].min()} -> {输出数据框['candle_begin_time'].max()}")


if __name__ == "__main__":
    运行()
