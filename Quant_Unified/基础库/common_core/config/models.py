"""
配置模型定义
用于定义和验证系统各部分的配置结构，利用 Pydantic 提供类型检查和自动验证功能。
"""
from typing import Optional, List, Dict, Union, Set
from pydantic import BaseModel, Field, AnyHttpUrl


class ExchangeConfig(BaseModel):
    """交易所基础配置"""
    exchange_name: str = Field(default="binance", description="交易所名称")
    apiKey: str = Field(default="", description="API 密钥")
    secret: str = Field(default="", description="API 私钥")
    is_pure_long: bool = Field(default=False, description="是否为纯多头模式")
    password: Optional[str] = None
    uid: Optional[str] = None


class FactorConfig(BaseModel):
    """因子配置"""
    name: str
    param: Union[int, float, str, dict, list]


class StrategyConfig(BaseModel):
    """策略配置"""
    strategy_name: str
    symbol_type: str = Field(default="swap", description="交易对类型：spot(现货) 或 swap(合约)")
    hold_period: str = Field(default="1h", description="持仓周期")
    # 在此添加其他通用策略字段
    # 这是一个基础模型，具体策略可以继承扩展此模型


class AccountConfig(BaseModel):
    """账户配置"""
    name: str = Field(default="default_account", description="账户名称")
    apiKey: Optional[str] = None
    secret: Optional[str] = None
    strategy: Dict = Field(default_factory=dict, description="策略配置字典")
    strategy_short: Optional[Dict] = Field(default=None, description="做空策略配置字典")
    
    # 风控设置
    black_list: List[str] = Field(default_factory=list, description="黑名单币种")
    white_list: List[str] = Field(default_factory=list, description="白名单币种")
    leverage: int = Field(default=1, description="杠杆倍数")
    
    # 数据获取设置
    get_kline_num: int = Field(default=999, description="获取K线数量")
    min_kline_num: int = Field(default=168, description="最小K线数量要求")
    
    # 通知设置
    wechat_webhook_url: Optional[str] = Field(default=None, description="企业微信 Webhook URL")
    
    # 下单限制
    order_spot_money_limit: float = Field(default=10.0, description="现货最小下单金额")
    order_swap_money_limit: float = Field(default=5.0, description="合约最小下单金额")
    
    # 高级设置
    use_offset: bool = Field(default=False, description="是否使用 Offset")
    is_pure_long: bool = Field(default=False, description="是否为纯多头模式")
