"""
test_papi_cancel.py - 测试统一账户（PAPI）撤单参数格式（会尝试撤真实挂单）

这个文件是干嘛的？
    统一账户模式下，撤单接口对参数格式比较敏感。
    这个脚本会：
    - 拉取当前挂单
    - 取一个订单 ID
    - 直接调用 `papiDeleteUmOrder` 看参数是否能被接受

术语解释：
    - PAPI（Portfolio Margin API）：币安统一账户/组合保证金接口
    - 撤单：取消挂出去但还没成交的订单

怎么用？
    1) 确保你是统一账户模式：export BINANCE_ACCOUNT_TYPE=\"unified\"
    2) 运行：
        python3 -X utf8 Quant_Unified/策略仓库/二号网格策略/test_papi_cancel.py

安全提醒：
    这个脚本可能会撤掉一笔真实挂单，别在你不想撤单的时候运行。
"""

import os
import sys

# 注入路径
当前路径 = os.path.dirname(os.path.abspath(__file__))
项目根目录 = os.path.dirname(os.path.dirname(当前路径))
if 项目根目录 not in sys.path:
    sys.path.insert(0, 项目根目录)

from 策略仓库.二号网格策略.api import binance as api

def 测试撤单参数():
    print("="*50)
    print("🧪 测试 PAPI 撤单参数格式")
    print("="*50)
    
    if api.ACCOUNT_TYPE != 'unified':
        print("跳过：非统一账户模式")
        return

    # 尝试列出当前所有挂单，拿一个 ID 来测试
    try:
        all_orders = api.fetch_open_orders("SOLUSDC")
        if not all_orders:
            print("当前 SOLUSDC 没有挂单，无法测试真实撤单。")
            # 伪造一个 ID 测试调用能否通过（预期报 -2011，但我们要看是代码报错还是 BN 报错）
            test_id = 999999999
        else:
            test_id = all_orders[0]['id']
            print(f"发现挂单 ID: {test_id}, 类型: {type(test_id)}")

        # 核心：尝试用位置参数调用 (就像 papiPostUmOrder 做的那样)
        try:
            print(f"\n尝试 1: 位置参数调用 {test_id}...")
            # 模拟 binance.py 的逻辑但改为位置参数
            raw_symbol = "SOLUSDC"
            params = {'symbol': raw_symbol, 'orderId': test_id}
            # 直接调用 papi_exchange 看看
            if api.papi_exchange and hasattr(api.papi_exchange, 'papiDeleteUmOrder'):
                res = api.papi_exchange.papiDeleteUmOrder(params)
                print(f"结果: {res}")
            else:
                print("错误：papi_exchange 没有 papiDeleteUmOrder 方法")
        except Exception as e:
            print(f"尝试 1 失败报错: {e}")

    except Exception as e:
        print(f"整体测试失败: {e}")

if __name__ == "__main__":
    测试撤单参数()
