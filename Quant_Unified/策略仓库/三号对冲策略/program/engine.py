"""
这份文件实现【3号对冲策略】的核心引擎：
1. 维护“内部持仓账本”（多头账本与空头账本）
2. 每触发一个网格点，双向同时开仓，并设置等距止盈
3. 当价格继续沿一个方向运行时，优先用“止盈事件”去减少该方向“最劣价”的持仓，使剩余持仓均价更优（平劣减仓）
4. 支持“顺势复利”：将止盈利润从 USDC 转为 ETH，累加到该方向的开仓规模变量
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple


@dataclass
class 账本条目:
    开仓价: float
    数量: float  # 单位：ETH


class HedgeStrategy:
    def __init__(self, conf):
        self.conf = conf
        self.symbol = conf.symbol
        self.网格间距 = float(conf.grid_percent)
        self.网格层数 = int(conf.grid_levels)
        self.多头规模 = float(conf.initial_long_size)
        self.空头规模 = float(conf.initial_short_size)
        self.费率 = getattr(conf, 'fee_rate', 0.0002)  # 默认万2手续费
        self.基础价 = None  # base_price

        # 内部持仓账本：列表按“价格优劣”排序规则维护
        self.多头账本: List[账本条目] = []  # 多头最劣价：开仓价最高
        self.空头账本: List[账本条目] = []  # 空头最劣价：开仓价最低

        # 统计
        self.累计利润_USDC = 0.0
        self.累计成交次数 = 0

    def 初始化(self, 当前价: float):
        self.基础价 = float(当前价)

    def 当前网格价列表(self) -> List[float]:
        g = self.网格间距
        p0 = self.基础价
        价位 = []
        for i in range(1, self.网格层数 + 1):
            价位.append(p0 * (1 + g * i))  # 上方价格
            价位.append(p0 * (1 - g * i))  # 下方价格
        # 返回按绝对偏离排序的列表（越近的先处理）
        return sorted(价位, key=lambda x: abs(x - p0))

    def _减少最劣持仓(self, is_long: bool, 减少数量: float, 平仓价: float) -> Tuple[float, float]:
        """按“最劣价”优先减少该方向持仓，返回 (实际减少数量, 已实现盈亏_USDC)。"""
        remained = 减少数量
        realized_pnl = 0.0
        
        if is_long:
            # 多头最劣：价格最高
            self.多头账本.sort(key=lambda e: e.开仓价, reverse=True)
            for 条目 in self.多头账本:
                if remained <= 0:
                    break
                可减 = min(条目.数量, remained)
                条目.数量 -= 可减
                remained -= 可减
                
                # 累加盈亏：(平仓价 - 开仓价) * 数量
                realized_pnl += (平仓价 - 条目.开仓价) * 可减
                
            # 清理空条目
            self.多头账本 = [e for e in self.多头账本 if e.数量 > 1e-12]
        else:
            # 空头最劣：价格最低
            self.空头账本.sort(key=lambda e: e.开仓价)
            for 条目 in self.空头账本:
                if remained <= 0:
                    break
                可减 = min(条目.数量, remained)
                条目.数量 -= 可减
                remained -= 可减
                
                # 累加盈亏：(开仓价 - 平仓价) * 数量
                realized_pnl += (条目.开仓价 - 平仓价) * 可减
                
            self.空头账本 = [e for e in self.空头账本 if e.数量 > 1e-12]
            
        return (减少数量 - remained), realized_pnl

    def _复利累加(self, is_long: bool, 利润_USDC: float, 结算价: float):
        """将 USDC 利润按结算价换算为 ETH，累加到该方向规模变量。"""
        利润_ETH = float(利润_USDC) / float(结算价) if 结算价 > 0 else 0.0
        if is_long:
            self.多头规模 += 利润_ETH
            # 上限控制
            limit = getattr(self.conf, 'max_individual_position_size', None)
            if limit:
                self.多头规模 = min(self.多头规模, float(limit))
        else:
            self.空头规模 += 利润_ETH
            limit = getattr(self.conf, 'max_individual_position_size', None)
            if limit:
                self.空头规模 = min(self.空头规模, float(limit))

    def _开仓双向(self, 触发价: float):
        # 同价位同时开多与开空
        self.多头账本.append(账本条目(开仓价=触发价, 数量=self.多头规模))
        self.空头账本.append(账本条目(开仓价=触发价, 数量=self.空头规模))
        
        # 扣除开仓手续费
        开仓总额 = 触发价 * (self.多头规模 + self.空头规模)
        self.累计利润_USDC -= 开仓总额 * self.费率
        
        self.累计成交次数 += 2

    def _计算止盈(self, 开仓价: float, is_long: bool) -> float:
        g = self.网格间距
        if is_long:
            return 开仓价 * (1 + g)
        else:
            return 开仓价 * (1 - g)

    def _一步上行事件(self, 新价: float):
        """价格跨过一个上行网格：先在该网格开双向，再让“上一格的多头”止盈并平劣。"""
        触发价 = 新价
        # 1) 同步开仓
        self._开仓双向(触发价)
        # 2) 多头上一格止盈（开仓价在前一基础价的上一格）
        上一格开仓价 = self.基础价 * (1 + self.网格间距)
        多止盈价 = self._计算止盈(上一格开仓价, is_long=True)
        # 止盈利润（按一步间距）：qty * (止盈价 - 开仓价) ≈ qty * (开仓价 * g)
        止盈数量 = self.多头规模
        实际减少, 利润_USDC = self._减少最劣持仓(is_long=True, 减少数量=止盈数量, 平仓价=多止盈价)
        
        # 计算毛利与手续费
        # 利润_USDC 已经在 _减少最劣持仓 中计算准确
        交易金额 = 多止盈价 * 实际减少
        手续费 = 交易金额 * self.费率
        
        self.累计利润_USDC += (利润_USDC - 手续费)
        self._复利累加(is_long=True, 利润_USDC=(利润_USDC - 手续费), 结算价=多止盈价)
        # 3) 基础价移到当前触发价
        self.基础价 = 触发价

    def _一步下行事件(self, 新价: float):
        """价格跨过一个下行网格：先在该网格开双向，再让“上一格的空头”止盈并平劣。"""
        触发价 = 新价
        self._开仓双向(触发价)
        上一格开仓价 = self.基础价 * (1 - self.网格间距)
        空止盈价 = self._计算止盈(上一格开仓价, is_long=False)
        止盈数量 = self.空头规模
        实际减少, 利润_USDC = self._减少最劣持仓(is_long=False, 减少数量=止盈数量, 平仓价=空止盈价)
        
        # 计算毛利与手续费
        # 利润_USDC 已经在 _减少最劣持仓 中计算准确
        交易金额 = 空止盈价 * 实际减少
        手续费 = 交易金额 * self.费率
        
        self.累计利润_USDC += (利润_USDC - 手续费)
        self._复利累加(is_long=False, 利润_USDC=(利润_USDC - 手续费), 结算价=空止盈价)
        self.基础价 = 触发价

    def 处理价格(self, 最新价: float):
        """基于最新价，计算跨越了多少格，逐格触发事件。"""
        if self.基础价 is None:
            self.初始化(最新价)
            return
        p0 = self.基础价
        g = self.网格间距
        if 最新价 >= p0:
            # 上行跨越的格数
            比例 = 最新价 / p0 - 1
            步数 = int(比例 // g)
            for k in range(1, 步数 + 1):
                触发价 = p0 * (1 + g * k)
                self._一步上行事件(触发价)
        else:
            比例 = 1 - 最新价 / p0
            步数 = int(比例 // g)
            for k in range(1, 步数 + 1):
                触发价 = p0 * (1 - g * k)
                self._一步下行事件(触发价)

    def 汇总持仓(self) -> Tuple[float, float]:
        多 = sum(e.数量 for e in self.多头账本)
        空 = sum(e.数量 for e in self.空头账本)
        return 多, 空

    def 计算浮动盈亏(self, 当前价: float) -> float:
        浮盈_多 = sum(e.数量 * (当前价 - e.开仓价) for e in self.多头账本)
        浮盈_空 = sum(e.数量 * (e.开仓价 - 当前价) for e in self.空头账本)
        return 浮盈_多 + 浮盈_空
