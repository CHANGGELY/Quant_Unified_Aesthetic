# -*- coding: utf-8 -*-
import logging

logger = logging.getLogger(__name__)

class CPRPEngine:
    """
    CPRP (Constant Proportion Rebalanced Portfolio) 核心算子
    目标: 维持 50% ETH / 50% USDC 的资产配比
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
        
        # ====== 买单计算 (向下阶梯) ======
        cumulative_buy_qty = 0.0  # 累计已挂买单量
        for i in range(1, grid_layers + 1):
            # 价格递减: 1x, 2x, 3x 宽度
            width_multiplier = i
            price_bid = current_price * (1 - width_multiplier * base_grid_width)
            
            # 计算在该价格下，为了达到 50% 目标，总持仓应该是多少
            estimated_equity = total_equity - position_qty * (current_price - price_bid) 
            target_pos_value = estimated_equity * self.target_ratio
            target_pos_qty = target_pos_value / price_bid
            
            # 我们需要的总持仓量 = target_pos_qty
            # 我们已有的 = position_qty
            # L1_qty + L2_qty + ... + Li_qty = target_pos_qty - position_qty
            # 所以 Li_qty = target - pos - sum(prev_layers)
            
            needed_qty = target_pos_qty - position_qty - cumulative_buy_qty
            
            # 确保每层至少 min_qty，或者如果 needed < 0 (已经买多了) 就不挂
            qty_to_place = 0.0
            
            if needed_qty > 0:
                qty_to_place = max(needed_qty, min_qty)
            elif position_qty * current_price < total_equity * 0.6: 
                 # 即使算出来不需要买，如果持仓偏低 (<60%) 且是第一层/第二层，强制挂个最小单
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
            target_pos_value = estimated_equity * self.target_ratio
            target_pos_qty = target_pos_value / price_ask
            
            # 需要卖出的量 = current_pos - target_pos - cumulative_sold
            needed_sell = position_qty - target_pos_qty - cumulative_sell_qty
            
            qty_to_place = 0.0
            
            if needed_sell > 0:
                qty_to_place = max(needed_sell, min_qty)
            elif position_qty * current_price > total_equity * 0.4:
                # 即使算出来不需要卖，如果持仓偏高 (>40%)，强制挂个最小单
                qty_to_place = min_qty
                
            if qty_to_place > 0:
                sell_orders.append({'price': price_ask, 'qty': qty_to_place})
                cumulative_sell_qty += qty_to_place
            
        return buy_orders, sell_orders
