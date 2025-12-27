# -*- coding: utf-8 -*-
"""
Quant Unified 量化交易系统
[统一回测指标模块]

功能：
    为所有策略提供统一的回测绩效指标计算，避免重复开发。
    一次计算，处处复用 —— 所有策略（1-8号）都调用这个模块。

支持的指标：
    - 年化收益率 (CAGR)
    - 对数收益率 (Log Return)
    - 最大回撤 (Max Drawdown)
    - 最大回撤恢复时间 (Recovery Time)
    - 卡玛比率 (Calmar Ratio)
    - 夏普比率 (Sharpe Ratio)
    - 索提诺比率 (Sortino Ratio)
    - 胜率 (Win Rate)
    - 盈亏比 (Profit Factor)
    - 交易次数 (Trade Count)

使用方法：
    ```python
    from 基础库.common_core.backtest.metrics import 回测指标计算器

    # 方式1: 传入权益曲线数组
    计算器 = 回测指标计算器(权益曲线=equity_values, 初始资金=10000)
    计算器.打印报告()
    指标字典 = 计算器.获取指标()

    # 方式2: 传入 DataFrame (需包含 equity 列)
    计算器 = 回测指标计算器.从DataFrame创建(df, 权益列名='equity')
    计算器.打印报告()
    ```
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Union, List
from datetime import timedelta


@dataclass
class 回测指标结果:
    """回测指标结果数据类"""
    # 基础信息
    初始资金: float = 0.0
    最终资金: float = 0.0
    总收益: float = 0.0
    总收益率: float = 0.0
    
    # 收益指标
    年化收益率: float = 0.0           # CAGR
    对数收益率: float = 0.0           # Log Return
    
    # 风险指标
    最大回撤: float = 0.0             # Max Drawdown (负数)
    最大回撤百分比: str = ""          # 格式化显示
    最大回撤开始时间: Optional[str] = None
    最大回撤结束时间: Optional[str] = None
    最大回撤恢复时间: Optional[str] = None  # 恢复到前高的时间
    最大回撤恢复天数: int = 0
    
    # 风险调整收益
    卡玛比率: float = 0.0             # Calmar Ratio = 年化收益 / |最大回撤|
    夏普比率: float = 0.0             # Sharpe Ratio
    索提诺比率: float = 0.0           # Sortino Ratio
    年化波动率: float = 0.0           # Annualized Volatility
    
    # 交易统计
    总周期数: int = 0
    盈利周期数: int = 0
    亏损周期数: int = 0
    胜率: float = 0.0
    盈亏比: float = 0.0              # Profit Factor
    最大连续盈利周期: int = 0
    最大连续亏损周期: int = 0
    
    # 其他
    交易次数: int = 0
    回测天数: int = 0
    
    def 转为字典(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "初始资金": self.初始资金,
            "最终资金": self.最终资金,
            "总收益": self.总收益,
            "总收益率": f"{self.总收益率:.2%}",
            "年化收益率": f"{self.年化收益率:.2%}",
            "对数收益率": f"{self.对数收益率:.4f}",
            "最大回撤": f"{self.最大回撤:.2%}",
            "最大回撤恢复天数": self.最大回撤恢复天数,
            "卡玛比率": f"{self.卡玛比率:.2f}",
            "夏普比率": f"{self.夏普比率:.2f}",
            "索提诺比率": f"{self.索提诺比率:.2f}",
            "年化波动率": f"{self.年化波动率:.2%}",
            "胜率": f"{self.胜率:.2%}",
            "盈亏比": f"{self.盈亏比:.2f}",
            "交易次数": self.交易次数,
            "回测天数": self.回测天数,
        }


class 回测指标计算器:
    """
    统一回测指标计算器
    
    这个类就像一个"成绩单生成器"：
    你把考试成绩(权益曲线)交给它，它会自动帮你算出：
    - 平均分是多少 (年化收益)
    - 最差的一次考了多少 (最大回撤)
    - 成绩稳不稳定 (夏普比率)
    等等一系列指标。
    """
    
    def __init__(
        self,
        权益曲线: Union[np.ndarray, List[float], pd.Series],
        初始资金: float = 10000.0,
        时间戳: Optional[Union[np.ndarray, List, pd.DatetimeIndex]] = None,
        持仓序列: Optional[Union[np.ndarray, List[float], pd.Series]] = None,
        无风险利率: float = 0.0,  # 年化无风险利率，加密货币通常设为 0
        周期每年数量: int = 525600,  # 分钟级数据: 365.25 * 24 * 60
    ):
        """
        初始化回测指标计算器
        
        参数:
            权益曲线: 账户总资产序列 (如 [10000, 10100, 10050, ...])
            初始资金: 初始本金
            时间戳: 可选，每个数据点对应的时间戳
            持仓序列: 可选，持仓状态序列 (如 [0, 1, 1, -1, 0, ...])，用于计算交易次数
            无风险利率: 年化无风险收益率，默认 0 (加密货币市场)
            周期每年数量: 每年有多少个周期，用于年化
                - 分钟级: 525600 (365.25 * 24 * 60)
                - 小时级: 8766 (365.25 * 24)
                - 日级: 365
        """
        # 转换为 numpy 数组
        self.权益 = np.array(权益曲线, dtype=np.float64)
        self.初始资金 = float(初始资金)
        self.无风险利率 = 无风险利率
        self.周期每年数量 = 周期每年数量
        
        # 时间戳处理
        if 时间戳 is not None:
            self.时间戳 = pd.to_datetime(时间戳)
        else:
            self.时间戳 = None
            
        # 持仓序列
        if 持仓序列 is not None:
            self.持仓 = np.array(持仓序列, dtype=np.float64)
        else:
            self.持仓 = None
            
        # 预计算
        self._计算收益率序列()
        
    def _计算收益率序列(self):
        """计算周期收益率序列"""
        # 简单收益率: (P_t - P_{t-1}) / P_{t-1}
        self.收益率 = np.diff(self.权益) / self.权益[:-1]
        # 处理 NaN 和 Inf
        self.收益率 = np.nan_to_num(self.收益率, nan=0.0, posinf=0.0, neginf=0.0)
        
        # 对数收益率: ln(P_t / P_{t-1})
        with np.errstate(divide='ignore', invalid='ignore'):
            self.对数收益率序列 = np.log(self.权益[1:] / self.权益[:-1])
            self.对数收益率序列 = np.nan_to_num(self.对数收益率序列, nan=0.0, posinf=0.0, neginf=0.0)
    
    @classmethod
    def 从DataFrame创建(
        cls,
        df: pd.DataFrame,
        权益列名: str = 'equity',
        时间列名: str = 'candle_begin_time',
        持仓列名: Optional[str] = None,
        初始资金: Optional[float] = None,
        **kwargs
    ) -> '回测指标计算器':
        """
        从 DataFrame 创建计算器
        
        参数:
            df: 包含回测数据的 DataFrame
            权益列名: 权益/净值列的名称
            时间列名: 时间戳列的名称
            持仓列名: 可选，持仓列的名称
            初始资金: 可选，如不提供则使用权益曲线第一个值
        """
        权益 = df[权益列名].values
        
        时间戳 = None
        if 时间列名 in df.columns:
            时间戳 = df[时间列名].values
        elif isinstance(df.index, pd.DatetimeIndex):
            时间戳 = df.index
            
        持仓 = None
        if 持仓列名 and 持仓列名 in df.columns:
            持仓 = df[持仓列名].values
            
        if 初始资金 is None:
            初始资金 = 权益[0]
            
        return cls(
            权益曲线=权益,
            初始资金=初始资金,
            时间戳=时间戳,
            持仓序列=持仓,
            **kwargs
        )
    
    def 计算全部指标(self) -> 回测指标结果:
        """计算所有回测指标，返回结构化结果"""
        结果 = 回测指标结果()
        
        # 1. 基础信息
        结果.初始资金 = self.初始资金
        结果.最终资金 = self.权益[-1]
        结果.总收益 = 结果.最终资金 - 结果.初始资金
        结果.总收益率 = 结果.总收益 / 结果.初始资金
        结果.总周期数 = len(self.权益)
        
        # 2. 回测天数
        if self.时间戳 is not None and len(self.时间戳) > 1:
            结果.回测天数 = (self.时间戳[-1] - self.时间戳[0]).days
        else:
            结果.回测天数 = len(self.权益) // (24 * 60)  # 假设分钟级数据
        
        # 3. 年化收益率 (CAGR)
        # CAGR = (最终净值 / 初始净值) ^ (1 / 年数) - 1
        年数 = max(结果.回测天数 / 365.25, 0.001)  # 防止除零
        净值终点 = 结果.最终资金 / 结果.初始资金
        if 净值终点 > 0:
            结果.年化收益率 = (净值终点 ** (1 / 年数)) - 1
        else:
            结果.年化收益率 = -1.0
        
        # 4. 对数收益率 (总体)
        # Log Return = ln(最终净值 / 初始净值)
        if 净值终点 > 0:
            结果.对数收益率 = np.log(净值终点)
        else:
            结果.对数收益率 = float('-inf')
        
        # 5. 最大回撤
        回撤结果 = self._计算最大回撤()
        结果.最大回撤 = 回撤结果['最大回撤']
        结果.最大回撤百分比 = f"{回撤结果['最大回撤']:.2%}"
        结果.最大回撤开始时间 = 回撤结果.get('开始时间')
        结果.最大回撤结束时间 = 回撤结果.get('结束时间')
        结果.最大回撤恢复时间 = 回撤结果.get('恢复时间')
        结果.最大回撤恢复天数 = 回撤结果.get('恢复天数', 0)
        
        # 6. 卡玛比率 (Calmar Ratio)
        # Calmar = 年化收益率 / |最大回撤|
        if abs(结果.最大回撤) > 1e-9:
            结果.卡玛比率 = 结果.年化收益率 / abs(结果.最大回撤)
        else:
            结果.卡玛比率 = float('inf') if 结果.年化收益率 > 0 else 0.0
        
        # 7. 波动率和夏普比率
        if len(self.收益率) > 1:
            # 年化波动率 = 周期标准差 * sqrt(周期每年数量)
            结果.年化波动率 = np.std(self.收益率) * np.sqrt(self.周期每年数量)
            
            # 夏普比率 = (年化收益 - 无风险利率) / 年化波动率
            if 结果.年化波动率 > 1e-9:
                结果.夏普比率 = (结果.年化收益率 - self.无风险利率) / 结果.年化波动率
            else:
                结果.夏普比率 = 0.0
                
            # 索提诺比率 = (年化收益 - 无风险利率) / 下行波动率
            下行收益 = self.收益率[self.收益率 < 0]
            if len(下行收益) > 0:
                下行波动率 = np.std(下行收益) * np.sqrt(self.周期每年数量)
                if 下行波动率 > 1e-9:
                    结果.索提诺比率 = (结果.年化收益率 - self.无风险利率) / 下行波动率
        
        # 8. 胜率和盈亏比
        盈利周期 = self.收益率[self.收益率 > 0]
        亏损周期 = self.收益率[self.收益率 < 0]
        
        结果.盈利周期数 = len(盈利周期)
        结果.亏损周期数 = len(亏损周期)
        
        if len(self.收益率) > 0:
            结果.胜率 = 结果.盈利周期数 / len(self.收益率)
        
        if len(亏损周期) > 0 and np.sum(np.abs(亏损周期)) > 1e-9:
            结果.盈亏比 = np.sum(盈利周期) / np.abs(np.sum(亏损周期))
        
        # 9. 连续盈亏
        结果.最大连续盈利周期 = self._计算最大连续(self.收益率 > 0)
        结果.最大连续亏损周期 = self._计算最大连续(self.收益率 < 0)
        
        # 10. 交易次数 (如果有持仓序列)
        if self.持仓 is not None:
            # 持仓变化就是交易
            结果.交易次数 = int(np.sum(np.abs(np.diff(self.持仓)) > 0))
        
        return 结果
    
    def _计算最大回撤(self) -> Dict[str, Any]:
        """
        计算最大回撤及相关信息
        
        最大回撤 = (峰值 - 谷值) / 峰值
        就像股票从最高点跌到最低点的幅度
        """
        if len(self.权益) < 2:
            return {'最大回撤': 0.0}
        
        # 计算滚动最高点 (累计最大值)
        累计最高 = np.maximum.accumulate(self.权益)
        
        # 计算回撤 (当前值相对于历史最高的跌幅)
        # 回撤 = (当前值 - 最高值) / 最高值  (负数或零)
        回撤序列 = (self.权益 - 累计最高) / 累计最高
        
        # 最大回撤位置 (最低点)
        最大回撤索引 = np.argmin(回撤序列)
        最大回撤值 = 回撤序列[最大回撤索引]
        
        # 最大回撤开始位置 (在最低点之前的最高点)
        峰值索引 = np.argmax(self.权益[:最大回撤索引 + 1])
        
        结果 = {
            '最大回撤': 最大回撤值,
            '回撤开始索引': 峰值索引,
            '回撤结束索引': 最大回撤索引,
        }
        
        # 如果有时间戳，添加时间信息
        if self.时间戳 is not None:
            结果['开始时间'] = str(self.时间戳[峰值索引])
            结果['结束时间'] = str(self.时间戳[最大回撤索引])
            
            # 计算恢复时间 (从最低点恢复到前高)
            峰值 = self.权益[峰值索引]
            恢复索引 = None
            for i in range(最大回撤索引 + 1, len(self.权益)):
                if self.权益[i] >= 峰值:
                    恢复索引 = i
                    break
            
            if 恢复索引 is not None:
                结果['恢复时间'] = str(self.时间戳[恢复索引])
                结果['恢复天数'] = (self.时间戳[恢复索引] - self.时间戳[最大回撤索引]).days
            else:
                结果['恢复天数'] = -1  # 未恢复
                结果['恢复时间'] = "未恢复"
        
        return 结果
    
    def _计算最大连续(self, 条件数组: np.ndarray) -> int:
        """计算最大连续满足条件的周期数"""
        if len(条件数组) == 0:
            return 0
        
        最大连续 = 0
        当前连续 = 0
        
        for 满足条件 in 条件数组:
            if 满足条件:
                当前连续 += 1
                最大连续 = max(最大连续, 当前连续)
            else:
                当前连续 = 0
        
        return 最大连续
    
    def 获取指标(self) -> Dict[str, Any]:
        """获取指标字典"""
        return self.计算全部指标().转为字典()
    
    def 打印报告(self, 策略名称: str = "策略"):
        """
        打印格式化的回测报告
        
        输出一个漂亮的表格，展示所有关键指标
        """
        结果 = self.计算全部指标()
        
        # 构建分隔线
        宽度 = 50
        分隔线 = "═" * 宽度
        细分隔线 = "─" * 宽度
        
        print()
        print(f"╔{分隔线}╗")
        print(f"║{'📊 ' + 策略名称 + ' 回测报告':^{宽度-2}}║")
        print(f"╠{分隔线}╣")
        
        # 基础信息
        print(f"║ {'💰 初始资金':<15}: {结果.初始资金:>18,.2f} USDT  ║")
        print(f"║ {'💎 最终资金':<15}: {结果.最终资金:>18,.2f} USDT  ║")
        print(f"║ {'📈 总收益率':<15}: {结果.总收益率:>18.2%}       ║")
        print(f"╠{细分隔线}╣")
        
        # 收益指标
        print(f"║ {'📅 年化收益率':<14}: {结果.年化收益率:>18.2%}       ║")
        print(f"║ {'📐 对数收益率':<14}: {结果.对数收益率:>18.4f}       ║")
        print(f"╠{细分隔线}╣")
        
        # 风险指标
        print(f"║ {'🌊 最大回撤':<15}: {结果.最大回撤:>18.2%}       ║")
        if 结果.最大回撤恢复天数 > 0:
            print(f"║ {'⏱️ 回撤恢复天数':<13}: {结果.最大回撤恢复天数:>18} 天    ║")
        elif 结果.最大回撤恢复天数 == -1:
            print(f"║ {'⏱️ 回撤恢复天数':<13}: {'未恢复':>21}    ║")
        print(f"╠{细分隔线}╣")
        
        # 风险调整收益
        print(f"║ {'⚖️ 卡玛比率':<14}: {结果.卡玛比率:>18.2f}       ║")
        print(f"║ {'📊 夏普比率':<15}: {结果.夏普比率:>18.2f}       ║")
        print(f"║ {'📉 索提诺比率':<14}: {结果.索提诺比率:>18.2f}       ║")
        print(f"║ {'📈 年化波动率':<14}: {结果.年化波动率:>18.2%}       ║")
        print(f"╠{细分隔线}╣")
        
        # 交易统计
        print(f"║ {'🎯 胜率':<16}: {结果.胜率:>18.2%}       ║")
        print(f"║ {'💹 盈亏比':<15}: {结果.盈亏比:>18.2f}       ║")
        if 结果.交易次数 > 0:
            print(f"║ {'🔄 交易次数':<15}: {结果.交易次数:>18}       ║")
        print(f"║ {'📆 回测天数':<15}: {结果.回测天数:>18} 天    ║")
        
        print(f"╚{分隔线}╝")
        print()
        
        return 结果


# ============== 便捷函数 ==============

def 快速计算指标(
    权益曲线: Union[np.ndarray, List[float]],
    初始资金: float = 10000.0,
    打印: bool = True,
    策略名称: str = "策略"
) -> Dict[str, Any]:
    """
    快速计算回测指标的便捷函数
    
    使用方法:
        from 基础库.common_core.backtest.metrics import 快速计算指标
        
        指标 = 快速计算指标(equity_list, 初始资金=10000)
    """
    计算器 = 回测指标计算器(权益曲线=权益曲线, 初始资金=初始资金)
    if 打印:
        计算器.打印报告(策略名称=策略名称)
    return 计算器.获取指标()


# ============== 测试代码 ==============

if __name__ == "__main__":
    # 生成模拟权益曲线 (用于测试)
    np.random.seed(42)
    天数 = 365
    每天周期数 = 1440  # 分钟级
    总周期 = 天数 * 每天周期数
    
    # 模拟一个有波动的权益曲线
    收益率 = np.random.normal(0.00001, 0.0005, 总周期)  # 微小正漂移 + 波动
    权益 = 10000 * np.cumprod(1 + 收益率)
    
    # 插入一个大回撤
    权益[int(总周期*0.3):int(总周期*0.4)] *= 0.7
    
    # 测试计算器
    计算器 = 回测指标计算器(权益曲线=权益, 初始资金=10000, 周期每年数量=每天周期数*365)
    计算器.打印报告(策略名称="测试策略")
