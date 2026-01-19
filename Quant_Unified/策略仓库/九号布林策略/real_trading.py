# -*- coding: utf-8 -*-
"""
九号布林策略 - 实时信号脚本（不下单，只推送）

这个文件是干嘛的？
    这是一个“信号雷达”：
    - 每分钟订阅 BTC 1m K线（WebSocket：长连接，像电话不挂断）
    - 用 1m 聚合出 5m/15m/30m/1h/4h，并计算布林带与均线
    - 满足你定义的规则后，在“下一分钟”推送信号到钉钉机器人

重要要求（你明确说的）：
    1) 只做实时，不做历史回放
    2) 历史只采集“计算需要”的 1m 数据（用于预热指标）
    3) 钉钉限频：1 分钟最多 20 条
    4) 消息必须包含关键词“布林”，否则钉钉机器人不推送
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

# ============================================================
# 将项目目录加入 sys.path（保证脚本从任意 cwd 都能运行）
# ============================================================
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]  # Quant_Unified

for folder in ["基础库", "服务", "策略仓库", "应用"]:
    p = PROJECT_ROOT / folder
    if p.exists() and str(p) not in sys.path:
        sys.path.append(str(p))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))


# ============================================================
# 环境变量加载（本地 .env 自动填充，但不覆盖系统环境变量）
# ============================================================
try:
    from common_core.utils.env_kit import 加载_env文件
except Exception:  # pragma: no cover
    加载_env文件 = None

已加载_env路径列表 = 加载_env文件(__file__) if 加载_env文件 else []
if 已加载_env路径列表:
    print(f"✅ 已加载环境变量文件: {' , '.join(str(p) for p in 已加载_env路径列表)}")
else:
    print("⚠️ 未找到任何 .env 文件：将只能读取系统环境变量（export 的那种）")


# ============================================================
# 现在才导入项目内模块（避免 import 时读不到路径/环境）
# ============================================================
from common_core.exchange import BinanceWsManager  # noqa: E402
from 策略仓库.九号布林策略.config import 九号布林策略配置  # noqa: E402
from 策略仓库.九号布林策略.program.strategy_brain import 分钟K线, 九号布林策略脑子, 待推送信号  # noqa: E402


def _设置行情环境(*, 使用测试网: bool) -> None:
    """
    只影响“行情来源”（WS/REST），不涉及下单（本策略不下单）。
    """
    if 使用测试网:
        os.environ["BINANCE_TESTNET"] = "true"
        os.environ["BINANCE_USE_TESTNET"] = "true"
        print("🧪 行情环境：测试网 (Demo) —— 注意：价格可能与真实 BTC 不一致")
        return
    os.environ["BINANCE_TESTNET"] = "false"
    os.environ["BINANCE_USE_TESTNET"] = "false"
    print("🌍 行情环境：主网 (真实行情)")


def _拉取最近K线_向后回溯(*, symbol: str, interval: str, 总根数: int, 使用测试网: bool) -> list[dict[str, Any]]:
    """
    用 REST 拉取最近 N 根 K线（向后回溯拼接）

    说明：
        - 这是“预热”用途：让布林/均线在启动时就有足够窗口
        - 全程使用真实接口，不使用任何假数据（Mock Data）
        - 这里只拉行情 K线：使用币安的“公开接口”，不需要 API KEY
    """
    if 总根数 <= 0:
        return []

    interval = str(interval).strip()
    if interval not in {"1m", "1d"}:
        raise ValueError(f"暂不支持的 interval={interval}（目前只用到 1m/1d）")

    # 关键修正：
    #   common_core.exchange.binance_raw 为了“安全默认”，在未开启 USE_REAL_TRADING 时会强制走测试网。
    #   九号策略只拉行情（不下单），你又明确选了主网（B），所以这里直接走币安公开行情端点。
    base_url = "https://testnet.binancefuture.com" if 使用测试网 else "https://fapi.binance.com"
    url = f"{base_url}/fapi/v1/klines"

    # Binance Klines: 只支持 endTime(ms)，我们就从“现在”一路往回拉
    end_time_ms: int | None = None
    已拿到: list[dict[str, Any]] = []
    remaining = int(总根数)

    while remaining > 0:
        limit = min(1000, remaining)  # 币安上限 1500，我们保守点用 1000
        params: dict[str, Any] = {"symbol": str(symbol).upper().strip(), "interval": interval, "limit": limit}
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)

        r = requests.get(url, params=params, timeout=10.0)
        r.raise_for_status()
        raw = r.json()
        if not isinstance(raw, list) or not raw:
            break

        chunk: list[dict[str, Any]] = []
        for item in raw:
            # 返回格式见币安文档：list[list]
            # [0] openTime, [1] open, [2] high, [3] low, [4] close, [5] volume, [6] closeTime
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

        # 下一轮往更早的时间拉（用最早一根的 open_time 往前推 1ms）
        earliest_open_ms = min(x["open_ms"] for x in chunk)
        end_time_ms = int(earliest_open_ms - 1)

        # 轻微休眠，避免过快触发限速（虽然我们这里请求很少）
        time.sleep(0.05)

    # 去重 + 排序（按 open_ms 升序）
    dedup = {x["open_ms"]: x for x in 已拿到}
    out = [dedup[k] for k in sorted(dedup.keys())]

    # 只保留最后 N 根（防止 API 返回超出）
    return out[-int(总根数) :]


class _钉钉限流器:
    """
    钉钉 1 分钟最多 20 条：
        用“滑动窗口”实现限流
    """

    def __init__(self, *, 每分钟上限: int) -> None:
        self._每分钟上限 = int(max(1, 每分钟上限))
        self._发送时间戳: deque[float] = deque()

    def 允许发送(self) -> bool:
        now = time.time()
        while self._发送时间戳 and (now - self._发送时间戳[0]) > 60.0:
            self._发送时间戳.popleft()
        return len(self._发送时间戳) < self._每分钟上限

    def 记录一次发送(self) -> None:
        self._发送时间戳.append(time.time())


def _发送钉钉文本(*, webhook_url: str, content: str, timeout_s: float = 10.0) -> None:
    if not webhook_url:
        raise ValueError("未配置 DINGTALK_WEBHOOK_URL")
    payload = {"msgtype": "text", "text": {"content": content}}
    r = requests.post(webhook_url, json=payload, timeout=float(timeout_s))
    r.raise_for_status()
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if isinstance(data, dict) and int(data.get("errcode", 0) or 0) != 0:
        raise RuntimeError(f"钉钉返回错误: {data}")


async def _主程序() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger = logging.getLogger("九号布林策略.实时")

    cfg = 九号布林策略配置()
    if not cfg.交易对:
        raise ValueError("❌ 缺少交易对（BOLL9_SYMBOL），例如 BTCUSDT")

    if cfg.布林窗口 <= 2:
        raise ValueError("❌ 布林窗口必须 > 2")
    if cfg.布林倍数 <= 0:
        raise ValueError("❌ 布林倍数必须 > 0")

    # 1) 选择行情环境（主网/测试网）
    _设置行情环境(使用测试网=bool(cfg.使用测试网))

    # 2) 初始化“脑子”
    脑子 = 九号布林策略脑子(
        交易对=cfg.交易对,
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

    # 3) 预热：日线（只拉必要的最小数据）
    logger.info("🧠 预热日线 MA：拉取最近 %s 天 1d K线...", cfg.预热日线K线_天数)
    daily_rows = _拉取最近K线_向后回溯(
        symbol=cfg.交易对,
        interval="1d",
        总根数=int(cfg.预热日线K线_天数),
        使用测试网=bool(cfg.使用测试网),
    )
    if not daily_rows:
        logger.warning("⚠️ 日线预热为空：后续 4h -> 1d 门槛可能一直不满足（因为 MA60 不够）")
    for row in daily_rows:
        脑子.喂入一根日线收盘(结束时间_ms=int(row["close_ms"]) + 1, 收盘价=float(row["close"]))
    logger.info("✅ 日线预热完成：%s 根", len(daily_rows))

    # 4) 预热：1m（只采集“计算需要”的分钟K线）
    minutes = int(max(1, cfg.预热分钟K线_天数) * 1440)
    logger.info("🧠 预热分钟K线：拉取最近 %s 天 1m K线（约 %s 根）...", cfg.预热分钟K线_天数, minutes)
    rows_1m = _拉取最近K线_向后回溯(
        symbol=cfg.交易对,
        interval="1m",
        总根数=minutes,
        使用测试网=bool(cfg.使用测试网),
    )
    if len(rows_1m) < minutes * 0.8:
        logger.warning("⚠️ 分钟K线预热数量偏少：拿到 %s / 期望 %s（可能网络/限速/时间段原因）", len(rows_1m), minutes)

    for row in rows_1m:
        k = 分钟K线(
            开始时间_ms=int(row["open_ms"]),
            结束时间_ms=int(row["close_ms"]) + 1,
            开=float(row["open"]),
            高=float(row["high"]),
            低=float(row["low"]),
            收=float(row["close"]),
            量=float(row.get("volume", 0.0) or 0.0),
        )
        _ = 脑子.喂入一分钟K线并产出信号(k)  # 预热阶段不推送历史信号
    logger.info("✅ 分钟K线预热完成：%s 根", len(rows_1m))

    # 5) 实时部分：订阅 1m K线（只用真实 1m，然后本地聚合）
    ws = BinanceWsManager(
        symbols=[cfg.交易对],
        market_stream_kinds=["kline_1m", "kline_1d"],  # 1d 很少推送，但能让日线 MA 自动更新
        listen_key_provider=None,  # 不下单，不需要用户流
        use_testnet=bool(cfg.使用测试网),
        proxy=None,
    )

    待推送队列: dict[int, list[待推送信号]] = defaultdict(list)  # key=推送时间_ms（分钟边界）
    已发送去重键: deque[str] = deque(maxlen=2000)  # 简单去重：只保留最近若干条
    限流器 = _钉钉限流器(每分钟上限=int(cfg.钉钉每分钟最多发送))

    async def _处理并推送(信号列表: list[待推送信号]) -> None:
        if not 信号列表:
            return
        if not cfg.钉钉Webhook:
            # 你说你稍后会提供 URL：这里先只打印日志，不中断策略
            for s in 信号列表:
                logger.info("📌（未配置钉钉）待推送信号: %s", s.文本.replace("\n", " | "))
            return

        for s in 信号列表:
            # 必须包含关键词“布林”
            if cfg.钉钉关键词 not in s.文本:
                s = 待推送信号(
                    推送时间_ms=s.推送时间_ms,
                    文本=f"{cfg.钉钉关键词} {s.文本}",
                    去重键=s.去重键,
                )

            if s.去重键 in 已发送去重键:
                continue

            if not 限流器.允许发送():
                logger.warning("⛔️ 钉钉限频：本分钟已达 %s 条上限，跳过推送（去重键=%s）", cfg.钉钉每分钟最多发送, s.去重键)
                continue

            try:
                await asyncio.to_thread(_发送钉钉文本, webhook_url=cfg.钉钉Webhook, content=s.文本)
            except Exception:
                logger.exception("❌ 钉钉推送失败（去重键=%s）", s.去重键)
                continue

            限流器.记录一次发送()
            已发送去重键.append(s.去重键)
            logger.info("✅ 钉钉已推送（去重键=%s）", s.去重键)

    async def on_event(event: dict[str, Any]) -> None:
        if str(event.get("e", "")).strip() != "kline":
            return

        k = event.get("k") or {}
        if not k:
            return

        if not bool(k.get("x")):
            return  # 只处理“已收盘”的K线

        interval = str(k.get("i", "")).strip()
        start_ms = int(k.get("t", 0) or 0)
        end_ms_inclusive = int(k.get("T", 0) or 0)
        if start_ms <= 0 or end_ms_inclusive <= 0:
            return
        end_ms = int(end_ms_inclusive + 1)  # 统一成“边界时间”（下一根K线的开始）

        # 先处理“到点要发的”
        due = 待推送队列.pop(end_ms, [])
        await _处理并推送(due)

        # ====== 日线更新（一天一次）=====
        if interval == "1d":
            close_price = float(k.get("c", 0.0) or 0.0)
            if close_price > 0:
                脑子.喂入一根日线收盘(结束时间_ms=end_ms, 收盘价=close_price)
                logger.info("📌 日线已更新: close=%s @ %s", close_price, datetime.fromtimestamp(end_ms / 1000.0))
            return

        # ====== 分钟K线（主驱动）=====
        if interval != "1m":
            return

        one = 分钟K线(
            开始时间_ms=start_ms,
            结束时间_ms=end_ms,
            开=float(k.get("o", 0.0) or 0.0),
            高=float(k.get("h", 0.0) or 0.0),
            低=float(k.get("l", 0.0) or 0.0),
            收=float(k.get("c", 0.0) or 0.0),
            量=float(k.get("v", 0.0) or 0.0),
        )

        新信号 = 脑子.喂入一分钟K线并产出信号(one)

        for s in 新信号:
            # 只排程未来（避免时间乱序导致立刻发）
            if s.推送时间_ms <= end_ms:
                continue
            待推送队列[s.推送时间_ms].append(s)
            logger.info("⏳ 已排程下一分钟推送: %s", s.去重键)

    ws.add_listener(on_event)
    ws.add_connected_listener(lambda: logger.info("✅ WebSocket 已连接：开始实时计算九号布林信号"))

    logger.info(
        "🚀 九号布林策略启动：symbol=%s | testnet=%s | boll=(%s,%s) | warmup_1m_days=%s",
        cfg.交易对,
        cfg.使用测试网,
        cfg.布林窗口,
        cfg.布林倍数,
        cfg.预热分钟K线_天数,
    )
    await ws.start()


def main() -> None:
    try:
        asyncio.run(_主程序())
    except KeyboardInterrupt:
        print("\n👋 收到 Ctrl+C，已退出。")


if __name__ == "__main__":
    main()
