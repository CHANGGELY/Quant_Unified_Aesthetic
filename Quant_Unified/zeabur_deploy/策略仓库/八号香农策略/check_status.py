"""
check_status.py - 检查当前账户的持仓和挂单状态
"""
import sys
from pathlib import Path

# 添加项目路径
策略目录 = Path(__file__).parent
项目根目录 = 策略目录.parent.parent
sys.path.append(str(项目根目录))

from 策略仓库.八号香农策略.api import binance_raw as api

def main():
    symbol = "ETHUSDT"
    print(f"正在查询 {symbol} 状态 (基于 binance_raw)...")
    
    # 1. 查价格
    price = api.fetch_symbol_price(symbol)
    print(f"当前市价: {price}")
    
    # 2. 查持仓
    position = api.fetch_position(symbol)
    amt = position['amount']
    print(f"当前持仓: {amt} ETH (未实现盈亏: {position['unRealizedProfit']} U)")
    
    # 3. 查挂单
    orders = api.fetch_open_orders(symbol)
    print(f"当前挂单数: {len(orders)}")
    for o in orders:
        print(f"  - [{o['side']}] 价格: {o['price']} | 数量: {o['amount']} | 已成交: {o['filled']}")
        差距 = (price - o['price']) / price * 100
        print(f"    距离市价: {差距:.4f}% ({'下方' if 差距 > 0 else '上方'})")

if __name__ == "__main__":
    main()
