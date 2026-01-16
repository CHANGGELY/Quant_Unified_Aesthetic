"""这个文件用于维护常见交易对的数量小数位精度，保证策略内部仓位和交易所实际仓位的小数位一致"""
PRECISION_MAP = {
    "SOLUSDC": 2,
    "ETHUSDC": 3,
    "BTCUSDC": 3,
}


def get_quantity_precision(symbol: str) -> int | None:
    key = (symbol or "").upper()
    return PRECISION_MAP.get(key)
