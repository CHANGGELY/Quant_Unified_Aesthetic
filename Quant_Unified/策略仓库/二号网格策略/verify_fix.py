"""
verify_fix.py - 验证修复脚本：测试撤单函数是否正常（实盘，会撤掉真实挂单）

这个文件是干嘛的？
    之前如果遇到“撤单报错 / 订单 ID 类型不对”等问题，
    可以用这个脚本做一次最小验证：
    - 先拉取当前挂单
    - 拿第一笔挂单的 ID
    - 调用 `api.cancel_order(...)` 试着撤掉它

怎么用？
    需要你已配置好币安 API Key/Secret（见 `api/binance.py` 的说明），然后运行：
        python3 -X utf8 Quant_Unified/策略仓库/二号网格策略/verify_fix.py

安全提醒：
    本脚本会撤掉一笔真实挂单，别在你不想撤单的时候运行。
"""

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
