"""
binance_raw.py - 原生 requests 实现的币安期货 API

完全不依赖 CCXT，直接按照币安官方文档拼接请求。
支持 Demo Trading 和生产环境。

文档参考:
- https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
"""

import os
import time
import hmac
import hashlib
import requests
import logging
import threading
from urllib.parse import urlencode
from dotenv import load_dotenv
from pathlib import Path
from decimal import Decimal, ROUND_DOWN
import pandas as pd

# ============================================================
# 配置加载
# ============================================================

当前目录 = Path(__file__).parent
策略目录 = 当前目录.parent
环境文件路径 = 策略目录 / '.env'
load_dotenv(dotenv_path=环境文件路径)

logger = logging.getLogger(__name__)

# API 密钥
API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
USE_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() == "true"

# API 限速配置
API_MAX_QPS = float(os.getenv("BINANCE_API_MAX_QPS", "2"))
_API_LOCK = threading.Lock()
_LAST_API_TS = 0.0

# 基础 URL (根据环境切换)
if USE_TESTNET:
    # Demo Trading 期货端点
    BASE_URL = "https://demo-fapi.binance.com"
    WS_BASE_URL = "wss://fstream.binancefuture.com"
    logger.info("🧪 已启用币安 Demo Trading 期货模式")
    logger.info(f"   REST 端点: {BASE_URL}")
    logger.info(f"   WS 端点: {WS_BASE_URL}")
else:
    # 生产环境
    BASE_URL = "https://fapi.binance.com"
    WS_BASE_URL = "wss://fstream.binance.com"
    logger.info("🔴 警告: 使用生产环境，请确保资金安全！")

if not API_KEY or not SECRET_KEY:
    logger.warning("未检测到 BINANCE_API_KEY 或 BINANCE_SECRET_KEY，API 功能将不可用。")


# ============================================================
# 核心工具函数
# ============================================================

def 生成签名(参数: dict) -> str:
    """
    对请求参数进行 HMAC SHA256 签名
    """
    查询字符串 = urlencode(参数)
    签名 = hmac.new(
        SECRET_KEY.encode('utf-8'),
        查询字符串.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return 签名


def _限速等待():
    """
    API 限速控制
    """
    global _LAST_API_TS
    with _API_LOCK:
        当前时间 = time.time()
        间隔 = 1.0 / API_MAX_QPS
        距离上次 = 当前时间 - _LAST_API_TS
        if 距离上次 < 间隔:
            time.sleep(间隔 - 距离上次)
        _LAST_API_TS = time.time()


def _请求(方法: str, 端点: str, 参数: dict = None, 需要签名: bool = False, 重试次数: int = 3) -> dict:
    """
    统一的 HTTP 请求封装
    
    :param 方法: GET, POST, DELETE
    :param 端点: API 端点路径 (如 /fapi/v1/ticker/price)
    :param 参数: 请求参数
    :param 需要签名: 是否需要签名 (私有接口需要)
    :param 重试次数: 失败重试次数
    :return: JSON 响应
    """
    if 参数 is None:
        参数 = {}
    
    URL = BASE_URL + 端点
    请求头 = {'X-MBX-APIKEY': API_KEY}
    
    if 需要签名:
        参数['timestamp'] = int(time.time() * 1000)
        参数['recvWindow'] = 5000
        参数['signature'] = 生成签名(参数)
    
    for 尝试 in range(重试次数):
        try:
            _限速等待()
            
            if 方法 == 'GET':
                响应 = requests.get(URL, params=参数, headers=请求头, timeout=10)
            elif 方法 == 'POST':
                响应 = requests.post(URL, params=参数, headers=请求头, timeout=10)
            elif 方法 == 'DELETE':
                响应 = requests.delete(URL, params=参数, headers=请求头, timeout=10)
            else:
                raise ValueError(f"不支持的 HTTP 方法: {方法}")
            
            数据 = 响应.json()
            
            if 响应.status_code == 200:
                return 数据
            else:
                错误码 = 数据.get('code', 响应.status_code)
                错误信息 = 数据.get('msg', '未知错误')
                
                # 判断是否可重试
                if 错误码 in [-1001, -1003, -1015]:  # 网络/限速错误
                    logger.warning(f"API 请求失败 ({尝试+1}/{重试次数}): [{错误码}] {错误信息}")
                    time.sleep(1)
                    continue
                else:
                    raise Exception(f"[{错误码}] {错误信息}")
                    
        except requests.exceptions.RequestException as e:
            logger.warning(f"网络请求失败 ({尝试+1}/{重试次数}): {e}")
            if 尝试 < 重试次数 - 1:
                time.sleep(1)
            else:
                raise Exception(f"网络错误: {e}")
    
    raise Exception("请求失败，已达最大重试次数")


# ============================================================
# 行情接口 (公开)
# ============================================================

def fetch_symbol_price(symbol: str) -> float:
    """
    获取单个交易对的最新价格
    
    :param symbol: 交易对 (如 ETHUSDT)
    :return: 最新价格
    """
    数据 = _请求('GET', '/fapi/v1/ticker/price', {'symbol': symbol})
    return float(数据['price'])


def fetch_ticker_price() -> dict:
    """
    获取所有交易对的最新价格
    
    :return: {symbol: price} 字典
    """
    数据列表 = _请求('GET', '/fapi/v1/ticker/price')
    return {item['symbol']: float(item['price']) for item in 数据列表}


def fetch_candle_data(symbol: str, end_time, interval: str = '1m', limit: int = 1000) -> pd.DataFrame:
    """
    获取 K 线数据
    
    :param symbol: 交易对
    :param end_time: 截止时间 (datetime 对象)
    :param interval: K 线周期
    :param limit: 获取条数
    :return: DataFrame
    """
    参数 = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    if end_time:
        参数['endTime'] = int(end_time.timestamp() * 1000)
    
    数据 = _请求('GET', '/fapi/v1/klines', 参数)
    
    df = pd.DataFrame(数据, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_volume',
        'taker_buy_quote_volume', 'ignore'
    ])
    
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    
    return df


