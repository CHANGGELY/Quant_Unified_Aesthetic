import os
import sys

# 注入路径
当前路径 = os.path.dirname(os.path.abspath(__file__))
项目根目录 = os.path.dirname(os.path.dirname(当前路径))
if 项目根目录 not in sys.path:
    sys.path.insert(0, 项目根目录)

from 策略仓库.二号网格策略.api import binance as api

def 验证修复效果():
    print("="*50)
    print("🧪 验证 binance.py 修复效果")
    print("="*50)
    
    try:
        # 1. 获取一个真实的挂单 (CCXT 格式，id 是字符串)
        all_orders = api.fetch_open_orders("SOLUSDC")
        if not all_orders:
             print("当前 SOLUSDC 没有挂单，无法验证。")
             return
             
        test_id = all_orders[0]['id']
        test_symbol = all_orders[0]['symbol']
        print(f"待测订单: {test_symbol}, ID: {test_id}, 类型: {type(test_id)}")

        # 2. 调用已修复的 api.cancel_order
        # 预期：内部会将其转为 int 并调用 papiDeleteUmOrder 成功
        try:
            print("\n执行 api.cancel_order...")
            res = api.cancel_order(test_symbol, test_id)
            print(f"✅ 成功! 接口返回状态: {res.get('status')}")
        except Exception as e:
            print(f"❌ 依然失败: {e}")

    except Exception as e:
        print(f"验证过程出错: {e}")

if __name__ == "__main__":
    验证修复效果()
