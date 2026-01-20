"""
quantity_precision.py - 常见交易对的下单数量精度表

这个文件是干嘛的？
    交易所对“下单数量”通常有小数位限制，比如：
    - SOL 可能允许 2 位小数
    - ETH 可能允许 3 位小数

    如果你下单时小数位超了，交易所会拒单。
    所以这里维护一个最简单的映射表，让策略能把数量四舍五入到正确的小数位。

怎么用？
    在配置里填 `qty_precision`，或者在代码里调用：
        get_quantity_precision(\"SOLUSDC\")
"""
PRECISION_MAP = {
    "SOLUSDC": 2,
    "ETHUSDC": 3,
    "BTCUSDC": 3,
}


def get_quantity_precision(symbol: str) -> int | None:
    key = (symbol or "").upper()
    return PRECISION_MAP.get(key)