# ============================================================
# 账户接口 (私有)
# ============================================================

def fetch_account_equity(asset_name: str = 'USDT') -> float:
    """
    获取账户净值 (钱包余额 + 未实现盈亏)
    """
    数据 = _请求('GET', '/fapi/v2/account', 需要签名=True)
    
    for 资产 in 数据.get('assets', []):
        if 资产['asset'] == asset_name:
            钱包余额 = float(资产.get('walletBalance', 0))
            未实现盈亏 = float(资产.get('unrealizedProfit', 0))
            return 钱包余额 + 未实现盈亏
    
    logger.warning(f"未找到资产 {asset_name}")
    return 0.0


def fetch_account_status(asset_name: str = 'USDT', symbol: str = None) -> dict:
    """
    获取详细账户权益状态 (合并查询: 资金 + 持仓)
    
    :param asset_name: 资产名称 (如 USDT)
    :param symbol: 交易对 (如 ETHUSDT)，如果提供，会同时在 account 接口返回的 positions 中查找该币种持仓
    :return: dict or None
    """
    try:
        # 权重: 5 (v2/account)
        数据 = _请求('GET', '/fapi/v2/account', 需要签名=True)
        
        result = {}
        
        # 1. 搜索指定资产 (USDT)
        found_asset = False
        for 资产 in 数据.get('assets', []):
            if 资产['asset'] == asset_name:
                result.update({
                    'asset': asset_name,
                    'wallet_balance': float(资产.get('walletBalance', 0)),
                    'unrealized_pnl': float(资产.get('unrealizedProfit', 0)),
                    'margin_balance': float(资产.get('marginBalance', 0)),
                    'available_balance': float(资产.get('availableBalance', 0)),
                    'maint_margin': float(资产.get('maintMargin', 0)),
                    'update_time': int(数据.get('updateTime', 0))
                })
                found_asset = True
                break
        
        if not found_asset:
            available_assets = [a['asset'] for a in 数据.get('assets', []) if float(a.get('walletBalance', 0)) > 0]
            logger.warning(f"未找到资产 {asset_name}。账户内可用资产: {available_assets}")
            return None
            
        # 2. 如果指定了 symbol，顺便在 positions 里找持仓 (省去一次单独的 positionRisk 请求)
        if symbol:
            found_pos = False
            for pos in 数据.get('positions', []):
                if pos['symbol'] == symbol:
                    result.update({
                        'symbol': symbol,
                        'position_amt': float(pos.get('positionAmt', 0)),
                        'position_entry': float(pos.get('entryPrice', 0)),
                        'position_unPnl': float(pos.get('unrealizedProfit', 0))
                    })
                    found_pos = True
                    break
            if not found_pos:
                # 没找到仓位信息，默认 0
                result.update({'position_amt': 0.0, 'position_entry': 0.0, 'position_unPnl': 0.0})

        return result
        
    except Exception as e:
        logger.error(f"获取账户状态失败: {e}")
        return None


