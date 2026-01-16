import os
import sys
import time

# 注入路径
当前路径 = os.path.dirname(os.path.abspath(__file__))
项目根目录 = os.path.dirname(os.path.dirname(当前路径))
if 项目根目录 not in sys.path:
    sys.path.insert(0, 项目根目录)

from 策略仓库.二号网格策略.api import binance as api

def 抢救操作():
    print("="*50)
    print("🚀 开始紧急抢救行动：止损减仓")
    print("="*50)
    
    # 1. 获取当前 SOL 持仓
    try:
        sol_pos = api.fetch_position("SOLUSDC")
        current_amt = sol_pos['amount']
        
        if current_amt <= 0:
            print("ℹ️ 当前没有 SOL 多头持仓，无需减仓。")
            return

        # 2. 计算减仓数量 (75%)
        # 目标是留下 25%，平掉 75%
        reduce_amt = current_amt * 0.75
        # 向上取整到合适精度 (SOL 通常是 2 位小数)
        reduce_amt = round(reduce_amt, 2)
        
        print(f"📦 当前 SOL 持仓: {current_amt:.4f}")
        print(f"🔥 计划减仓数量: {reduce_amt:.4f} (约 75%)")
        
        # 3. 执行卖出平仓
        # 使用 place_limit_order，但价格稍微设低一点确保立即成交 (类似市价单)
        current_price = api.fetch_symbol_price("SOLUSDC")
        # 卖出价格设低 0.5%，确保必成
        sell_price = current_price * 0.995 
        
        print(f"💸 当前市价约: {current_price:.2f} | 卖出参考价: {sell_price:.2f}")
        
        # 提示：统一账户下单通常需要指定 positionSide
        # 网格策略里做多是用 LONG 仓位
        try:
            res = api.place_limit_order(
                symbol="SOLUSDC",
                side="SELL",
                price=sell_price,
                quantity=reduce_amt,
                position_side="LONG",
                post_only=False # 必须吃单以确保立即释放保证金
            )
            print(f"✅ 减仓订单已发送！订单 ID: {res.get('id') or res.get('orderId')}")
        except Exception as e:
            print(f"❌ 减仓失败: {e}")
            
        # 4. 再次诊断
        time.sleep(2) # 等待订单成交
        print("\n" + "="*50)
        print("📊 抢救后状态复查")
        print("="*50)
        
        equity = api.fetch_account_equity()
        available = api.fetch_account_balance('USDT')
        new_sol_pos = api.fetch_position("SOLUSDC")
        new_sol_val = abs(new_sol_pos['amount'] * current_price)
        
        print(f"💰 账户净值: {equity:.2f} U")
        print(f"🚥 可用保证金: {available:.2f} U")
        print(f"📦 剩余 SOL 持仓: {new_sol_pos['amount']:.4f} (价值: {new_sol_val:.2f} U)")
        
        if equity > 0:
            print(f"🌀 当前实际杠杆: {new_sol_val/equity:.2f} x")
            
    except Exception as e:
        print(f"运行抢救脚本出错: {e}")

if __name__ == "__main__":
    抢救操作()
