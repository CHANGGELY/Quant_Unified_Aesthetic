"""
test_papi_cancel_deep.py - 深度测试统一账户（PAPI）撤单（会尝试撤真实挂单）

这个文件是干嘛的？
    和 `test_papi_cancel.py` 类似，但更“啰嗦”一点：
    - 直接从 PAPI 取原始挂单列表
    - 用不同的订单 ID 类型（int / str）分别尝试撤单
    - 还会尝试 ccxt 的统一 `cancel_order` 方法

怎么用？
    1) 确保你是统一账户模式：export BINANCE_ACCOUNT_TYPE=\"unified\"
    2) 运行：
        python3 -X utf8 Quant_Unified/策略仓库/二号网格策略/test_papi_cancel_deep.py

安全提醒：
    这个脚本会撤掉真实挂单，请谨慎运行。
"""

import os
import sys

# 注入路径
当前路径 = os.path.dirname(os.path.abspath(__file__))
项目根目录 = os.path.dirname(os.path.dirname(当前路径))
if 项目根目录 not in sys.path:
    sys.path.insert(0, 项目根目录)

from 策略仓库.二号网格策略.api import binance as api

def 测试更深层撤单():
    print("="*50)
    print("🧪 深度测试 PAPI 撤单")
    print("="*50)
    
    try:
        # 1. 获取所有挂单
        all_raw = api.papi_exchange.papiGetUmOpenOrders()
        if not all_raw:
            print("当前没有任何挂单")
            return
            
        target = all_raw[0]
        oid = target['orderId']
        symbol = target['symbol']
        print(f"目标订单: Symbol={symbol}, OrderId={oid}, 类型={type(oid)}")

        # 尝试 1: 用原始类型 (通常是 int/long) 调用
        try:
            print(f"\n尝试 1: 原始类型调用...")
            params = {'symbol': symbol, 'orderId': oid}
            res = api.papi_exchange.papiDeleteUmOrder(params)
            print(f"✅ 成功: {res}")
            return
        except Exception as e:
            print(f"❌ 失败: {e}")

        # 尝试 2: 强制 String 类型调用
        try:
            print(f"\n尝试 2: 强制 String 调用...")
            params = {'symbol': symbol, 'orderId': str(oid)}
            res = api.papi_exchange.papiDeleteUmOrder(params)
            print(f"✅ 成功: {res}")
            return
        except Exception as e:
            print(f"❌ 失败: {e}")

        # 尝试 3: 使用 CCXT 统一方法 cancelOrder
        try:
            print(f"\n尝试 3: 使用 CCXT 统一方法 cancelOrder...")
            # 注意: CCXT 的 cancelOrder 可能会内部映射到不同的 API
            res = api.papi_exchange.cancel_order(str(oid), symbol)
            print(f"✅ 成功: {res}")
        except Exception as e:
            print(f"❌ 失败: {e}")

    except Exception as e:
        print(f"测试出错: {e}")

if __name__ == "__main__":
    测试更深层撤单()