def fetch_account_balance(asset_name: str = 'USDT') -> float:
    """
    获取账户余额 (不含未实现盈亏)
    """
    数据 = _请求('GET', '/fapi/v2/balance', 需要签名=True)
    
    for 资产 in 数据:
        if 资产['asset'] == asset_name:
            return float(资产.get('balance', 0))
    
    logger.warning(f"未找到资产 {asset_name}")
    return 0.0


def fetch_position(symbol: str) -> dict:
    """
    获取单个交易对的持仓信息
    
    :return: {'amount': float, 'entryPrice': float, 'unRealizedProfit': float}
    """
    数据 = _请求('GET', '/fapi/v2/positionRisk', {'symbol': symbol}, 需要签名=True)
    
    for 持仓 in 数据:
        if 持仓['symbol'] == symbol:
            return {
                'amount': float(持仓.get('positionAmt', 0)),
                'entryPrice': float(持仓.get('entryPrice', 0)),
                'unRealizedProfit': float(持仓.get('unRealizedProfit', 0))
            }
    
    return {'amount': 0.0, 'entryPrice': 0.0, 'unRealizedProfit': 0.0}


# ============================================================
# 订单接口 (私有)
# ============================================================

# 缓存交易规则
_symbol_info_cache = {}


def _获取交易规则(symbol: str) -> dict:
    """
    获取交易对的精度和限制规则
    """
    if symbol in _symbol_info_cache:
        return _symbol_info_cache[symbol]
    
    数据 = _请求('GET', '/fapi/v1/exchangeInfo')
    
    for 规则 in 数据.get('symbols', []):
        if 规则['symbol'] == symbol:
            价格精度 = 规则.get('pricePrecision', 2)
            数量精度 = 规则.get('quantityPrecision', 3)
            
            # 解析过滤器
            最小数量 = 0.001
            最小名义价值 = 5.0
            
            for 过滤器 in 规则.get('filters', []):
                if 过滤器['filterType'] == 'LOT_SIZE':
                    最小数量 = float(过滤器.get('minQty', 0.001))
                elif 过滤器['filterType'] == 'MIN_NOTIONAL':
                    最小名义价值 = float(过滤器.get('notional', 5))
            
            结果 = {
                'pricePrecision': 价格精度,
                'quantityPrecision': 数量精度,
                'minQty': 最小数量,
                'minNotional': 最小名义价值
            }
            _symbol_info_cache[symbol] = 结果
            return 结果
    
    logger.warning(f"未找到交易对 {symbol} 的规则")
    return {'pricePrecision': 2, 'quantityPrecision': 3, 'minQty': 0.001, 'minNotional': 5}


def _调整精度(symbol: str, price: float, quantity: float) -> tuple:
    """
    根据交易规则调整价格和数量精度
    """
    规则 = _获取交易规则(symbol)
    
    调整后价格 = round(price, 规则['pricePrecision'])
    调整后数量 = float(Decimal(str(quantity)).quantize(
        Decimal(10) ** -规则['quantityPrecision'],
        rounding=ROUND_DOWN
    ))
    
    return 调整后价格, 调整后数量


def place_limit_order(symbol: str, side: str, price: float, quantity: float, 
                      client_order_id: str = None, position_side: str = None,
                      post_only: bool = False) -> dict:
    """
    下限价单
    
    :param symbol: 交易对
    :param side: BUY 或 SELL
    :param price: 价格
    :param quantity: 数量
    :param client_order_id: 自定义订单 ID
    :param position_side: 持仓方向 (单向持仓模式不需要)
    :param post_only: 是否只做 Maker
    :return: 订单信息
    """
    调整后价格, 调整后数量 = _调整精度(symbol, price, quantity)
    
    参数 = {
        'symbol': symbol,
        'side': side.upper(),
        'type': 'LIMIT',
        'price': 调整后价格,
        'quantity': 调整后数量,
        'timeInForce': 'GTX' if post_only else 'GTC'
    }
    
    if client_order_id:
        参数['newClientOrderId'] = client_order_id
    
    if position_side:
        参数['positionSide'] = position_side
    
    订单 = _请求('POST', '/fapi/v1/order', 参数, 需要签名=True)
    
    logger.info(f"下单成功: {side} {调整后数量} {symbol} @ {调整后价格}")
    return 订单


