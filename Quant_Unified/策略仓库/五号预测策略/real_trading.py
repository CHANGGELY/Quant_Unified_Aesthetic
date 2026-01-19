# -*- coding: utf-8 -*-
"""
五号预测策略 - 实盘脚本（L2 盘口 + 机器学习信号 -> 目标仓位）

这个文件是干嘛的？
    你可以把它理解成“五号实盘机器人启动器”：
    1) 用 WebSocket（长连接：像电话不挂断）订阅 L2 盘口深度（多档位买卖盘）
    2) 把盘口快照喂给“五号预测策略脑子”（机器学习模型输出做多/做空/空仓）
    3) 把目标仓位交给“实盘执行器”去下真实订单（这里用市价单做调仓）

为什么这里用 WebSocket 而不是每秒去请求一次 REST？
    - REST（普通 HTTP 请求）：像“发消息问一次”，你要不断问，成本高、还慢一拍
    - WebSocket（长连接）：像“电话不断线”，交易所主动推送，实时且省请求

重要安全提醒：
    - 实盘会动用真实资金；默认只连测试网（Demo Trading）
    - 只有当环境变量 USE_REAL_TRADING=true 时才会连实盘，并要求你在终端确认
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any


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
# 环境变量加载（解决“明明有 Key 但读不到”）
# ============================================================
try:
    from common_core.utils.env_kit import 加载_env文件, 读取布尔环境变量
except Exception:  # pragma: no cover
    加载_env文件 = None
    读取布尔环境变量 = None

已加载_env路径列表 = 加载_env文件(__file__) if 加载_env文件 else []
if 已加载_env路径列表:
    print(f"✅ 已加载环境变量文件: {' , '.join(str(p) for p in 已加载_env路径列表)}")
else:
    print("⚠️ 未找到任何 .env 文件：将只能读取系统环境变量（export 的那种）")


# ============================================================
# 安全启动检查（在导入 API 前设置环境变量）
# ============================================================
def _读取_use_real_trading() -> bool:
    if 读取布尔环境变量 is None:
        return os.getenv("USE_REAL_TRADING", "").strip().lower() in ("true", "1", "yes", "y", "on")
    return bool(读取布尔环境变量("USE_REAL_TRADING", 默认值=False))


def _执行安全确认(use_real: bool) -> None:
    if not use_real:
        os.environ["BINANCE_TESTNET"] = "true"
        os.environ["BINANCE_WS_SSL_VERIFY"] = os.getenv("BINANCE_WS_SSL_VERIFY", "false")
        print("🧪以此启动: 测试网模式 (Demo Trading)")
        return

    print("\n" + "!" * 50)
    print("⚠️  警告: 你正在启动 [USE_REAL_TRADING=true] —— 即将连接币安【实盘】！")
    print("!" * 50 + "\n")
    try:
        if os.getenv("可以跳过确认") != "yes":
            confirm = input("请输入 'yes' 确认启动实盘: ")
            if confirm != "yes":
                print("❌ 已取消启动。")
                raise SystemExit(0)
    except EOFError:
        # 非交互环境（例如 CI）下不允许启动实盘
        raise SystemExit("❌ 非交互环境无法确认启动实盘，请改用测试网或设置 可以跳过确认=yes")

    os.environ["BINANCE_TESTNET"] = "false"
    print("🚀以此启动: 实盘模式 (Production)")


_执行安全确认(_读取_use_real_trading())


# ============================================================
# 现在才导入依赖（避免 import 时就误读环境变量）
# ============================================================
from common_core.exchange import BinanceWsManager, ListenKeyProvider  # noqa: E402
from common_core.exchange import binance_raw as api  # noqa: E402
from common_core.strategy import 盘口快照, 币安USDM目标仓位执行器  # noqa: E402
from 策略仓库.五号预测策略.config import Config  # noqa: E402
from 策略仓库.五号预测策略.program.strategy_brain import 五号预测策略脑子  # noqa: E402


def _选择盘口深度档位(depth_levels: int) -> int:
    """
    Binance 盘口流是固定档位：常见是 5/10/20（不同产品可能略有差异）。

    为了“口径一致”，我们只做非常保守的映射：
    - <=5  -> 5
    - <=10 -> 10
    - 其它 -> 20
    """
    lv = int(max(1, depth_levels))
    if lv <= 5:
        return 5
    if lv <= 10:
        return 10
    return 20


def _解析深度事件为盘口快照(event: dict[str, Any], *, depth_levels: int) -> 盘口快照 | None:
    symbol = str(event.get("s", "")).upper().strip()
    if not symbol:
        return None

    ts_exch = int(event.get("T", event.get("E", 0)) or 0)
    if ts_exch <= 0:
        return None

    bids = event.get("b") or []
    asks = event.get("a") or []

    bid价: list[float] = []
    bid量: list[float] = []
    ask价: list[float] = []
    ask量: list[float] = []

    for i in range(int(depth_levels)):
        if i < len(bids):
            bid价.append(float(bids[i][0]))
            bid量.append(float(bids[i][1]))
        else:
            bid价.append(0.0)
            bid量.append(0.0)

        if i < len(asks):
            ask价.append(float(asks[i][0]))
            ask量.append(float(asks[i][1]))
        else:
            ask价.append(0.0)
            ask量.append(0.0)

    return 盘口快照(
        交易对=symbol,
        时间_ms=ts_exch,
        bid价=tuple(bid价),
        bid量=tuple(bid量),
        ask价=tuple(ask价),
        ask量=tuple(ask量),
    )


async def _主程序() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger = logging.getLogger("五号预测策略.实盘")

    cfg = Config()
    symbol = str(cfg.symbol).upper().strip()
    if not symbol:
        raise ValueError("❌ 配置缺少 symbol（例如 BTCUSDT）")

    # 盘口档位与订阅 stream 对齐
    实盘深度档位 = _选择盘口深度档位(int(cfg.depth_levels))
    if int(cfg.depth_levels) != 实盘深度档位:
        logger.warning("⚠️ depth_levels=%s 不在实盘支持档位范围内，已自动映射为 %s", cfg.depth_levels, 实盘深度档位)
        cfg = replace(cfg, depth_levels=实盘深度档位)

    depth_stream = f"depth{实盘深度档位}@100ms"

    # 1) 初始化“脑子”和“手脚”
    脑子 = 五号预测策略脑子(cfg)
    执行器 = 币安USDM目标仓位执行器(
        交易对=symbol,
        数量步进=float(cfg.qty_step),
        最小下单名义=float(cfg.min_order_notional),
        最小下单间隔_s=1.0,
    )

    # 2) 启动时先同步一次账户（不给 0 权益导致策略直接不工作）
    await asyncio.to_thread(执行器.同步账户状态)
    logger.info("✅ 启动同步账户完成: %s", 执行器.获取账户状态())

    # 3) WebSocket（长连接）管理器：订阅盘口 + 用户成交推送
    provider = ListenKeyProvider(
        get_listen_key=api.get_listen_key,
        keep_alive_listen_key=api.keep_alive_listen_key,
    )
    ws = BinanceWsManager(
        symbols=[symbol],
        market_stream_kinds=[depth_stream],
        listen_key_provider=provider,
        user_stream_kind="um",
        use_testnet=bool(getattr(api, "USE_TESTNET", False)),
        proxy=None,
    )

    执行锁 = asyncio.Lock()
    最后一次账户同步_ts = 0.0

    async def on_event(event: dict[str, Any]) -> None:
        nonlocal 最后一次账户同步_ts

        et = str(event.get("e", "")).strip()

        # ====== 1) 盘口深度 ======
        if et == "depthUpdate":
            快照 = _解析深度事件为盘口快照(event, depth_levels=int(cfg.depth_levels))
            if 快照 is None:
                return

            # 更新执行器的 bid/ask（用于下单时计算中间价/名义过滤）
            执行器.更新盘口(时间_ms=快照.时间_ms, bid1=快照.买一价(), ask1=快照.卖一价())

            # 少量周期同步：防止长时间不下单导致账户状态过旧
            now = time.time()
            if now - 最后一次账户同步_ts >= 30.0:
                最后一次账户同步_ts = now
                try:
                    await asyncio.to_thread(执行器.同步账户状态)
                except Exception:
                    logger.exception("❌ 周期同步账户失败（会继续运行，但建议你排查网络/API Key 权限）")

            账户 = 执行器.获取账户状态()
            输出 = 脑子.在盘口快照(快照, 账户)
            if 输出 is None or 输出.目标仓位 is None:
                return

            # 执行可能触发 REST 下单：放到线程里，避免阻塞 WebSocket 事件循环
            async with 执行锁:
                logger.info("🧠 策略输出目标仓位: %s | 备注=%s", 输出.目标仓位, 输出.备注 or {})
                try:
                    await asyncio.to_thread(执行器.执行策略输出, 输出)
                except Exception:
                    logger.exception("❌ 执行策略输出失败（已记录堆栈）")
                else:
                    logger.info("✅ 调仓后账户状态: %s", 执行器.获取账户状态())

            return

        # ====== 2) 用户成交推送（ORDER_TRADE_UPDATE）=====
        if et == "ORDER_TRADE_UPDATE":
            o = event.get("o") or {}
            s = o.get("s", "")
            side = o.get("S", "")
            status = o.get("X", "")
            last_qty = o.get("l", "")
            last_px = o.get("L", "")
            logger.info("📌 成交推送: %s %s status=%s last=%s@%s", s, side, status, last_qty, last_px)
            return

        # ====== 3) 账户更新（ACCOUNT_UPDATE）=====
        if et == "ACCOUNT_UPDATE":
            # 这里先做日志，后续可以进一步“用推送更新本地账户缓存”，减少 REST 压力
            logger.info("📌 账户更新推送: %s", event.get("a", {}))
            return

    ws.add_listener(on_event)

    # 连接成功时打印一次“我在线了”
    ws.add_connected_listener(lambda: logger.info("✅ WebSocket 已连接（盘口 + 用户流）"))

    logger.info("🚀 五号预测策略实盘启动：symbol=%s | stream=%s | testnet=%s", symbol, depth_stream, getattr(api, "USE_TESTNET", None))
    await ws.start()


def main() -> None:
    try:
        asyncio.run(_主程序())
    except KeyboardInterrupt:
        print("\n👋 收到 Ctrl+C，已退出。")


if __name__ == "__main__":
    main()
