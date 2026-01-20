"""
test_api.py - 币安接口连通性自检（安全：只查余额，不下单）

这个文件是干嘛的？
    这是给新手用的“开机自检”：
    - 检查你是否正确配置了 BINANCE_API_KEY / BINANCE_SECRET_KEY
    - 分别尝试连接：
        1) 现货账户（Spot：现货交易）
        2) 合约账户（Futures：合约/期货交易）
        3) 统一账户（PAPI：Portfolio Margin API，组合保证金/统一账户接口）

怎么用？
    1) 先配置环境变量（见 `api/binance.py` 的说明）
    2) 运行：
        python3 -X utf8 Quant_Unified/策略仓库/二号网格策略/test_api.py

你会看到什么？
    - 哪个接口能通、哪个接口报错
    - 如果能通，会打印出余额的一部分作为证明
"""

import os
import sys
import logging
import ccxt

try:
    from common_core.utils.env_kit import 加载_env文件
except Exception:  # pragma: no cover
    加载_env文件 = None

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_api():
    # 1. 加载环境变量
    已加载_env路径列表 = 加载_env文件(__file__) if 加载_env文件 else []
    if 已加载_env路径列表:
        logger.info("✅ 已加载环境变量文件: %s", " , ".join(str(p) for p in 已加载_env路径列表))
    else:
        logger.warning("⚠️ 未找到任何 .env 文件：将只能读取系统环境变量（export 的那种）")
    
    api_key = os.getenv("BINANCE_API_KEY")
    secret_key = os.getenv("BINANCE_SECRET_KEY")
    proxy = os.getenv("BINANCE_PROXY")
    account_type = os.getenv("BINANCE_ACCOUNT_TYPE", "normal").lower()
    
    if not api_key or not secret_key:
        logger.error("❌ .env 文件中未找到 BINANCE_API_KEY 或 BINANCE_SECRET_KEY")
        return

    # 隐藏部分 key 打印
    masked_key = api_key[:4] + "*" * 10 + api_key[-4:]
    logger.info(f"🔑 检测到 API Key: {masked_key}")
    logger.info(f"⚙️ 当前配置的账户模式: {account_type} (如果是统一账户，请确保设置为 unified)")

    # --- 测试 1: 现货 (Spot) API ---
    logger.info("------------- 测试 1: 现货 (Spot) API -------------")
    try:
        spot_config = {
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
            }
        }
        if proxy:
            spot_config['proxies'] = {'http': proxy, 'https': proxy}
            
        exchange_spot = ccxt.binance(spot_config)
        
        logger.info("📡 正在连接现货 API...")
        balance_spot = exchange_spot.fetch_balance()
        # 随便找个资产打印一下，证明通了
        usdt_spot = balance_spot['USDT']['free'] if 'USDT' in balance_spot else 0
        logger.info(f"✅ 现货 API 连接成功！现货账户 USDT 余额: {usdt_spot:.2f}")
        
    except Exception as e:
        logger.error(f"❌ 现货 API 连接失败: {e}")

    # --- 测试 2: 合约 (Futures) API ---
    logger.info("\n------------- 测试 2: 合约 (Futures) API -------------")
    try:
        exchange_config = {
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
            }
        }
        
        if proxy:
            exchange_config['proxies'] = {
                'http': proxy,
                'https': proxy
            }
            
        exchange = ccxt.binanceusdm(exchange_config)
        
        logger.info("📡 正在尝试连接币安合约 API (fapi)...")
        balance = exchange.fetch_balance()
        usdt_balance = balance['USDT']['free']
        logger.info(f"✅ 合约 API 连接成功！USDT 余额: {usdt_balance:.2f}")
        
    except Exception as e:
        logger.error(f"❌ 合约 API (fapi) 连接失败: {e}")
        
    # --- 测试 3: 统一账户 (Portfolio Margin) API ---
    logger.info("\n------------- 测试 3: 统一账户 (PAPI) -------------")
    try:
        # PAPI 通常在 ccxt.binance 中可用，不需要 binanceusdm
        papi_config = {
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
        }
        if proxy:
            papi_config['proxies'] = {'http': proxy, 'https': proxy}
            
        exchange_papi = ccxt.binance(papi_config)
        
        logger.info("📡 正在尝试连接统一账户 API (papi)...")
        
        # 尝试多种 PAPI 获取余额的方法
        # 方法 1: papiPrivateGetBalance (部分版本)
        # 方法 2: papiPrivateGetAccount (账户信息)
        # 方法 3: papiGetBalance (部分版本)
        
        papi_balance_data = None
        method_used = ""
        
        if hasattr(exchange_papi, 'papiPrivateGetBalance'):
            papi_balance_data = exchange_papi.papiPrivateGetBalance()
            method_used = "papiPrivateGetBalance"
        elif hasattr(exchange_papi, 'papiGetBalance'):
            papi_balance_data = exchange_papi.papiGetBalance()
            method_used = "papiGetBalance"
        elif hasattr(exchange_papi, 'papiPrivateGetAccount'):
            papi_balance_data = exchange_papi.papiPrivateGetAccount()
            method_used = "papiPrivateGetAccount"
        elif hasattr(exchange_papi, 'papiGetAccount'):
            papi_balance_data = exchange_papi.papiGetAccount()
            method_used = "papiGetAccount"
            
        if papi_balance_data:
            logger.info(f"✅ 统一账户 (PAPI) 连接成功！使用方法: {method_used}")
            # 尝试打印关键余额信息
            if 'totalMarginBalance' in papi_balance_data:
                 logger.info(f"💰 统一账户总保证金余额 (totalMarginBalance): {papi_balance_data['totalMarginBalance']}")
            elif 'totalWalletBalance' in papi_balance_data:
                 logger.info(f"💰 统一账户总钱包余额 (totalWalletBalance): {papi_balance_data['totalWalletBalance']}")
            else:
                 logger.info(f"📊 PAPI 返回数据示例: {str(papi_balance_data)[:150]}...")
        else:
            logger.warning("⚠️ 当前 ccxt 版本似乎没有标准的 PAPI 余额查询方法。")
            logger.info("正在尝试打印所有 PAPI 相关方法供调试...")
            methods = [m for m in dir(exchange_papi) if m.startswith('papi')]
            logger.info(f"可用 PAPI 方法 (前10个): {methods[:10]}")
            
    except Exception as e:
        logger.error(f"❌ 统一账户 (PAPI) 连接失败: {e}")

if __name__ == "__main__":
    test_api()
