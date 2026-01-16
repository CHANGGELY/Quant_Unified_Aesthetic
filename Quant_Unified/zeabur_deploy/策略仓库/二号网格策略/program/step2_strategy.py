"""
Quant Unified 量化交易系统
[网格策略核心逻辑]
功能：实现等差/等比网格生成、挂单逻辑、仓位管理及盈亏计算，是策略运行的“大脑”。
"""

# 导入 Enum (枚举) 模块，用于定义一组固定的选项（比如：做多还是做空）
from enum import Enum
# 导入 math 数学模块，用于进行复杂的数学计算（如指数、对数等）
import math
# 导入类型提示模块，帮助代码编辑器提示变量应该是什么类型（如：字典 Dict、列表 List、任意类型 Any）
from typing import Dict, List, Any
# 导入我们自己写的“爆仓检查器”，用于计算风险，防止亏损超过本金
from 基础库.common_core.risk_ctrl.liquidation import LiquidationChecker

# 定义网格间隔模式的枚举（选项列表）
class Interval_mode(Enum):
    AS = "arithmetic_sequence" # 等差数列：每格价格差是固定的（例如：100, 101, 102... 差都是1）
    GS = "geometric_sequence"  # 等比数列：每格涨跌幅度是固定的（例如：100, 110, 121... 涨幅都是10%）

# 定义交易方向模式的枚举
class Direction_mode(Enum):
    NEUTRAL = "neutral" # 中性：既不做多也不做空（通常用于观望，或者双向网格）
    LONG = "long"       # 做多：看涨，低买高卖
    SHORT = "short"     # 做空：看跌，高卖低买

# 定义一个极小值 epsilon，用于浮点数比较，防止因为计算机精度问题导致 1.0 != 0.999999999
eps = 0.000001