def cancel_order(symbol: str, order_id: int = None, client_order_id: str = None) -> dict:
    """
    撤销订单
    """
    参数 = {'symbol': symbol}
    
    if order_id:
        参数['orderId'] = order_id
    elif client_order_id:
        参数['origClientOrderId'] = client_order_id
    else:
        raise ValueError("必须提供 order_id 或 client_order_id")
    
    结果 = _请求('DELETE', '/fapi/v1/order', 参数, 需要签名=True)
    logger.info(f"撤单成功: {symbol} #{order_id or client_order_id}")
    return 结果


def cancel_all_orders(symbol: str) -> dict:
    """
    撤销指定交易对的所有挂单
    """
    结果 = _请求('DELETE', '/fapi/v1/allOpenOrders', {'symbol': symbol}, 需要签名=True)
    logger.info(f"已撤销 {symbol} 所有挂单")
    return 结果


def fetch_open_orders(symbol: str) -> list:
    """
    获取当前挂单
    """
    数据 = _请求('GET', '/fapi/v1/openOrders', {'symbol': symbol}, 需要签名=True)
    
    订单列表 = []
    for 订单 in 数据:
        订单列表.append({
            'id': 订单['orderId'],
            'clientOrderId': 订单.get('clientOrderId', ''),
            'symbol': 订单['symbol'],
            'side': 订单['side'],
            'price': float(订单['price']),
            'amount': float(订单['origQty']),
            'filled': float(订单.get('executedQty', 0)),
            'status': 订单['status'],
            'type': 订单['type'],
            'timestamp': 订单.get('time', 0)
        })
    
    return 订单列表


def fetch_order(symbol: str, order_id: int) -> dict:
    """
    查询单个订单状态
    """
    return _请求('GET', '/fapi/v1/order', {'symbol': symbol, 'orderId': order_id}, 需要签名=True)


# ============================================================
# WebSocket 相关
# ============================================================

def get_listen_key(enable_retry: bool = True) -> str:
    """
    获取 User Data Stream ListenKey
    """
    重试次数 = 3 if enable_retry else 1
    数据 = _请求('POST', '/fapi/v1/listenKey', 需要签名=False, 重试次数=重试次数)
    return 数据.get('listenKey', '')


def keep_alive_listen_key(enable_retry: bool = True) -> bool:
    """
    延长 ListenKey 有效期
    """
    try:
        重试次数 = 3 if enable_retry else 1
        _请求('PUT', '/fapi/v1/listenKey', 需要签名=False, 重试次数=重试次数)
        return True
    except Exception as e:
        logger.warning(f"延长 ListenKey 失败: {e}")
        return False


# ============================================================
# 兼容接口 (与原 binance.py 保持一致)
# ============================================================

def _get_filters(symbol: str) -> tuple:
    """
    获取交易对过滤器信息 (兼容旧 API)
    
    :return: (tick_size, step_size, min_notional)
    """
    规则 = _获取交易规则(symbol)
    
    # 计算 tick_size 和 step_size
    tick_size = 10 ** (-规则['pricePrecision'])
    step_size = 10 ** (-规则['quantityPrecision'])
    min_notional = 规则['minNotional']
    
    return tick_size, step_size, min_notional


def fetch_order_book(symbol: str, limit: int = 5) -> dict:
    """
    获取盘口深度 (买卖挂单)
    
    :param symbol: 交易对
    :param limit: 深度层数 (默认 5)
    :return: {'bids': [[price, qty], ...], 'asks': [[price, qty], ...]}
    """
    数据 = _请求('GET', '/fapi/v1/depth', {'symbol': symbol, 'limit': limit})
    
    return {
        'bids': [[float(p), float(q)] for p, q in 数据.get('bids', [])],
        'asks': [[float(p), float(q)] for p, q in 数据.get('asks', [])]
    }


# 为了兼容性，保留 exchange 变量 (虽然不再是 CCXT 对象)
class 虚拟交易所:
    """
    模拟 CCXT exchange 对象的部分接口，便于兼容现有代码
    """
    def fetch_order_book(self, symbol: str, limit: int = 5) -> dict:
        """代理到模块函数"""
        return fetch_order_book(symbol, limit)

exchange = 虚拟交易所()


if __name__ == "__main__":
    # 简单测试
    print(f"API Key: {API_KEY[:10]}...")
    print(f"测试网模式: {USE_TESTNET}")
    
    try:
        价格 = fetch_symbol_price("ETHUSDT")
        print(f"ETHUSDT 价格: {价格}")
        
        净值 = fetch_account_equity()
        print(f"账户净值: {净值} USDT")
        
        持仓 = fetch_position("ETHUSDT")
        print(f"ETHUSDT 持仓: {持仓}")
    except Exception as e:
        print(f"测试失败: {e}")
