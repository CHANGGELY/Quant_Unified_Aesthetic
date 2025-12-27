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

    def calculate_rebalance(self, current_price, position_qty, total_equity, grid_width):
        """
        计算再平衡订单
        
        :param current_price: 当前市场价格
        :param position_qty: 当前持仓数量 (正数为多, 0或负数视为0，因为本策略只做多现货或做多合约)
                             注意: 纯 Maker 策略通常假设持有现货或做多。如果是合约全仓模式，Short 是反向操作。
                             这里假设是标准 Long/Cash 模型。
        :param total_equity: 账户总净值 (USDT/USDC 计价)
        :param grid_width: 当前动态网格宽度 (比如 0.005)
        :return: (buy_order, sell_order)
                 order 格式: {'price': float, 'qty': float} 或 None
        """
        if current_price <= 0 or total_equity <= 0:
            return None, None

        # 1. 计算当前持仓价值和目标价值
        # 强制处理: 如果是空单，暂且当做负数处理，但 CPRP 通常用于 Spot 或 Long-Only
        # 策略描述是 ETHUSDC 50%/50%，暗示是 Long/Cash 组合
        curr_pos_val = position_qty * current_price
        
        target_pos_val = total_equity * self.target_ratio
        
        # 2. 计算挂单价格
        # 买单价: P_bid = P * (1 - X / (1+X))
        # 卖单价: P_ask = P * (1 + X)
        # 逻辑依据: 
        #   Sell: 上涨 X 比例后卖出
        #   Buy:  下跌到 "上涨 X 恢复后回到原价" 的位置? 
        #   公式源自 User Prompt: P_bid = P_market * (1 - X/(1+X)) 
        #   这意味着如果以 P_bid 买入，上涨 (1+X) 倍后价格回到 P_market ? 
        #   Validation: P_bid * (1+X) = P * (1 - X/(1+X)) * (1+X) 
        #                             = P * ((1+X-X)/(1+X)) * (1+X) 
        #                             = P * (1/(1+X)) * (1+X) = P.  Correct.
        #   Shannon's rebalancing math: Buy low so that when it goes back up we profit.
        
        price_bid = current_price * (1 - grid_width / (1 + grid_width))
        price_ask = current_price * (1 + grid_width)

        # 3. 计算数量 (核心逻辑)
        # 即使不做 Taker，我们也需要预挂单。
        # 挂单的目标是：一旦成交，仓位比例回归 50%？或者仅仅是切分资金？
        # 策略文档: "计算为了回归 50% 下一单买单需要买多少"
        
        # 场景 A: 价格跌到 P_bid
        # 假设成交，此时价格是 P_bid。
        # 我们的总资产会变吗？ Maker买入成交一瞬间资产不变（现金换币），但价格跌了，总权益缩水。
        # 简化计算：按当前时刻的 Total Equity 估算目标持仓量。
        # Target_Qty_at_Current = (Total_Equity * 0.5) / Current_Price
        # Diff = Target - Current_Pos
        # 如果 Diff > 0, 说明缺货，要在下方挂买单。
        # 如果 Diff < 0, 说明货多，要在上方挂卖单。
        
        # 为了更精确：我们希望成交后的持仓也是平衡的。
        # 但由于我们不知道成交时的确切 Total Equity (随价格变动)，通常的做法是：
        # 始终挂双边单。
        # Buy Side: 假设我们要把手中的 USDC 买入一部分变成 ETH。
        # Sell Side: 假设我们要把手中的 ETH 卖出一部分变成 USDC。
        
        # 按照双向挂单逻辑 (Grid):
        # 只有在持仓极度偏离时才只挂单边吗？
        # 不，Shannon Grid 是双边挂单。
        # 买单量: 如果价格跌到 P_bid，我们希望买入多少？
        # 经典的香农策略是固定金额定投？或是恒定比例？
        # Constant Proportion:
        #   Target Value = Equity * 0.5.
        #   我们挂单的目的是捕获波动。
        #   Prompt 指出: "计算为了回归 50% ... 需要买多少"
        #   这实际上暗示每一笔成交都在试图维持平衡。
        
        # 让我们计算 P_bid 成交时的目标数量:
        # Est_Equity_at_Bid = Cash + Pos * P_bid
        # Target_Pos_Val_at_Bid = Est_Equity_at_Bid * 0.5
        # Target_Qty_at_Bid = Target_Pos_Val_at_Bid / P_bid
        # Need_Buy_Qty = Target_Qty_at_Bid - Current_Pos
        
        # 同理计算 P_ask 成交时的目标数量:
        # Est_Equity_at_Ask = Cash + Pos * P_ask
        # Target_Pos_Val_at_Ask = Est_Equity_at_Ask * 0.5
        # Target_Qty_at_Ask = Target_Pos_Val_at_Ask / P_ask
        # Need_Sell_Qty = Current_Pos - Target_Qty_at_Ask
        
        # (1) Buy Calculation details
        # Est_Equity_at_Bid = (Total_Equity - Pos * Current_Price) + Pos * P_bid 
        #                   = Total_Equity - Pos * (Current_Price - P_bid)
        # Target_Qty_Bid    = 0.5 * Est_Equity_at_Bid / P_bid
        # Buy_Qty           = Target_Qty_Bid - Pos
        
        estimated_equity_bid = total_equity - position_qty * (current_price - price_bid)
        target_qty_bid = (estimated_equity_bid * self.target_ratio) / price_bid
        buy_qty = target_qty_bid - position_qty
        
        # (2) Sell Calculation details
        estimated_equity_ask = total_equity + position_qty * (price_ask - current_price)
        target_qty_ask = (estimated_equity_ask * self.target_ratio) / price_ask
        sell_qty = position_qty - target_qty_ask
        
        buy_order = None
        sell_order = None
        
        # 只有当计算出的数量 > 0 时才挂单
        # 甚至可以加一个最小阈值，防止微小碎单
        min_qty_notional = 10.0 # 假设最小下单价值 10U
        
        if buy_qty * price_bid > min_qty_notional:
            buy_order = {'price': price_bid, 'qty': buy_qty}
            
        if sell_qty * price_ask > min_qty_notional:
            sell_order = {'price': price_ask, 'qty': sell_qty}
            
        return buy_order, sell_order
