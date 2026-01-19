# -*- coding: utf-8 -*-
"""
九号布林策略 - 配置文件

这个文件是干嘛的？
    九号策略的核心任务不是下单，而是“生成信号 + 推送钉钉”。
    你可以把它理解成一个“报警器”：
        - 交易所每分钟给你一根 1m K线（开高低收）
        - 我们把它聚合成 5m/15m/30m/1h/4h（用于布林线与均线计算）
        - 满足你定义的条件后，在下一分钟推送包含关键词“布林”的消息到钉钉机器人

重要约定（唯一入口）：
    - 程序运行时只读取系统环境变量
    - `.env` 只是本地开发的“自动填充器”（启动时把内容塞进环境变量，不覆盖你手动 export 的值）
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class 九号布林策略配置:
    # ====== 数据源 ======
    交易对: str = os.getenv("BOLL9_SYMBOL", "BTCUSDT").upper().strip()

    # 是否使用测试网（只影响行情来源：WS/REST）
    # - False：主网（真实 BTC 行情）
    # - True：测试网（Demo 行情，可能和真实价格不同）
    使用测试网: bool = os.getenv("BOLL9_USE_TESTNET", "false").lower() in ("true", "1", "yes", "y", "on")

    # ====== 指标参数（默认布林：20,2）======
    布林窗口: int = int(os.getenv("BOLL9_BOLL_WINDOW", "20"))
    布林倍数: float = float(os.getenv("BOLL9_BOLL_K", "2"))

    # ====== 历史预热（只拉“计算需要”的 1m 历史）======
    # 解释：
    #   我们需要 4h 的 MA60：
    #       60 根 4h K线 = 10 天
    #   所以这里默认拉 12 天（留一点缓冲）。
    预热分钟K线_天数: int = int(os.getenv("BOLL9_WARMUP_1M_DAYS", "12"))

    # 日线 MA60 需要至少 60 根 1d K线（60 天），但我们不拉 60 天 1m（太浪费）。
    # 这里单独拉日线历史（这也是“计算需要”的最小数据）。
    预热日线K线_天数: int = int(os.getenv("BOLL9_WARMUP_1D_DAYS", "70"))

    # ====== 信号阈值（按你的描述写死默认，可用 env 覆盖）======
    # MA 收敛阈值（max(MA5,MA30,MA60)-min(...) < 阈值）
    阈值_15m_ma收敛: float = float(os.getenv("BOLL9_TH_15M_MA_SPREAD", "500"))
    阈值_30m_ma收敛: float = float(os.getenv("BOLL9_TH_30M_MA_SPREAD", "1000"))
    阈值_1h_ma收敛_上穿: float = float(os.getenv("BOLL9_TH_1H_MA_SPREAD_UP", "1800"))
    阈值_1h_ma收敛_下穿: float = float(os.getenv("BOLL9_TH_1H_MA_SPREAD_DOWN", "1500"))
    阈值_4h_ma收敛: float = float(os.getenv("BOLL9_TH_4H_MA_SPREAD", "1800"))
    阈值_1d_ma收敛: float = float(os.getenv("BOLL9_TH_1D_MA_SPREAD", "2900"))

    # “在 5 个更高周期之内出现过一次 MA 收敛”
    # 解释：例如 5m 触发时，要求最近 5 根 15m K线里有一根满足 MA 收敛。
    更高周期回看根数: int = int(os.getenv("BOLL9_LOOKBACK_BARS", "5"))

    # ====== 钉钉推送 ======
    钉钉Webhook: str = os.getenv("DINGTALK_WEBHOOK_URL", "").strip()
    钉钉关键词: str = os.getenv("BOLL9_DINGTALK_KEYWORD", "布林").strip() or "布林"

    # 钉钉限制：1 分钟最多 20 条（你已明确）
    钉钉每分钟最多发送: int = int(os.getenv("BOLL9_DINGTALK_RPM_LIMIT", "20"))
