# -*- coding: utf-8 -*-
"""
保证金模式下的杠杆换算与目标仓位工具

本策略口径（用户定义）：
    - X: 持仓名义价值（B 仓位价值）
    - Y: 空闲 USDT/USDC（available balance）
    - T: 占用保证金（used margin）
    - Z: 逐笔杠杆（交易所设置的 leverage）
    - 目标：始终维持 X 与 Y 的价值比例为 target_ratio : (1-target_ratio)
      默认 target_ratio=0.5，即 X == Y

在该口径下（忽略资金费/利息/维持保证金差异），有：
    Y = E - X / Z
    X / (X + Y) = target_ratio

可解得（E 为账户权益/保证金余额 margin balance）：
    X_target = E * target_ratio / ((1-target_ratio) + target_ratio / Z)

名义杠杆（用户定义）：
    W = (X + Y) / E
      = 1 / ((1-target_ratio) + target_ratio / Z)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LeverageSpec:
    nominal_leverage: float  # W
    position_leverage: float  # Z


def nominal_from_position_leverage(position_leverage: float, target_ratio: float = 0.5) -> float:
    z = float(position_leverage)
    r = float(target_ratio)
    if z <= 0:
        raise ValueError(f"position_leverage 必须 > 0, 当前={z}")
    if not (0 < r < 1):
        raise ValueError(f"target_ratio 必须在 (0,1) 内, 当前={r}")
    return 1.0 / ((1.0 - r) + r / z)


def position_from_nominal_leverage(nominal_leverage: float, target_ratio: float = 0.5) -> float:
    w = float(nominal_leverage)
    r = float(target_ratio)
    if not (0 < r < 1):
        raise ValueError(f"target_ratio 必须在 (0,1) 内, 当前={r}")

    w_max = 1.0 / (1.0 - r)  # Z -> +inf
    if w < 1.0 or w >= w_max:
        raise ValueError(f"nominal_leverage 必须在 [1, {w_max}) 内, 当前={w}")

    denom = (1.0 / w) - (1.0 - r)
    if denom <= 0:
        raise ValueError(f"nominal_leverage={w} 与 target_ratio={r} 不兼容")
    return r / denom


def target_position_notional(equity: float, position_leverage: float, target_ratio: float = 0.5) -> float:
    e = float(equity)
    z = float(position_leverage)
    r = float(target_ratio)
    if e < 0:
        raise ValueError(f"equity 必须 >= 0, 当前={e}")
    if z <= 0:
        raise ValueError(f"position_leverage 必须 > 0, 当前={z}")
    if not (0 < r < 1):
        raise ValueError(f"target_ratio 必须在 (0,1) 内, 当前={r}")
    return e * r / ((1.0 - r) + r / z)


def available_balance(equity: float, position_notional: float, position_leverage: float) -> float:
    e = float(equity)
    x = float(position_notional)
    z = float(position_leverage)
    if z <= 0:
        raise ValueError(f"position_leverage 必须 > 0, 当前={z}")
    return e - x / z


def used_margin(equity: float, available: float) -> float:
    return float(equity) - float(available)


def resolve_leverage_spec(
    config,
    *,
    target_ratio: float = 0.5,
    max_position_leverage: float | None = None,
) -> LeverageSpec:
    """
    从 config 中解析杠杆参数，支持两种口径（二选一）：
      - nominal_leverage (W): 名义杠杆（策略层）
      - position_leverage (Z) / leverage: 逐笔杠杆（交易所设置）
    """
    r = float(target_ratio)

    w_cfg = getattr(config, "nominal_leverage", None)
    z_cfg = getattr(config, "position_leverage", None)
    z_legacy = getattr(config, "leverage", None)

    has_w = w_cfg is not None
    has_z = z_cfg is not None
    has_legacy = z_legacy is not None

    if has_w:
        w = float(w_cfg)
        z = position_from_nominal_leverage(w, r)
        if has_z:
            z2 = float(z_cfg)
            if abs(z2 - z) / max(1.0, z) > 1e-6:
                raise ValueError(f"nominal_leverage={w} 推导的 position_leverage={z:.6f} 与配置 position_leverage={z2} 不一致")
        elif has_legacy:
            z2 = float(z_legacy)
            if abs(z2 - z) / max(1.0, z) > 1e-6:
                raise ValueError(f"nominal_leverage={w} 推导的 leverage={z:.6f} 与配置 leverage={z2} 不一致")
    else:
        if has_z:
            z = float(z_cfg)
        elif has_legacy:
            z = float(z_legacy)
        else:
            z = 1.0
        if z <= 0:
            raise ValueError(f"position_leverage/leverage 必须 > 0, 当前={z}")
        w = nominal_from_position_leverage(z, r)
        if has_z and has_legacy:
            z1 = float(z_cfg)
            z2 = float(z_legacy)
            if abs(z1 - z2) / max(1.0, z1) > 1e-6:
                raise ValueError(f"position_leverage={z1} 与兼容字段 leverage={z2} 不一致，请只保留一个或保持一致")

    if max_position_leverage is None:
        max_position_leverage = getattr(config, "max_position_leverage", None) or getattr(config, "max_leverage", None)
    if max_position_leverage is not None and z > float(max_position_leverage):
        raise ValueError(f"逐笔杠杆 Z={z:.4f} 超过上限 {float(max_position_leverage):.4f}")

    return LeverageSpec(nominal_leverage=w, position_leverage=z)