# 定义网格策略类，这是策略的“蓝图”
class GridStrategy:
    """
    2号网格策略核心逻辑
    这是整个策略的大脑，负责决定什么时候买、什么时候卖、买卖多少。
    """
    
    # 初始化函数：当策略启动时，第一个执行的函数，用于设置初始状态
    def __init__(self, config):
        """
        初始化策略
        :param config: 配置参数，包含了用户设置的所有选项（如本金、杠杆、币种等）
        """
        # 1. 处理配置参数
        # 检查 config 是否是一个对象（有 to_dict 方法），如果是，转换成字典格式方便取值
        if hasattr(config, 'to_dict'):
            cfg = config.to_dict()
        else:
            cfg = config
            
        # 保存配置到 self.config，方便后续使用
        self.config = cfg
        # 获取交易对名称，默认为 'ETHUSDT'
        self.symbol = cfg.get('symbol', 'ETHUSDT')
        # 获取初始本金，默认为 10000 U
        self.money = cfg.get('money', 10000)
        # 获取杠杆倍数，默认为 1倍（不加杠杆）
        self.leverage = cfg.get('leverage', 1)
        
        # 2. 解析网格模式配置
        # 获取用户设置的间隔模式，默认为 'geometric_sequence' (等比)
        im_str = cfg.get('interval_mode', 'geometric_sequence')
        # 如果是 "arithmetic_sequence"，设置为等差模式
        if im_str == "arithmetic_sequence":
            self.interval_mode = Interval_mode.AS
        else:
            # 否则设置为等比模式
            self.interval_mode = Interval_mode.GS
            
        # 3. 解析交易方向配置
        # 获取用户设置的方向，默认为 'neutral'
        dm_str = cfg.get('direction_mode', 'neutral')
        if dm_str == "long":
            self.direction_mode = Direction_mode.LONG
        elif dm_str == "short":
            self.direction_mode = Direction_mode.SHORT
        else:
            self.direction_mode = Direction_mode.NEUTRAL
            
        # 获取资金利用率，默认为 0.5 (即只用 50% 的钱跑网格，留 50% 备用)
        self.capital_ratio = cfg.get('capital_ratio', 0.5)
        self.capital_weight = cfg.get('capital_weight', 1.0)
        
        # 4. 获取高级开关配置
        # 是否允许网格整体向上平移（当价格涨破上限时，网格跟着上移，防止踏空）
        self.enable_upward_shift = cfg.get('enable_upward_shift', False)
        # 是否允许网格整体向下平移（当价格跌破下限时，网格跟着下移，防止套牢）
        self.enable_downward_shift = cfg.get('enable_downward_shift', False)
        # 停止上移的价格（涨到这个价就不追了）
        self.stop_up_price = cfg.get('stop_up_price', 0)
        # 停止下移的价格（跌到这个价就不跟了）
        self.stop_down_price = cfg.get('stop_down_price', 0)
        
        # 新增：复利模式配置 (默认 False，如果开启，赚了钱会自动加大投入)
        self.enable_compound = cfg.get('enable_compound', False)
        
        # 5. 获取网格核心参数
        # 网格数量：要把区间分成多少格
        self.num_steps = cfg.get('num_steps', 100)
        # 网格最低价（下限）
        self.min_price = cfg.get('min_price', 0)
        # 网格最高价（上限）
        self.max_price = cfg.get('max_price', 0)
        
        # 动态价格区间比例：如果设置非0（如0.2），则会忽略上面的 min/max_price，
        # 而是根据当前价格动态计算：上限 = 当前价*(1+0.2)，下限 = 当前价*(1-0.2)
        self.price_range = cfg.get('price_range', 0)
        self.post_only = cfg.get('post_only', True)
        self.post_only_tick_offset_buy = int(cfg.get('post_only_tick_offset_buy', 1))
        self.post_only_tick_offset_sell = int(cfg.get('post_only_tick_offset_sell', 1))
        self.post_only_reject_retry_limit = int(cfg.get('post_only_reject_retry_limit', 2))
        self.tick_size = float(cfg.get('tick_size', 0.01))
        self.qty_precision = cfg.get('qty_precision')
        
        # 6. 初始化运行时变量
        # 当前最新的市场价格
        self.curr_price = 0
        # 记录最大亏损（用于统计回撤）
        self.max_loss = 0
        # 记录最大盈利
        self.max_profit = 0
        
        # 记录网格平移的日志（什么时候移动了网格）
        self.shift_logs = []
        # 统计向上平移了多少次
        self.upward_shift_count = 0
        # 统计向下平移了多少次
        self.downward_shift_count = 0
        
        # 初始化策略的内部状态字典（包含持仓、均价等重要数据）
        self.grid_dict = {}
        self.account_dict = {}
        self._init_strategy_state()
        
        # 7. 初始化风控模块
        # LiquidationChecker 像是一个“裁判”，时刻盯着你的账户。
        # 这里假设维持保证金率为 0.5% (Binance 交易所的标准)，如果权益低于这个比例就会爆仓。
        self.risk_ctrl = LiquidationChecker(min_margin_rate=0.005) 
        # 标记是否已经爆仓（如果 True，游戏结束）
        self.is_liquidated = False
        
        # [新增] 实盘模式标记：如果为 True，update_price 触发的 update_order 不会修改持仓和利润
        # 只有显式传入 actual_qty 的调用（如来自实盘成交回调）才会更新状态
        self.is_live = cfg.get('is_live', False)
        
        # 外部风控开关 (若为 True，则策略自己不判断爆仓，而是由外部的“组合模拟器”统一管理)
        # 这在多策略组合回测时很有用，因为要看总账户是否爆仓，而不是单个策略。
        self.external_risk_control = cfg.get('external_risk_control', False)

    # 初始化策略状态的辅助函数
    def _init_strategy_state(self):
        # grid_dict 存储网格的几何属性
        self.grid_dict = {
            "interval": 0,          # 网格间距（每格多少钱或百分比）
            "price_central": 0,     # 网格中枢价格（当前所在的格子线）
            "one_grid_quantity": 0, # 每一格的标准下单数量
            "max_price": 0,         # 当前网格上限
            "min_price": 0,         # 当前网格下限
        }

        # account_dict 存储账户的资金和持仓状态
        self.account_dict = {
            "positions_grids": 0,   # 逻辑持仓数：净持有多少个格子的单子（整数，+3表示持有3格多单）
            "positions_qty": 0.0,   # 真实持仓数量：实际持有的币数（浮点数，如 1.5 ETH）
            "pairing_count": 0,     # 配对次数：成功低买高卖（或高卖低买）了多少次
            "pair_profit": 0,       # 已实现利润：落袋为安的钱
            "positions_cost": 0,    # 持仓成本价：当前持仓的平均买入价
            "positions_profit": 0,  # 浮动盈亏：当前持仓账面上的赚赔（还没卖出的）
            "avg_price": 0,         # 加权平均持仓价格
            "pending_orders": [],   # 挂单列表（实盘时用，回测中暂未深度使用）
            "up_price": 0,          # 上方最近的一根网格线价格
            "down_price": 0,        # 下方最近的一根网格线价格
            "entry_price": 0,       # [新增] 初始/最近一次重置时的入场价格
            "base_price": 0,        # [新增] 策略基准价格
        }

    # [新增] 检查并执行趋势跟随重置 (Trend Follow Re-entry)
    def check_trend_reentry(self, current_price, other_position_value=0.0):
        """
        检查是否触发趋势跟随重置：
        当价格突破网格上限(做多时)且持仓过低(或对冲比例不足)时，强制重置中枢并追涨建仓
        """
        if self.direction_mode != Direction_mode.LONG:
            return False

        # 1. 检查价格是否突破上限
        grid_upper = float(self.grid_dict.get('max_price', 0) or 0)
        # 只有当确实设置了上限且价格显著突破(>0.1%)时才触发
        if grid_upper <= 0 or current_price <= grid_upper * 1.001:
            return False

        # 2. 检查持仓/对冲状态
        should_reset = False
        min_hedge_ratio = float(self.config.get('min_hedge_ratio', 0.1))
        
        pos_qty = float(self.account_dict.get('positions_qty', 0) or 0)
        current_value = abs(pos_qty * current_price)

        if other_position_value > 0:
            current_ratio = current_value / other_position_value
            if current_ratio < min_hedge_ratio:
                # print(f"[{self.symbol}] 趋势卖飞触发: 价格{current_price} > {grid_upper}, 比例{current_ratio:.2f} < {min_hedge_ratio}")
                should_reset = True
        else:
            # 单腿模式：如果持仓小于0.5格
            one_grid = float(self.grid_dict.get('one_grid_quantity', 0) or 0)
            if one_grid > 0 and pos_qty < one_grid * 0.5:
                # print(f"[{self.symbol}] 趋势卖飞触发(单腿): 持仓过低 < 0.5格")
                should_reset = True

        if should_reset:
            self._execute_trend_reset(current_price, other_position_value)
            return True
        return False

    def _execute_trend_reset(self, current_price, other_position_value=0.0):
        """
        执行重置逻辑：更新中枢，买入底仓
        """
        # 1. 重置中枢
        self.account_dict['base_price'] = current_price
        self.account_dict['entry_price'] = current_price
        self.curr_price = current_price
        self._initialize_grid_params() # 重新计算网格

        # 2. 计算需要买入的数量
        target_hedge_ratio = float(self.config.get('target_hedge_ratio', 0.4))
        buy_qty = 0.0

        if other_position_value > 0:
            target_value = other_position_value * target_hedge_ratio
            current_pos = float(self.account_dict.get('positions_qty', 0) or 0)
            current_value = abs(current_pos * current_price)
            missing_value = max(0, target_value - current_value)
            buy_qty = missing_value / current_price
        else:
            # 保底买入 10 格
            one_grid = float(self.grid_dict.get('one_grid_quantity', 0) or 0)
            buy_qty = one_grid * 10
        
        # 3. 执行买入 (直接更新持仓)
        if buy_qty > 0:
             # update_order 模拟成交
             # 注意：这是模拟市价单，直接增加持仓，并更新均价
             self.update_order(None, current_price, 'BUY', actual_qty=buy_qty)
             # print(f"[{self.symbol}] 趋势重置买入: {buy_qty:.4f}")

    # [新增] 检查并自动构建底仓 (Auto Build Position)
    def check_auto_build(self, current_price, other_position_value=0.0):
        """
        检查是否需要自动构建底仓 (通常在策略初期或对冲端加仓后触发)
        """
        if not self.config.get('auto_build_position', False):
            return False
            
        if self.direction_mode != Direction_mode.LONG:
            return False

        min_hedge_ratio = float(self.config.get('min_hedge_ratio', 0.1))
        
        pos_qty = float(self.account_dict.get('positions_qty', 0) or 0)
        current_value = abs(pos_qty * current_price)
        
        should_build = False
        target_qty = 0.0

        if other_position_value > 0:
             current_ratio = current_value / other_position_value
             if current_ratio < min_hedge_ratio:
                 should_build = True
                 target_hedge_ratio = float(self.config.get('target_hedge_ratio', 0.4))
                 target_value = other_position_value * target_hedge_ratio
                 missing = max(0, target_value - current_value)
                 target_qty = missing / current_price
        else:
             # 单腿模式: 如果持仓几乎为0
             one_grid = float(self.grid_dict.get('one_grid_quantity', 0) or 0)
             if one_grid > 0 and pos_qty < one_grid * 0.1:
                 should_build = True
                 target_qty = one_grid * 15 # 初始建仓 15 格
        
        if should_build and target_qty > 0:
             self.update_order(None, current_price, 'BUY', actual_qty=target_qty)
             # print(f"[{self.symbol}] 自动补仓: {target_qty:.4f}")
             return True
        return False


    # 策略启动后的第二次初始化（通常在有了第一个价格数据后调用）
    def init(self):
        # 如果已经获取到了当前价格，就开始计算网格的具体参数
        if self.curr_price != 0:
            self._initialize_grid_params()

    # 核心函数：当收到每一个新的价格数据 (Tick) 时调用
    def on_tick(self, timestamp, price):
        # 调用 update_price 来处理价格变化逻辑
        self.update_price(timestamp, price)

    # K线结束时的回调（目前为空，因为主要逻辑都在 on_tick 处理了）
    def on_bar(self, bar):
        # 我们在 on_tick 中处理价格变动，所以 on_bar 仅用于同步（如果需要）
        pass

    '''------------------------------ 策略计算工具 ------------------------------'''

    # 计算给定价格下方的下一个网格线价格
    def get_down_price(self, price):
        # 如果是等比数列
        if self.interval_mode == Interval_mode.GS:
            # 下一个价格 = 当前价格 / (1 + 涨幅比例)
            # 例如：涨幅10%，当前110，下方就是 110 / 1.1 = 100
            down_price = price / (1 + self.grid_dict["interval"])
        # 如果是等差数列
        elif self.interval_mode == Interval_mode.AS:
            # 下一个价格 = 当前价格 - 固定差价
            down_price = price - self.grid_dict["interval"]
        return down_price

    # 计算给定价格上方的下一个网格线价格
    def get_up_price(self, price):
        # 如果是等比数列
        if self.interval_mode == Interval_mode.GS:
            # 上一个价格 = 当前价格 * (1 + 涨幅比例)
            up_price = price * (1 + self.grid_dict["interval"])
        # 如果是等差数列
        elif self.interval_mode == Interval_mode.AS:
            # 上一个价格 = 当前价格 + 固定差价
            up_price = price + self.grid_dict["interval"]
        return up_price

    # 获取当前持仓的成本价
    def get_positions_cost(self):
        """
        获取当前持仓成本 (会计成本 / 加权平均价)
        """
        return self.account_dict["avg_price"]

    # 计算当前持仓的浮动盈亏（Unrealized PnL）
    def get_positions_profit(self, price):
        """
        计算浮动盈亏
        公式：(当前市价 - 平均持仓价) * 持仓数量
        """
        # 注意: positions_qty 是有正负的 (+为多头, -为空头)
        # 如果做多 (Qty>0): 价格(Price) > 均价(Avg) -> 赚钱 (正数)
        # 如果做空 (Qty<0): 价格(Price) > 均价(Avg) -> 亏钱 (负数，因为负数乘正差值 = 负数)
        positions_profit = (price - self.account_dict["avg_price"]) * self.account_dict["positions_qty"]
        return positions_profit

    # 计算网格的间距 (Interval)
    def get_interval(self):
        max_value = self.max_price
        min_value = self.min_price
        num_elements = self.num_steps

        # 等比数列公式推导：Max = Min * (1+r)^N
        # 所以 1+r = (Max/Min)^(1/N)
        # r = (Max/Min)^(1/N) - 1
        if self.interval_mode == Interval_mode.GS:
            interval = (max_value / min_value) ** (1 / num_elements) - 1
        # 等差数列公式：Interval = (Max - Min) / N
        elif self.interval_mode == Interval_mode.AS:
            interval = (max_value - min_value) / num_elements
        return interval

    # 根据新价格，找到离它最近的那根网格线作为“中枢”
    def get_price_central(self, new_price):
        max_value = self.max_price
        min_value = self.min_price
        num_elements = self.num_steps

        # 生成所有网格线的价格列表
        if self.interval_mode == Interval_mode.GS:
            interval = (max_value / min_value) ** (1 / num_elements)
            price_list = [min_value * (interval ** i) for i in range(num_elements + 1)]
        elif self.interval_mode == Interval_mode.AS:
            interval = (max_value - min_value) / num_elements
            price_list = [min_value + (interval * i) for i in range(num_elements + 1)]

        # 在列表中找到和 new_price 差值最小的那个价格
        price_central = min(price_list, key=lambda x: abs(x - new_price))
        return price_central

    # 计算每一格应该买卖多少数量 (Base Quantity)
    def _get_price_list(self):
        """生成完整的网格价格列表"""
        max_value = self.max_price
        min_value = self.min_price
        num_elements = self.num_steps
        if self.interval_mode == Interval_mode.GS:
            interval = (max_value / min_value) ** (1 / num_elements)
            return [min_value * (interval ** i) for i in range(num_elements + 1)]
        elif self.interval_mode == Interval_mode.AS:
            interval = (max_value - min_value) / num_elements
            return [min_value + (interval * i) for i in range(num_elements + 1)]
        return []

    def get_one_grid_quantity(self):
        max_value = self.max_price
        min_value = self.min_price
        num_elements = self.num_steps
        
        # 重新生成网格价格列表
        price_list = self._get_price_list()
        if not price_list: return 0

        base_qty = self.money * self.leverage * self.capital_ratio / sum(price_list)
        if self.qty_precision is not None:
            # [优化] 为了应对 PAPI 100U 限制，我们在这里加入微量的 eps 补偿 (1e-9)，
            # 防止由于浮点数计算误差导致 0.001299... 被截断成 0.001。
            # 这能显著降低因精度损失导致金额刚好低于 100U 的概率。
            factor = 10 ** int(self.qty_precision)
            base_qty = int((base_qty + 1e-9) * factor) / factor
        return base_qty

    def get_expected_profit_rate(self, ref_price=None):
        p = ref_price if ref_price else self.grid_dict.get("price_central", 0) or self.curr_price
        if self.interval_mode == Interval_mode.GS:
            return self.grid_dict["interval"]
        elif self.interval_mode == Interval_mode.AS:
            if p and p > 0:
                return self.grid_dict["interval"] / p
            return 0
        return 0

    def get_expected_profit_amount(self, ref_price=None):
        p = ref_price if ref_price else self.grid_dict.get("price_central", 0) or self.curr_price
        qty = self.grid_dict.get("one_grid_quantity", 0) or self.get_one_grid_quantity()
        if self.interval_mode == Interval_mode.GS:
            return p * self.grid_dict["interval"] * qty
        elif self.interval_mode == Interval_mode.AS:
            return self.grid_dict["interval"] * qty
        return 0

    # 计算单次网格交易的已实现利润 (Pair Profit)
    def get_pair_profit(self, price, side, trade_qty):
        """
        计算配对利润：当完成一次“低买高卖”或“高卖低买”时，赚了多少钱。
        :param trade_qty: 本次成交的数量
        """
        # 如果是等比网格
        if self.interval_mode == Interval_mode.GS:
            if side == "SELL":
                # 卖出触发利润（说明之前是低价买入的）
                # 利润 = 卖出金额 - 买入金额
                # 买入价推算 = 当前卖出价 / (1 + 间距)
                # 利润公式推导见下行注释
                pair_profit = (price / (1 + self.grid_dict["interval"])) * self.grid_dict["interval"] * trade_qty
            elif side == "BUY":
                # 买入触发利润（说明之前是高价卖空，现在低价买回平仓）
                # 利润 = 卖出金额 - 买入金额
                # 卖出价推算 = 当前买入价 * (1 + 间距)
                pair_profit = price * self.grid_dict["interval"] * trade_qty
        # 如果是等差网格
        elif self.interval_mode == Interval_mode.AS:
            # 等差很简单：价差 * 数量
            pair_profit = self.grid_dict["interval"] * trade_qty
        else:
            pair_profit = 0
        return pair_profit

    # 初始化网格参数的入口函数
    def _initialize_grid_params(self, force=False):
        """
        根据当前价格 (self.curr_price) 初始化网格的所有参数。
        [优化] 引入 force 参数，仅在必要时（如初始启动、或价格破网）才重新计算区间。
        """
        # 如果开启了动态价格区间 (price_range != 0)
        if self.price_range != 0:
            # 修改：只要设置了 price_range，初次启动(initialized=False)或者强制重算时，
            # 都必须忽略硬编码的 max_price，以保证动态区间生效。
            initialized = getattr(self, '_initialized_once', False)
            if force or not initialized:
                # 标记已经根据动态区间初始化过一次
                self._initialized_once = True
                print(f"[{self.symbol}] 触发区间重置 | 原因: {'越界' if force else '初始化'} | 当前价: {self.curr_price:.2f}")
                self.max_price = self.curr_price * (1 + self.price_range)
                self.min_price = self.curr_price * (1 - self.price_range)
            else:
                # 否则保持现有的 max/min 不动，这样网格线就不会随着市价每一跳而抖动
                pass
        
        # 计算并保存各项网格参数
        self.grid_dict["interval"] = self.get_interval()
        self.grid_dict["max_price"] = self.max_price
        self.grid_dict["min_price"] = self.min_price
        self.grid_dict["one_grid_quantity"] = self.get_one_grid_quantity()
        
        # [优化] 区间包围逻辑：找到包围当前价格的上下两根网格线
        price_list = self._get_price_list()
        if not price_list: return

        # 寻找当前价格所在的区间 [down, up]
        if self.curr_price <= price_list[0] + eps:
            down = self.get_down_price(price_list[0])
            up = price_list[0]
        elif self.curr_price >= price_list[-1] - eps:
            down = price_list[-1]
            up = self.get_up_price(price_list[-1])
        else:
            # 正常范围内，通过遍历找到紧邻 current_price 的两个点
            idx = 0
            for i in range(len(price_list) - 1):
                if price_list[i] <= self.curr_price + eps:
                    idx = i
                else:
                    break
            down = price_list[idx]
            up = price_list[idx + 1]

        self.grid_dict["price_central"] = down # 兼容性保留
        self.account_dict["up_price"] = up
        self.account_dict["down_price"] = down

        # 中文翻译映射
        TRANS_MAP = {
            'interval': '网格间距',
            'price_central': '中枢价格',
            'one_grid_quantity': '单格数量',
            'max_price': '网格上限',
            'min_price': '网格下限',
            'positions_grids': '持仓格数',
            'positions_qty': '持仓数量',
            'pairing_count': '配对次数',
            'pair_profit': '配对利润',
            'positions_cost': '持仓成本',
            'positions_profit': '持仓浮盈',
            'avg_price': '持仓均价',
            'pending_orders': '挂单列表',
            'up_price': '上方网格',
            'down_price': '下方网格'
        }

        def _format_dict(d):
            items = []
            for k, v in d.items():
                cn_key = TRANS_MAP.get(k, k)
                if k == 'interval' and self.interval_mode == Interval_mode.GS:
                    # 等比网格：显示百分比和近似价格间距
                    approx_gap = self.curr_price * v
                    val_str = f"{v:.2%} (约 {approx_gap:.2f})"
                elif isinstance(v, float):
                    val_str = f"{v:.4f}"
                else:
                    val_str = str(v)
                items.append(f"{cn_key}: {val_str}")
            return " | ".join(items)

        print(f"网格初始化完成: {_format_dict(self.grid_dict)}")
        print(f"账户初始化完成: {_format_dict(self.account_dict)}")

    # 计算当前这一单应该下单多少数量 (包含复利逻辑)
    def get_current_trade_qty(self, price):
        """
        计算当前下单数量 (支持复利)
        """
        base_qty = self.grid_dict["one_grid_quantity"]
        
        # 如果开启了复利模式
        if self.enable_compound:
             # 计算当前总权益 = 初始本金 + 已实现利润 + 浮动盈亏
             realized = self.account_dict["pair_profit"]
             unrealized = self.get_positions_profit(price)
             equity = self.money + realized + unrealized
             
             # 计算缩放系数：当前权益 / 初始本金
             # 如果赚了10%，系数就是1.1，下单量也增加10%
             scale = max(0, equity / self.money)
             trade_qty = base_qty * scale
        else:
             # 没开复利，就用固定下单量
             trade_qty = base_qty
        if self.qty_precision is not None:
            factor = 10 ** int(self.qty_precision)
            trade_qty = int(trade_qty * factor) / factor
        return trade_qty

    # 核心交易执行逻辑：更新订单、持仓和利润
    def update_order(self, ts, price, side, actual_qty=None):
        # 1. 检查网格是否需要向上平移
        # 如果价格冲破了最高价，且开启了自动上移
        if price > self.grid_dict["max_price"] and self.enable_upward_shift:
            can_shift = True
            if can_shift:
                # 检查是否触及了“停止上移价格”
                if self.stop_up_price and price >= self.stop_up_price:
                    print(f'{ts} 达到停止上移价格，停止上移')
                    self.shift_logs.append({"ts": ts, "type": "stop_up", "price": price})
                    self.enable_upward_shift = False
                else:
                    # 执行上移操作：所有网格线统统上移一格
                    oc = self.grid_dict["price_central"]
                    omin = self.grid_dict["min_price"]
                    omax = self.grid_dict["max_price"]
                    
                    # 重新计算中枢、下限、上限
                    self.grid_dict["price_central"] = self.get_up_price(self.grid_dict["price_central"])
                    self.grid_dict["min_price"] = self.get_up_price(self.grid_dict["min_price"])
                    self.grid_dict["max_price"] = self.get_up_price(self.grid_dict["max_price"])
                    
                    nc = self.grid_dict["price_central"]
                    nmin = self.grid_dict["min_price"]
                    nmax = self.grid_dict["max_price"]
                    
                    self.upward_shift_count += 1
                    # 记录日志
                    self.shift_logs.append({"ts": ts, "type": "up", "price": price, "old_central": oc, "new_central": nc, "old_min": omin, "new_min": nmin, "old_max": omax, "new_max": nmax})
                    print(f'{ts} 上移一格 中枢 {oc:.2f}->{nc:.2f} 上限 {omax:.2f}->{nmax:.2f} 下限 {omin:.2f}->{nmin:.2f}')

        # 2. 检查网格是否需要向下平移
        # 逻辑同上，只是方向相反
        if price < self.grid_dict["min_price"] and self.enable_downward_shift:
            if self.stop_down_price and price <= self.stop_down_price:
                print(f'{ts} 达到停止下移价格，停止下移')
                self.shift_logs.append({"ts": ts, "type": "stop_down", "price": price})
                self.enable_downward_shift = False
            else:
                oc = self.grid_dict["price_central"]
                omin = self.grid_dict["min_price"]
                omax = self.grid_dict["max_price"]
                
                self.grid_dict["price_central"] = self.get_down_price(self.grid_dict["price_central"])
                self.grid_dict["min_price"] = self.get_down_price(self.grid_dict["min_price"])
                self.grid_dict["max_price"] = self.get_down_price(self.grid_dict["max_price"])
                
                nc = self.grid_dict["price_central"]
                nmin = self.grid_dict["min_price"]
                nmax = self.grid_dict["max_price"]
                
                self.downward_shift_count += 1
                self.shift_logs.append({"ts": ts, "type": "down", "price": price, "old_central": oc, "new_central": nc, "old_min": omin, "new_min": nmin, "old_max": omax, "new_max": nmax})
                print(f'{ts} 下移一格 中枢 {oc:.2f}->{nc:.2f} 上限 {omax:.2f}->{nmax:.2f} 下限 {omin:.2f}->{nmin:.2f}')

        # 3. 检查方向模式 (Long Only / Short Only)
        should_execute = True
        # 如果是只做多模式
        if self.direction_mode == Direction_mode.LONG:
            # 如果要卖出 (SELL)，且当前没有多单持仓 (positions_grids <= 0)，则禁止开空单
            # 也就是说：只允许平多单，不允许开空单
            if side == "SELL" and self.account_dict["positions_grids"] <= 0:
                should_execute = False
        # 如果是只做空模式
        elif self.direction_mode == Direction_mode.SHORT:
            # 如果要买入 (BUY)，且当前没有空单持仓 (positions_grids >= 0)，则禁止开多单
            if side == "BUY" and self.account_dict["positions_grids"] >= 0:
                should_execute = False

        # 如果被禁止交易，更新下一次的监控价格然后返回
        # 但如果是实盘传入了 actual_qty，说明交易已经发生，强制执行更新
        if not should_execute and actual_qty is None:
            self.account_dict["down_price"] = self.get_down_price(price)
            self.account_dict["up_price"] = self.get_up_price(price)
            return

        # [核心修复] 在实盘模式下，由 update_price 触发的模拟调用不应更新持仓和利润
        # 只有真正成交（传入 actual_qty）时才执行状态更新
        if getattr(self, 'is_live', False) and actual_qty is None:
            # 仅更新边界，不更新持仓
            self.account_dict["down_price"] = self.get_down_price(price)
            self.account_dict["up_price"] = self.get_up_price(price)
            return

        # 4. 执行交易
        # 计算下单数量
        if actual_qty is not None:
            trade_qty = actual_qty
        else:
            trade_qty = self.get_current_trade_qty(price)
            # 如果配置了数量精度，立即对理论下单数量进行截断
            # 这样可以确保利润计算 (pair_profit) 也是基于真实的“可成交数量”
            if self.qty_precision is not None:
                factor = 10 ** int(self.qty_precision)
                trade_qty = int(trade_qty * factor) / factor

        # 记录交易前的持仓状态
        curr_qty = self.account_dict["positions_qty"]
        avg_price = self.account_dict["avg_price"]
        
        # 确定交易方向符号：买入为正，卖出为负
        signed_trade_qty = trade_qty if side == "BUY" else -trade_qty
        
        # 5. 更新持仓均价 (Weighted Average Price)
        # 判断是加仓(Increasing)还是减仓(Closing)
        is_increasing = False
        
        # 情况A: 之前空仓，现在开仓 -> 加仓
        if abs(curr_qty) < 1e-9: 
            is_increasing = True
        # 情况B: 之前有多单，现在继续买 -> 加仓
        elif (curr_qty > 0 and side == "BUY"):
            is_increasing = True
        # 情况C: 之前有空单，现在继续卖 -> 加仓
        elif (curr_qty < 0 and side == "SELL"):
            is_increasing = True
            
        if is_increasing:
             # 加仓逻辑：重新计算加权平均价
             # 公式：(旧持仓量*旧均价 + 新成交量*新价格) / 总持仓量
             old_val = abs(curr_qty) * avg_price
             new_val = trade_qty * price
             new_total_qty = abs(curr_qty) + trade_qty
             if new_total_qty > 0:
                self.account_dict["avg_price"] = (old_val + new_val) / new_total_qty
        else:
             # 减仓逻辑：均价不变（因为只是卖出了一部分，剩下的成本价不变）
             # 除非发生“反手”（从多头变成空头，或者反之）
             remaining = curr_qty + signed_trade_qty
             
             # 检查是否反手 (符号改变了)
             if (curr_qty > 0 and remaining < 0) or (curr_qty < 0 and remaining > 0):
                 # 如果反手了，剩余部分的成本价就是当前市价
                 self.account_dict["avg_price"] = price
             elif abs(remaining) < 1e-9:
                 # 如果完全平仓了，成本价归零
                 self.account_dict["avg_price"] = 0
                 
        # 6. 更新持仓数量
        self.account_dict["positions_qty"] += signed_trade_qty
        if self.qty_precision is not None:
            factor = 10 ** int(self.qty_precision)
            self.account_dict["positions_qty"] = int(self.account_dict["positions_qty"] * factor) / factor
        
        # 7. 更新逻辑网格持仓数 (+1/-1)
        if side == "BUY":
            self.account_dict["positions_grids"] += 1
        else:
            self.account_dict["positions_grids"] -= 1

        # 8. 更新利润统计
        # 更新持仓成本
        self.account_dict["positions_cost"] = self.get_positions_cost()
        # 更新浮动盈亏
        self.account_dict["positions_profit"] = self.get_positions_profit(price)
        
        # 9. 检查是否完成配对 (Realize Profit)
        # 逻辑：如果买入后网格数归零或变正（做空回补），或者卖出后网格数归零或变负（做多止盈）
        # 简单来说：只要是“减仓”操作，就视为一次配对
        if side == "BUY" and self.account_dict["positions_grids"] <= 0:
            self.account_dict["pairing_count"] += 1
            self.account_dict["pair_profit"] += self.get_pair_profit(price, side, trade_qty)
        elif side == "SELL" and self.account_dict["positions_grids"] >= 0:
            self.account_dict["pairing_count"] += 1
            self.account_dict["pair_profit"] += self.get_pair_profit(price, side, trade_qty)

        # 10. 更新最大盈亏记录
        pl = self.account_dict["positions_profit"] + self.account_dict["pair_profit"]
        self.max_loss = min(pl, self.max_loss)
        self.max_profit = max(pl, self.max_profit)

        # 11. 更新下一次的监控价格
        # 11. 更新下一次的监控价格
        # [优化] 消除真空带的核心：根据成交方向，将成交价格设为一侧边界，
        # 另一侧边界则向相反方向跳一格。从而保证买卖单间距始终为 1 个 interval。
        if side == "BUY":
            # 刚跌破 down_price 完成买入 -> 此时价格在 grid_line 上
            # 下一个卖出点就是刚刚买入的点 (price)，下一个买入点是更下方的一个点
            base_up = price
            base_down = self.get_down_price(price)
        else:
            # 刚涨破 up_price 完成卖出 -> 此时价格在 grid_line 上
            # 下一个买入点就是刚刚卖出的点 (price)，下一个卖出点是更上方的一个点
            base_down = price
            base_up = self.get_up_price(price)

        adj_down = base_down - self.tick_size * self.post_only_tick_offset_buy if self.post_only else base_down
        adj_up = base_up + self.tick_size * self.post_only_tick_offset_sell if self.post_only else base_up
        self.account_dict["down_price"] = adj_down
        self.account_dict["up_price"] = adj_up

    # 核心价格更新循环
    def update_price(self, ts, new_price):
        # 如果已经爆仓，停止一切操作
        if self.is_liquidated:
            return

        # 如果是第一次收到价格，进行初始化
        if self.curr_price == 0:
             self.curr_price = new_price
             self._initialize_grid_params()
             return

        # --- 风控检查 (Risk Control) ---
        # 每次价格变动，都要检查是否爆仓
        if not self.external_risk_control:
            # 计算总权益
            realized_pnl = self.account_dict["pair_profit"]
            unrealized_pnl = self.get_positions_profit(new_price)
            current_equity = self.money + realized_pnl + unrealized_pnl
            
            # 计算持仓名义价值 (用于计算保证金需求)
            position_value = abs(self.account_dict["positions_qty"]) * new_price
            
            # 调用风控模块检查
            is_liq, margin_rate = self.risk_ctrl.check_margin_rate(current_equity, position_value)
            
            if is_liq:
                print(f"💀 触发爆仓! 时间: {ts}, 价格: {new_price}, 权益: {current_equity:.2f}, 持仓价值: {position_value:.2f}, 保证金率: {margin_rate:.2%}")
                self.is_liquidated = True
                # 清空所有持仓状态
                self.account_dict["positions_grids"] = 0
                self.account_dict["positions_qty"] = 0
                self.account_dict["positions_cost"] = 0
                self.account_dict["positions_profit"] = 0
                self.account_dict["avg_price"] = 0
                self.shift_logs.append({"ts": ts, "type": "liquidation", "price": new_price})
                return
        # ---------------------

        # 循环处理价格变动：模拟价格一步步走到新价格，防止跳过中间的网格线
        while True:
            # 如果价格已经超出了网格的大区间 (破网了)
            # 只要破了边界，我们就需要重置整个网格系统
            if (new_price > self.grid_dict["max_price"] + eps) or (new_price < self.grid_dict["min_price"] - eps):
                self.curr_price = new_price
                # 强制重新初始化参数 (force=True)
                self._initialize_grid_params(force=True)
                return

            up_price = self.account_dict["up_price"]
            down_price = self.account_dict["down_price"]
            
            # 如果新价格和当前价格几乎一样，直接退出
            if abs(new_price - self.curr_price) < eps:
                return

            # 如果新价格在当前格子内 (既没破上界，也没破下界)
            if new_price > self.curr_price and new_price < up_price - eps:
                self.curr_price = new_price
                return

            if new_price < self.curr_price and new_price > down_price + eps:
                self.curr_price = new_price
                return

            # 如果价格涨破了相邻的上界
            if new_price > self.curr_price:
                # 价格移动到上界
                self.curr_price = up_price 
                # 触发卖出 (SELL) 操作
                self.update_order(ts, up_price, 'SELL')
            else:
                # 如果价格跌破了相邻的下界
                # 价格移动到下界
                self.curr_price = down_price
                # 触发买入 (BUY) 操作
                self.update_order(ts, down_price, 'BUY')

    '''------------------------------ 状态持久化 ------------------------------'''

    # 导出当前策略状态，用于保存进度
    def export_state(self) -> Dict[str, Any]:
        """
        导出当前策略状态，用于断点续传或系统重启后恢复
        """
        def _json_safe(x):
            from datetime import datetime as _dt
            if isinstance(x, _dt):
                return x.isoformat()
            if isinstance(x, dict):
                return {k: _json_safe(v) for k, v in x.items()}
            if isinstance(x, list):
                return [_json_safe(v) for v in x]
            return x
        state = {
            "grid_dict": self.grid_dict,
            "account_dict": self.account_dict,
            "shift_logs": self.shift_logs,
            "upward_shift_count": self.upward_shift_count,
            "downward_shift_count": self.downward_shift_count,
            "enable_upward_shift": self.enable_upward_shift,
            "enable_downward_shift": self.enable_downward_shift,
            "max_loss": self.max_loss,
            "max_profit": self.max_profit,
            "is_liquidated": self.is_liquidated
        }
        return _json_safe(state)

    # 导入策略状态，恢复进度
    def import_state(self, state_dict: Dict[str, Any]):
        """
        导入策略状态
        """
        try:
            self.grid_dict = state_dict.get("grid_dict", self.grid_dict)
            self.account_dict = state_dict.get("account_dict", self.account_dict)
            self.shift_logs = state_dict.get("shift_logs", [])
            self.upward_shift_count = state_dict.get("upward_shift_count", 0)
            self.downward_shift_count = state_dict.get("downward_shift_count", 0)
            
            # 恢复开关状态 (如果是 None 则保持默认)
            if "enable_upward_shift" in state_dict:
                self.enable_upward_shift = state_dict["enable_upward_shift"]
            if "enable_downward_shift" in state_dict:
                self.enable_downward_shift = state_dict["enable_downward_shift"]
                
            self.max_loss = state_dict.get("max_loss", 0)
            self.max_profit = state_dict.get("max_profit", 0)
            self.is_liquidated = state_dict.get("is_liquidated", False)
            
            print(">>> 策略状态已成功恢复")
            return True
        except Exception as e:
            print(f"!!! 策略状态恢复失败: {e}")
            return False
