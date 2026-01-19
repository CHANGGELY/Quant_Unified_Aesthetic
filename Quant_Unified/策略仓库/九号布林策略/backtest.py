# -*- coding: utf-8 -*-
"""
九号布林策略 - 回测脚本

这个文件是干嘛的？
    用历史 K 线数据"回放"策略逻辑，验证：
    1) 策略能否正常产生信号（有信号 = 逻辑跑通了）
    2) 钉钉机器人能否正常收到消息（可选：发送一条测试消息）

为什么要回测？
    实盘要"等行情"，可能几小时都不出信号。
    回测用历史数据"快进"，几秒钟就能看到有没有信号、逻辑对不对。

使用方法（在终端运行）：
    python 策略仓库/九号布林策略/backtest.py

    加参数：
        --days 30       回测最近 30 天（默认 12 天）
        --send-dingtalk 回测结束后发一条真实钉钉消息验证
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

# ============================================================
# 将项目目录加入 sys.path（保证脚本从任意 cwd 都能运行）
# ============================================================
当前文件 = Path(__file__).resolve()
项目根目录 = 当前文件.parents[2]  # Quant_Unified

for folder in ["基础库", "服务", "策略仓库", "应用"]:
    p = 项目根目录 / folder
    if p.exists() and str(p) not in sys.path:
        sys.path.append(str(p))
if str(项目根目录) not in sys.path:
    sys.path.append(str(项目根目录))

# ============================================================
# 环境变量加载
# ============================================================
try:
    from common_core.utils.env_kit import 加载_env文件
except Exception:
    加载_env文件 = None

已加载_env路径列表 = 加载_env文件(__file__) if 加载_env文件 else []
if 已加载_env路径列表:
    print(f"✅ 已加载环境变量文件: {' , '.join(str(p) for p in 已加载_env路径列表)}")

# ============================================================
# 导入策略脑子和配置
# ============================================================
from 策略仓库.九号布林策略.config import 九号布林策略配置  # noqa: E402
from 策略仓库.九号布林策略.program.strategy_brain import 分钟K线, 九号布林策略脑子, 待推送信号  # noqa: E402


def 拉取K线(*, symbol: str, interval: str, 天数: int) -> list[dict[str, Any]]:
    """
    从币安拉取历史 K 线（真实数据，不是假数据）

    解释：
        - 币安公开接口，不需要 API KEY
        - 我们用主网接口（因为你说要用真实行情）
    """
    base_url = "https://fapi.binance.com"
    url = f"{base_url}/fapi/v1/klines"

    总根数 = int(天数 * 1440)  # 1天 = 1440 分钟
    end_time_ms: int | None = None
    已拿到: list[dict[str, Any]] = []
    remaining = int(总根数)

    print(f"📥 正在拉取 {symbol} 最近 {天数} 天的 {interval} K线（约 {总根数} 根）...")

    while remaining > 0:
        limit = min(1000, remaining)
        params: dict[str, Any] = {"symbol": str(symbol).upper().strip(), "interval": interval, "limit": limit}
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)

        r = requests.get(url, params=params, timeout=30.0)
        r.raise_for_status()
        raw = r.json()
        if not isinstance(raw, list) or not raw:
            break

        chunk: list[dict[str, Any]] = []
        for item in raw:
            try:
                open_ms = int(item[0])
                close_ms = int(item[6])
                chunk.append(
                    {
                        "open_ms": open_ms,
                        "close_ms": close_ms,
                        "open": float(item[1]),
                        "high": float(item[2]),
                        "low": float(item[3]),
                        "close": float(item[4]),
                        "volume": float(item[5]),
                    }
                )
            except Exception:
                continue

        if not chunk:
            break

        已拿到.extend(chunk)
        remaining -= len(chunk)

        earliest_open_ms = min(x["open_ms"] for x in chunk)
        end_time_ms = int(earliest_open_ms - 1)

        # 避免请求太快被限速
        time.sleep(0.1)

    # 去重 + 排序
    dedup = {x["open_ms"]: x for x in 已拿到}
    out = [dedup[k] for k in sorted(dedup.keys())]
    print(f"✅ 拉取完成：共 {len(out)} 根 K线")
    return out[-int(总根数):]


def 拉取日线(*, symbol: str, 天数: int) -> list[dict[str, Any]]:
    """拉取日线（用于预热日线 MA）"""
    base_url = "https://fapi.binance.com"
    url = f"{base_url}/fapi/v1/klines"

    params: dict[str, Any] = {"symbol": str(symbol).upper().strip(), "interval": "1d", "limit": int(天数)}
    r = requests.get(url, params=params, timeout=30.0)
    r.raise_for_status()
    raw = r.json()

    out: list[dict[str, Any]] = []
    for item in raw:
        try:
            out.append(
                {
                    "open_ms": int(item[0]),
                    "close_ms": int(item[6]),
                    "close": float(item[4]),
                }
            )
        except Exception:
            continue
    return out


def 发送钉钉测试消息(*, webhook_url: str, 信号数量: int) -> None:
    """发送一条真实的钉钉消息（验证 webhook 是否可用）"""
    if not webhook_url:
        print("⚠️ 未配置 DINGTALK_WEBHOOK_URL，跳过钉钉测试")
        return

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = f"布林 九号策略回测完成\n时间: {now_str}\n信号数量: {信号数量} 条\n\n（这是一条自动测试消息，说明钉钉推送正常工作）"

    payload = {"msgtype": "text", "text": {"content": content}}
    try:
        r = requests.post(webhook_url, json=payload, timeout=10.0)
        r.raise_for_status()
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if isinstance(data, dict) and int(data.get("errcode", 0) or 0) != 0:
            print(f"❌ 钉钉返回错误: {data}")
        else:
            print("✅ 钉钉测试消息已发送！请检查钉钉群是否收到消息。")
    except Exception as e:
        print(f"❌ 钉钉推送失败: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="九号布林策略回测",
        description="用历史 K 线回放策略，验证逻辑是否正常、是否能产生信号。",
    )
    parser.add_argument("--days", type=int, default=12, help="回测最近多少天（默认 12 天）")
    parser.add_argument("--send-dingtalk", action="store_true", help="回测结束后发送一条钉钉测试消息")
    args = parser.parse_args()

    cfg = 九号布林策略配置()
    symbol = cfg.交易对
    print(f"🚀 开始回测：{symbol}")
    print(f"   布林参数: 窗口={cfg.布林窗口}, 倍数={cfg.布林倍数}")
    print(f"   回测天数: {args.days} 天")
    print()

    # 1) 拉取日线（预热）
    daily_rows = 拉取日线(symbol=symbol, 天数=cfg.预热日线K线_天数)
    print(f"📊 日线预热: {len(daily_rows)} 根")

    # 2) 拉取分钟 K 线
    rows_1m = 拉取K线(symbol=symbol, interval="1m", 天数=args.days)
    if not rows_1m:
        print("❌ 未能拉取到分钟 K 线数据，请检查网络")
        return

    # 3) 初始化策略脑子
    脑子 = 九号布林策略脑子(
        交易对=symbol,
        布林窗口=cfg.布林窗口,
        布林倍数=cfg.布林倍数,
        回看根数=cfg.更高周期回看根数,
        阈值_15m_ma收敛=cfg.阈值_15m_ma收敛,
        阈值_30m_ma收敛=cfg.阈值_30m_ma收敛,
        阈值_1h_ma收敛_上穿=cfg.阈值_1h_ma收敛_上穿,
        阈值_1h_ma收敛_下穿=cfg.阈值_1h_ma收敛_下穿,
        阈值_4h_ma收敛=cfg.阈值_4h_ma收敛,
        阈值_1d_ma收敛=cfg.阈值_1d_ma收敛,
    )

    # 4) 预热日线
    for row in daily_rows:
        脑子.喂入一根日线收盘(结束时间_ms=int(row["close_ms"]) + 1, 收盘价=float(row["close"]))

    # 5) 回放分钟 K 线
    print()
    print("⏳ 正在回放 K 线数据...")
    所有信号: list[待推送信号] = []
    for i, row in enumerate(rows_1m):
        k = 分钟K线(
            开始时间_ms=int(row["open_ms"]),
            结束时间_ms=int(row["close_ms"]) + 1,
            开=float(row["open"]),
            高=float(row["high"]),
            低=float(row["low"]),
            收=float(row["close"]),
            量=float(row.get("volume", 0.0) or 0.0),
        )
        新信号 = 脑子.喂入一分钟K线并产出信号(k)
        所有信号.extend(新信号)

        # 进度提示（每 5000 根打印一次）
        if (i + 1) % 5000 == 0:
            print(f"   已处理 {i + 1} / {len(rows_1m)} 根...")

    # 6) 输出结果
    print()
    print("=" * 60)
    print(f"📈 回测完成！共产生 {len(所有信号)} 条信号")
    print("=" * 60)

    if 所有信号:
        print()
        print("📌 信号列表（最多显示前 20 条）：")
        print("-" * 60)
        for i, s in enumerate(所有信号[:20]):
            推送时间 = datetime.fromtimestamp(s.推送时间_ms / 1000.0).strftime("%Y-%m-%d %H:%M")
            print(f"#{i + 1} [{推送时间}] {s.去重键}")
            for line in s.文本.split("\n"):
                print(f"     {line}")
            print()

        if len(所有信号) > 20:
            print(f"   ...还有 {len(所有信号) - 20} 条信号未显示")
    else:
        print()
        print("⚠️ 没有产生任何信号。")
        print("   可能原因：")
        print("   - 回测天数太短，行情不满足触发条件")
        print("   - 阈值设置太严格")
        print("   - 你可以尝试增加 --days 参数，例如：--days 30")

    # 7) 可选：发送钉钉测试消息
    if bool(args.send_dingtalk):
        print()
        发送钉钉测试消息(webhook_url=cfg.钉钉Webhook, 信号数量=len(所有信号))


if __name__ == "__main__":
    main()
