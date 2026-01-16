import os
import sys

# 注入路径
当前路径 = os.path.dirname(os.path.abspath(__file__))
项目根目录 = os.path.dirname(os.path.dirname(当前路径))
if 项目根目录 not in sys.path:
    sys.path.insert(0, 项目根目录)

from 策略仓库.二号网格策略.api import binance as api

def 紧急诊断():
    print("="*50)
    print("🔍 紧急风险诊断报告")
    print("="*50)
    
    # 1. 获取账户净值
    try:
        equity = api.fetch_account_equity()
        # 获取可用余额 (USDT)
        available = api.fetch_account_balance('USDT')
        
        print(f"💰 账户总净值 (Equity): {equity:.2f} U")
        print(f"🚥 可用保证金 (Available): {available:.2f} U")
    except Exception as e:
        print(f"获取账户资金信息失败: {e}")
    
    # 2. 获取持仓
    try:
        sol_pos = api.fetch_position("SOLUSDC")
        eth_pos = api.fetch_position("ETHUSDC")
        
        # 使用当前价格计算名义价值
        sol_price = api.fetch_symbol_price("SOLUSDC")
        eth_price = api.fetch_symbol_price("ETHUSDC")
        
        sol_val = abs(sol_pos['amount'] * sol_price)
        eth_val = abs(eth_pos['amount'] * eth_price)
        
        print("-" * 50)
        print(f"📦 SOL 持仓: {sol_pos['amount']:.4f} (当前价值: {sol_val:.2f} U) | 方向: {'多' if sol_pos['amount']>0 else ('空' if sol_pos['amount']<0 else '无')}")
        print(f"📦 ETH 持仓: {eth_pos['amount']:.4f} (当前价值: {eth_val:.2f} U) | 方向: {'多' if eth_pos['amount']>0 else ('空' if eth_pos['amount']<0 else '无')}")
        
        # 3. 计算 Delta
        delta = (sol_pos['amount'] * sol_price) + (eth_pos['amount'] * eth_price)
        print("-" * 50)
        print(f"⚖️ 净 Delta 暴露: {delta:+.2f} U")
        
        if equity > 0:
            print(f"🌀 实际杠杆 (Actual Leverage): {abs(delta)/equity:.2f} x")
        
        if available < 5:
            print("\n🚨 警告：可用保证金已耗尽！系统无法执行止盈外的任何下单操作。")
        
        if equity > 0 and abs(delta) > equity * 8:
            print("\n🔥 极高风险提醒：当前已处于“裸奔”多头状态，且杠杆极高！")
            print("🚀 建议行动：立即在币安 App 或通过脚本手动平掉 50% 以上的 SOL 持仓以释放保证金。")
            
    except Exception as e:
        print(f"获取持仓风险信息失败: {e}")

if __name__ == "__main__":
    紧急诊断()
