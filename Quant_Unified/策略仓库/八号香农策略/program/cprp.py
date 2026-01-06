# -*- coding: utf-8 -*-
import logging

logger = logging.getLogger(__name__)

from 策略仓库.八号香农策略.program.leverage_model import resolve_leverage_spec, target_position_notional

class CPRPEngine:
    """
    CPRP (Constant Proportion Rebalanced Portfolio) 核心算子
    目标: 维持「持仓名义价值 X」与「空闲余额 Y」的配比（默认 50/50，即 X==Y）
    """
    def __init__(self, config):
        self.config = config
        self.target_ratio = getattr(config, 'target_ratio', 0.5) # 默认 50%

    def calculate_rebalance(self, current_price, position_qty, total_equity, base_grid_width):
        """
        计算多层网格挂单 (3层结构)
        
        :param current_price: 当前市场价
        :param position_qty: 当前持仓数量 (ETH)
        :param total_equity: 总权益 (净值计价币，如 USDC/USDT，需与 current_price 的计价币一致)
        :param base_grid_width: 基础网格宽度 (小数)
        :return: (buy_orders, sell_orders)  # lists of dicts
        """
        
        buy_orders = []
        sell_orders = []
        
        # 硬性最小下单数量 (固定 0.007 ETH)
        min_qty = 0.007
        
        # 从配置读取层数，默认 3 层
        grid_layers = getattr(self.config, 'grid_layers', 3)

        # 杠杆解析：本策略口径为「持仓名义价值 X 与 空闲余额 Y 按 target_ratio 配比」
        leverage_spec = resolve_leverage_spec(self.config, target_ratio=self.target_ratio, max_position_leverage=getattr(self.config, "max_position_leverage", None))
        z = leverage_spec.position_leverage

        # 强制双边挂单的“缓冲带”（沿用旧逻辑：target=0.5 时，相当于 [0.4,0.6]）
        # 这里统一用「持仓名义 / 权益」的比例做阈值判断，并随杠杆口径自动平移。
        band = float(getattr(self.config, "force_order_band", 0.1))
        if total_equity > 0:
            current_notional = abs(position_qty) * float(current_price)
            current_frac = current_notional / float(total_equity)
            target_notional_now = target_position_notional(float(total_equity), z, self.target_ratio)
            target_frac = target_notional_now / float(total_equity)
        else:
            current_frac = 0.0
            target_frac = 0.0
        lower_frac = target_frac - band
        upper_frac = target_frac + band
        
        # ====== 买单计算 (向下阶梯) ======
        cumulative_buy_qty = 0.0  # 累计已挂买单量
        for i in range(1, grid_layers + 1):
            # 价格递减: 1x, 2x, 3x 宽度
            width_multiplier = i
            price_bid = current_price * (1 - width_multiplier * base_grid_width)
            
            # 计算在该价格下，为了达到 50% 目标，总持仓应该是多少
            estimated_equity = total_equity - position_qty * (current_price - price_bid) 
            target_notional = target_position_notional(estimated_equity, z, self.target_ratio)
            target_pos_qty = target_notional / price_bid if price_bid > 0 else 0.0
            
            # 我们需要的总持仓量 = target_pos_qty
            # 我们已有的 = position_qty
            # L1_qty + L2_qty + ... + Li_qty = target_pos_qty - position_qty
            # 所以 Li_qty = target - pos - sum(prev_layers)
            
            needed_qty = target_pos_qty - position_qty - cumulative_buy_qty
            
            # 确保每层至少 min_qty，或者如果 needed < 0 (已经买多了) 就不挂
            qty_to_place = 0.0
            
            if needed_qty > 0:
                qty_to_place = max(needed_qty, min_qty)
            elif current_frac < upper_frac:
                 # 即使算出来不需要买，如果持仓不算太高（<= target+band），也挂最小买单保持双边流动性
                 qty_to_place = min_qty
            
            if qty_to_place > 0:
                buy_orders.append({'price': price_bid, 'qty': qty_to_place})
                cumulative_buy_qty += qty_to_place
        
        # ====== 卖单计算 (向上阶梯) ======
        cumulative_sell_qty = 0.0
        for i in range(1, grid_layers + 1):
            width_multiplier = i
            price_ask = current_price * (1 + width_multiplier * base_grid_width)
            
            estimated_equity = total_equity + position_qty * (price_ask - current_price)
            target_notional = target_position_notional(estimated_equity, z, self.target_ratio)
            target_pos_qty = target_notional / price_ask if price_ask > 0 else 0.0
            
            # 需要卖出的量 = current_pos - target_pos - cumulative_sold
            needed_sell = position_qty - target_pos_qty - cumulative_sell_qty
            
            qty_to_place = 0.0
            
            if needed_sell > 0:
                qty_to_place = max(needed_sell, min_qty)
            elif current_frac > lower_frac:
                # 即使算出来不需要卖，如果持仓不算太低（>= target-band），也挂最小卖单保持双边流动性
                qty_to_place = min_qty
                
            if qty_to_place > 0:
                sell_orders.append({'price': price_ask, 'qty': qty_to_place})
                cumulative_sell_qty += qty_to_place
            
        return buy_orders, sell_orders
