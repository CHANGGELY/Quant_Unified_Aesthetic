# -*- coding: utf-8 -*-
"""
Quant Unified 量化交易系统
[回测进度条模块]

功能：
    提供统一的进度条显示，让用户知道回测进行到哪了、还要等多久。
    底层使用 tqdm 库，但封装成中文接口方便使用。

使用方法：
    ```python
    from 基础库.common_core.backtest.进度条 import 回测进度条

    # 方式1: 作为上下文管理器
    with 回测进度条(总数=len(prices), 描述="回测中") as 进度:
        for i in range(len(prices)):
            # 你的回测逻辑...
            进度.更新(1)

    # 方式2: 手动控制
    进度 = 回测进度条(总数=1000, 描述="处理数据")
    for i in range(1000):
        # 处理逻辑...
        进度.更新(1)
    进度.关闭()
    ```

显示效果：
    回测中: 45%|████████████░░░░░░░░░░░░| 450000/1000000 [01:23<01:42, 5432.10 it/s]
"""

from tqdm import tqdm
from typing import Optional


class 回测进度条:
    """
    回测进度条封装类
    
    这个类就像一个"加载条"：
    当你在下载文件或安装软件时，会看到一个进度条告诉你：
    - 完成了多少 (45%)
    - 已经用了多久 (01:23)
    - 还需要多久 (01:42)
    - 速度多快 (5432 条/秒)
    
    这里我们把它用在回测上，让你知道回测还要跑多久。
    """
    
    def __init__(
        self,
        总数: int,
        描述: str = "回测进行中",
        单位: str = " bar",
        刷新间隔: float = 0.1,
        最小更新间隔: float = 0.5,
        禁用: bool = False,
        留存: bool = True
    ):
        """
        初始化进度条
        
        参数：
            总数: 总共需要处理的数量 (比如 K线条数)
            描述: 进度条前面显示的文字描述
            单位: 显示的单位 (如 "条", "bar", "根K线")
            刷新间隔: 进度条刷新频率 (秒)
            最小更新间隔: 最小更新间隔 (秒)，防止刷新太频繁拖慢速度
            禁用: 是否禁用进度条 (静默模式)
            留存: 完成后是否保留进度条显示
        """
        self.总数 = 总数
        self.禁用 = 禁用
        
        # 配置 tqdm 进度条
        self._进度条 = tqdm(
            total=总数,
            desc=描述,
            unit=单位,
            mininterval=刷新间隔,
            miniters=max(1, 总数 // 1000),  # 至少每 0.1% 更新一次
            disable=禁用,
            leave=留存,
            ncols=100,  # 进度条宽度
            bar_format='{desc}: {percentage:3.0f}%|{bar:25}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]'
        )
        
        self._当前 = 0
    
    def 更新(self, 步数: int = 1):
        """
        更新进度
        
        参数：
            步数: 本次完成的数量 (默认为1)
        """
        self._进度条.update(步数)
        self._当前 += 步数
    
    def 设置描述(self, 描述: str):
        """动态更新进度条描述文字"""
        self._进度条.set_description(描述)
    
    def 设置后缀(self, **kwargs):
        """
        设置进度条后缀信息
        
        示例：
            进度.设置后缀(收益率="12.5%", 回撤="-3.2%")
        """
        self._进度条.set_postfix(**kwargs)
    
    def 关闭(self):
        """关闭进度条"""
        self._进度条.close()
    
    def __enter__(self):
        """进入上下文管理器"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文管理器，自动关闭进度条"""
        self.关闭()
        return False  # 不吞掉异常
    
    @property
    def 已完成数量(self) -> int:
        """获取已完成的数量"""
        return self._当前
    
    @property
    def 完成百分比(self) -> float:
        """获取完成百分比 (0-100)"""
        if self.总数 == 0:
            return 100.0
        return (self._当前 / self.总数) * 100


def 创建进度条(总数: int, 描述: str = "处理中", 禁用: bool = False) -> 回测进度条:
    """
    快速创建进度条的便捷函数
    
    使用方法：
        进度 = 创建进度条(1000000, "回测ETH策略")
        for i in range(1000000):
            # 处理逻辑
            进度.更新(1)
        进度.关闭()
    """
    return 回测进度条(总数=总数, 描述=描述, 禁用=禁用)


# ============== 向量化回测专用 ==============

class 分块进度条:
    """
    分块进度条 - 适用于向量化回测
    
    向量化回测不是一条一条处理，而是一大块一大块处理。
    这个进度条专门为这种情况设计。
    
    使用方法：
        进度 = 分块进度条(总步骤=5, 描述="向量化回测")
        
        进度.完成步骤("加载数据")
        # ... 加载数据 ...
        
        进度.完成步骤("计算指标")
        # ... 计算指标 ...
        
        进度.完成步骤("生成信号")
        # ... 生成信号 ...
        
        进度.结束()
    """
    
    def __init__(self, 总步骤: int = 5, 描述: str = "回测中"):
        self.总步骤 = 总步骤
        self.当前步骤 = 0
        self.描述 = 描述
        
        self._进度条 = tqdm(
            total=总步骤,
            desc=描述,
            unit="步",
            bar_format='{desc}: {n}/{total} |{bar:20}| {postfix}',
            leave=True
        )
    
    def 完成步骤(self, 步骤名称: str):
        """标记一个步骤完成"""
        self.当前步骤 += 1
        self._进度条.set_postfix_str(f"✅ {步骤名称}")
        self._进度条.update(1)
    
    def 结束(self):
        """结束进度条"""
        self._进度条.set_postfix_str("🎉 完成!")
        self._进度条.close()


# ============== 测试代码 ==============

if __name__ == "__main__":
    import time
    
    print("测试1: 基础进度条")
    with 回测进度条(总数=100, 描述="处理K线") as 进度:
        for i in range(100):
            time.sleep(0.02)  # 模拟处理
            进度.更新(1)
            if i % 20 == 0:
                进度.设置后缀(收益="12.5%")
    
    print("\n测试2: 分块进度条 (向量化)")
    进度 = 分块进度条(总步骤=4, 描述="向量化回测")
    
    time.sleep(0.3)
    进度.完成步骤("加载数据")
    
    time.sleep(0.3)
    进度.完成步骤("计算指标")
    
    time.sleep(0.3)
    进度.完成步骤("生成信号")
    
    time.sleep(0.3)
    进度.完成步骤("计算收益")
    
    进度.结束()
    
    print("\n✅ 进度条模块测试通过!")
