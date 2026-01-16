"""
Quant Unified 量化交易系统
回测引擎.py (Localized Simulator)

功能：
    提供基于 Numba JIT 加速的回测核心逻辑。
    支持长短仓双向交易、资金费率结算、滑点与手续费计算。
"""
import numba as nb
import numpy as np
from numba.experimental import jitclass

spec = [
    ('账户权益', nb.float64),
    ('手续费率', nb.float64),
    ('滑点率', nb.float64),
    ('最小下单金额', nb.float64),
    ('每手数量', nb.float64[:]),
    ('当前持仓', nb.int64[:]),
    ('目标持仓', nb.int64[:]),
    ('最新价格', nb.float64[:]),
    ('是否有最新价', nb.boolean),
]

@jitclass(spec)
class 回测引擎:
    def __init__(self, 初始资金, 每手数量, 手续费率, 滑点率, 初始持仓, 最小下单金额):
        """
        初始化回测引擎
        :param 初始资金: 初始账户权益 (USDT)
        :param 每手数量: 每个币种的最小交易单位 (Contract Size)
        :param 手续费率: 单边手续费率 (e.g. 0.0005)
        :param 滑点率: 单边滑点率 (按成交额计算)
        :param 初始持仓: 初始持仓手数
        :param 最小下单金额: 低于此金额的订单将被忽略
        """
        self.账户权益 = 初始资金
        self.手续费率 = 手续费率
        self.滑点率 = 滑点率
        self.最小下单金额 = 最小下单金额

        n = len(每手数量)

        # 合约面值 (每手数量)
        self.每手数量 = np.zeros(n, dtype=np.float64)
        self.每手数量[:] = 每手数量

        # 前收盘价
        self.最新价格 = np.zeros(n, dtype=np.float64)
        self.是否有最新价 = False

        # 当前持仓手数
        self.当前持仓 = np.zeros(n, dtype=np.int64)
        self.当前持仓[:] = 初始持仓

        # 目标持仓手数
        self.目标持仓 = np.zeros(n, dtype=np.int64)
        self.目标持仓[:] = 初始持仓

    def 设置目标持仓(self, 目标持仓):
        """设置下一周期的目标持仓手数"""
        self.目标持仓[:] = 目标持仓

    def 填充最新价(self, 价格列表):
        """内部辅助函数：更新最新价格，自动过滤 NaN 值"""
        mask = np.logical_not(np.isnan(价格列表))
        self.最新价格[mask] = 价格列表[mask]
        self.是否有最新价 = True

    def 结算权益(self, 当前价格):
        """
        根据最新价格结算当前账户权益 (Mark-to-Market)
        公式: 净值变动 = (当前价格 - 上次价格) * 每手数量 * 持仓手数
        """
        mask = np.logical_and(self.当前持仓 != 0, np.logical_not(np.isnan(当前价格)))
        
        # 计算持仓盈亏
        equity_delta = np.sum((当前价格[mask] - self.最新价格[mask]) * self.每手数量[mask] * self.当前持仓[mask])

        # 更新账户权益
        self.账户权益 += equity_delta

    def 处理开盘(self, 开盘价, 资金费率, 标记价格):
        """
        模拟: K 线开盘 -> K 线收盘时刻 (处理资金费率)
        :param 开盘价: 当前 K 线开盘价
        :param 资金费率: 当前周期的资金费率
        :param 标记价格: 用于计算资金费的标记价格
        :return: (更新后的权益, 资金费支出, 当前持仓名义价值)
        """
        if not self.是否有最新价:
            self.填充最新价(开盘价)

        # 1. 根据开盘价和前最新价，结算持仓盈亏
        self.结算权益(开盘价)

        # 2. 结算资金费 (Funding Fee)
        # 资金费 = 名义价值 * 资金费率
        mask = np.logical_and(self.当前持仓 != 0, np.logical_not(np.isnan(标记价格)))
        notional_value = self.每手数量[mask] * self.当前持仓[mask] * 标记价格[mask]
        funding_fee = np.sum(notional_value * 资金费率[mask])
        
        self.账户权益 -= funding_fee

        # 3. 更新最新价为开盘价
        self.填充最新价(开盘价)

        return self.账户权益, funding_fee, notional_value

    def 处理调仓(self, 执行价格):
        """
        模拟: K 线开盘时刻 -> 调仓时刻 (执行交易)
        :param 执行价格: 实际成交价格 (通常为 VWAP 或特定算法价格)
        :return: (调仓后权益, 总成交额, 总交易成本)
        """
        if not self.是否有最新价:
            self.填充最新价(执行价格)

        # 1. 根据调仓价和前最新价（开盘价），结算持仓盈亏
        self.结算权益(执行价格)

        # 2. 计算需要交易的数量
        delta = self.目标持仓 - self.当前持仓
        mask = np.logical_and(delta != 0, np.logical_not(np.isnan(执行价格)))

        # 3. 计算预计成交额
        turnover = np.zeros(len(self.每手数量), dtype=np.float64)
        turnover[mask] = np.abs(delta[mask]) * self.每手数量[mask] * 执行价格[mask]

        # 4. 过滤掉低于最小下单金额的订单
        mask = np.logical_and(mask, turnover >= self.最小下单金额)

        # 5. 计算本期实际总成交额
        turnover_total = turnover[mask].sum()

        if np.isnan(turnover_total):
            raise RuntimeError('Turnover is nan')

        # 6. 扣除 交易手续费 + 滑点成本
        cost = turnover_total * (self.手续费率 + self.滑点率)
        self.账户权益 -= cost

        # 7. 更新持仓 (仅更新成功成交的部分)
        self.当前持仓[mask] = self.目标持仓[mask]

        # 8. 更新最新价为成交价
        self.填充最新价(执行价格)

        return self.账户权益, turnover_total, cost

    def 处理收盘(self, 收盘价):
        """
        模拟: K 线收盘 -> K 线收盘时刻 (结算周期末权益)
        :param 收盘价: 当前 K 线收盘价
        :return: (收盘后权益, 当前持仓名义价值)
        """
        if not self.是否有最新价:
            self.填充最新价(收盘价)

        # 1. 根据收盘价和前最新价（调仓价），结算持仓盈亏
        self.结算权益(收盘价)

        # 2. 更新最新价为收盘价
        self.填充最新价(收盘价)

        # 3. 计算当前持仓市值
        mask = np.logical_and(self.当前持仓 != 0, np.logical_not(np.isnan(收盘价)))
        pos_val = self.每手数量[mask] * self.当前持仓[mask] * 收盘价[mask]

        return self.账户权益, pos_val
