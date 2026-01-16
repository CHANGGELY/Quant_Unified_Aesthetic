"""
verify_key_raw.py - 使用原生 requests 验证币安 API 密钥

完全不依赖 CCXT，按照币安官方文档拼接请求。
https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
"""

import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

# 加载环境变量
load_dotenv('策略仓库/八号香农策略/.env')

API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

print(f"API Key: {API_KEY[:10]}...")
print(f"Secret: {SECRET_KEY[:10]}...")


def 生成签名(参数字典: dict, 密钥: str) -> str:
    """
    按照币安要求，对请求参数进行 HMAC SHA256 签名。
    """
    查询字符串 = urlencode(参数字典)
    签名 = hmac.new(
        密钥.encode('utf-8'),
        查询字符串.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return 签名


def 测试接口(名称: str, 基础URL: str, 是期货: bool = False):
    """
    测试一个具体的 API 端点是否能识别我们的 Key。
    """
    print(f"\n  测试 {名称} ({基础URL})...")
    
    # 构造请求参数
    时间戳 = int(time.time() * 1000)
    参数 = {
        'timestamp': 时间戳,
        'recvWindow': 5000
    }
    
    # 生成签名
    签名 = 生成签名(参数, SECRET_KEY)
    参数['signature'] = 签名
    
    # 构造 URL
    if 是期货:
        # 期货账户信息端点
        端点 = f"{基础URL}/fapi/v2/account"
    else:
        # 现货账户信息端点
        端点 = f"{基础URL}/api/v3/account"
    
    # 发送请求
    headers = {
        'X-MBX-APIKEY': API_KEY
    }
    
    try:
        响应 = requests.get(端点, params=参数, headers=headers, timeout=10)
        数据 = 响应.json()
        
        if 响应.status_code == 200:
            print(f"    ✅ 成功! 连接正常，Key 有效")
            # 打印一些账户信息
            if 是期货:
                print(f"       总钱包余额: {数据.get('totalWalletBalance', 'N/A')} USDT")
            else:
                # 现货打印前几个有余额的币种
                余额列表 = [b for b in 数据.get('balances', []) if float(b.get('free', 0)) > 0]
                for 余额 in 余额列表[:3]:
                    print(f"       {余额['asset']}: {余额['free']}")
            return True
        else:
            错误码 = 数据.get('code', 'N/A')
            错误信息 = 数据.get('msg', 'N/A')
            print(f"    ❌ 失败: [{错误码}] {错误信息}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"    ❌ 网络错误: {e}")
        return False


def 主函数():
    print("\n" + "=" * 60)
    print("币安 API 密钥连接测试 (原生 requests)")
    print("=" * 60)
    
    # 测试环境列表
    环境列表 = [
        # (名称, URL, 是否期货)
        ("现货 Demo Trading", "https://demo-api.binance.com", False),
        ("现货测试网 (Vision)", "https://testnet.binance.vision", False),
        ("现货实盘", "https://api.binance.com", False),
        
        ("期货 Demo Trading", "https://demo-fapi.binance.com", True),
        ("期货测试网 (Legacy)", "https://testnet.binancefuture.com", True),
        ("期货实盘", "https://fapi.binance.com", True),
    ]
    
    成功环境 = None
    
    for 名称, URL, 是期货 in 环境列表:
        if 测试接口(名称, URL, 是期货):
            成功环境 = (名称, URL, 是期货)
            break  # 找到一个成功的就停止
    
    print("\n" + "=" * 60)
    if 成功环境:
        print(f"🎉 密钥有效! 匹配环境: {成功环境[0]}")
        print(f"   URL: {成功环境[1]}")
        print(f"   类型: {'期货' if 成功环境[2] else '现货'}")
    else:
        print("❌ 密钥在所有已知环境中均无效。")
        print("请检查密钥是否正确复制，或尝试重新生成。")
    print("=" * 60)


if __name__ == "__main__":
    if not API_KEY or not SECRET_KEY:
        print("错误: 缺少 API_KEY 或 SECRET_KEY")
    else:
        主函数()
