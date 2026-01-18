"""
GLFT (Gueant-Lehalle-Tapia) 定价模型逻辑
-----------------------------------------
这个文件主要负责计算“我们应该挂什么价格”。
你可以把它想象成一个精明的菜市场老板的计算器：
1. 进货（买单）和出货（卖单）的价差要多大才能赚钱？（Optimal Spread）
2. 如果库存积压太多（手里货太多），是不是该便宜点卖？（Skew/Inventory Risk）

核心公式参考了 Avellaneda-Stoikov 和后续的 GLFT 模型。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class GlftParams:
    """
    GLFT 模型的参数配置。
    就像赛车的调校参数，决定了策略是激进还是保守。
    """
    gamma: float       # 风险厌恶系数 (Risk Aversion)：你有多怕赔钱？值越大，spread 拉得越宽（越保守）。
    kappa: float       # 订单流密度参数 (Liquidity Parameter)：市场上流动性好不好？值越大，越容易成交。
    horizon_sec: float # 预测视界 (Time Horizon)：我们在乎未来几秒的风险？通常是几秒到几分钟。


def optimal_spread(sigma: float, gamma: float, kappa: float, tau: float) -> float:
    """
    计算理论上的最优价差 (Spread)。
    
    公式解释：
    Spread = 风险补偿 + 利润锁定
    
    :param sigma: 当前市场的波动率 (Volatility)，市场越晃，我们要的补偿越高。
    :param gamma: 风险厌恶系数。
    :param kappa: 市场流动性系数。
    :param tau:   剩余时间视界。
    :return:      从中间价往上和往下应该拉开的总距离 (Bid到Ask的距离)。
    """
    # 避免数学计算报错，给个极小值兜底
    sigma = max(sigma, 1e-12)
    gamma = max(gamma, 1e-12)
    kappa = max(kappa, 1e-12)
    
    # 核心公式：r(s) + ... 
    # 第一项 gamma * sigma^2 * tau 是为了补偿持有库存的风险。
    # 第二项 (2/gamma) * log(...) 是为了最大化成交概率带来的利润。
    return gamma * sigma * sigma * tau + (2.0 / gamma) * math.log(1.0 + gamma / kappa)


def glft_quotes(
    fair_price: float,
    inventory: float,
    sigma: float,
    vol_down: float,
    vol_up: float,
    toxicity: float,
    params: GlftParams,
) -> Tuple[float, float, float, float]:
    """
    计算最终的挂单价格 (SOTA 版).
    
    :param vol_down:   下行波动率 (用于 Bid Spread & Long Inventory Skew)
    :param vol_up:     上行波动率 (用于 Ask Spread & Short Inventory Skew)
    :param toxicity:   交易流毒性 (0~1)，越高价差越宽
    :return:           (买一价, 卖一价, 理论总价差, 偏斜量)
    """
    tau = max(params.horizon_sec, 1e-6)
    
    # 1. 非对称 Spread 计算
    # 下跌时的波动率 -> 决定 Bid 挂多远 (以此接针)
    spread_bid = optimal_spread(vol_down, params.gamma, params.kappa, tau)
    # 上涨时的波动率 -> 决定 Ask 挂多远
    spread_ask = optimal_spread(vol_up, params.gamma, params.kappa, tau)
    
    # 基础半宽
    half_bid = 0.5 * spread_bid
    half_ask = 0.5 * spread_ask

    # 2. 毒性扩散 (Toxicity Expansion)
    # 如果毒性 > 0.6，开始线性扩大价差，最大扩大 3 倍
    # toxicity 0.6 -> mult 1.0
    # toxicity 1.0 -> mult 3.0
    tox_mult = 1.0
    if toxicity > 0.6:
        tox_mult = 1.0 + (toxicity - 0.6) * 5.0 # (1.0-0.6)*5 = 2.0 -> total 3.0
    
    half_bid *= tox_mult
    half_ask *= tox_mult

    # 3. 算出因为库存造成的“价格偏斜” (Skew)
    # 使用方向性波动率来评估风险
    if inventory > 0:
        # 多头持有，怕跌 -> 用 vol_down
        risk_sigma = vol_down
    else:
        # 空头持有，怕涨 -> 用 vol_up
        risk_sigma = vol_up
        
    skew = inventory * params.gamma * risk_sigma * risk_sigma * tau

    # 4. 计算对 bid 和 ask 的调整量
    delta_bid = half_bid + skew  # Bid 往下压
    delta_ask = half_ask - skew  # Ask 往下压

    # 5. 算出最终挂单价
    bid_price = fair_price - max(delta_bid, 0.0)
    ask_price = fair_price + max(delta_ask, 0.0)

    # 估算的显示用 Spread (非对称下已不完全准确，取均值显示)
    effective_spread = (half_bid + half_ask) * 2.0

    return bid_price, ask_price, effective_spread, skew


def geometric_spacings(base: float, growth: float, levels: int) -> Tuple[float, ...]:
    """
    计算网格的间距（几何级数增长）。
    
    为了铺开网格，我们不想每单都隔得一样远。
    通常靠近中间价的地方单子密一点（容易成交），
    离得远的地方单子稀疏一点（防身，抓暴跌暴涨）。
    
    比如 base=1, growth=2, levels=3 -> [1, 2, 4]
    """
    return tuple(base * (growth ** i) for i in range(levels))
