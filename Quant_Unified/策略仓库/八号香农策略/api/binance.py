import os
import time
import logging
import uuid
import ccxt
from dotenv import load_dotenv
from pathlib import Path
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import threading
import random

# 加载环境变量
# 优先加载策略目录下的 .env 文件
current_dir = Path(__file__).parent
strategy_dir = current_dir.parent
env_path = strategy_dir / '.env'
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)

API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
PROXY = os.getenv("BINANCE_PROXY")
ACCOUNT_TYPE = os.getenv("BINANCE_ACCOUNT_TYPE", "normal").lower()
API_MAX_QPS = float(os.getenv("BINANCE_API_MAX_QPS", "1"))
USE_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() == "true"  # 新增：测试网开关
_API_LOCK = threading.Lock()
_LAST_API_TS = 0.0

if not API_KEY or not SECRET_KEY:
    logger.warning("未检测到 BINANCE_API_KEY 或 BINANCE_SECRET_KEY，API 功能将不可用。")

# 初始化交易所对象 (主要用于下单和行情 - FAPI)
exchange_config = {
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
    }
}

# 测试网配置
if USE_TESTNET:
    # 测试网不支持统一账户 (PAPI)，强制切换到普通模式
    ACCOUNT_TYPE = 'normal'
    logger.info("🧪 准备启用币安合约测试网 (Futures Testnet) 模式")

if PROXY:
    exchange_config['proxies'] = {
        'http': PROXY,
        'https': PROXY
    }
    logger.info(f"已启用代理: {PROXY}")

exchange = ccxt.binanceusdm(exchange_config)

# 如果是测试网/Demo Trading，在实例化后直接覆盖 URL
if USE_TESTNET:
    # CCXT 期货 sandbox 模式已弃用，必须使用 Demo Trading URL
    # 参考: CCXT urls['demo'] 映射
    demo_urls = {
        'fapiPublic': 'https://demo-fapi.binance.com/fapi/v1',
        'fapiPublicV2': 'https://demo-fapi.binance.com/fapi/v2',
        'fapiPublicV3': 'https://demo-fapi.binance.com/fapi/v3',
        'fapiPrivate': 'https://demo-fapi.binance.com/fapi/v1',
        'fapiPrivateV2': 'https://demo-fapi.binance.com/fapi/v2',
        'fapiPrivateV3': 'https://demo-fapi.binance.com/fapi/v3',
        'fapiData': 'https://demo-fapi.binance.com/futures/data',
    }
    # 直接覆盖 exchange.urls['api']
    if 'api' in exchange.urls:
        for key, url in demo_urls.items():
            exchange.urls['api'][key] = url
    
    logger.info(f"🧪 已激活 Demo Trading 模式 (合约测试交易)")
    logger.info(f"   Fapi端点: {exchange.urls.get('api', {}).get('fapiPrivate', 'N/A')}")

# 初始化统一账户专用对象 (用于获取余额 - PAPI)
papi_exchange = None
if ACCOUNT_TYPE == 'unified':
    try:
        papi_config = exchange_config.copy()
        # 移除 defaultType: future，使用默认的 binance 实例以支持 generic methods
        if 'defaultType' in papi_config['options']:
            del papi_config['options']['defaultType']
        
        papi_exchange = ccxt.binance(papi_config)
        
        # 【关键修改】保留 exchange 为 binanceusdm 实例以确保 FAPI 兼容性
        # papi_exchange 仅用于显式调用的 PAPI 接口
        # exchange = papi_exchange  <-- 移除此行，避免污染默认 exchange
        
        logger.info("已启用统一账户 (Unified Account) 模式，PAPI 客户端初始化成功。")
    except Exception as e:
        logger.error(f"初始化 PAPI 客户端失败: {e}")

logger.info(f"当前账户模式: {ACCOUNT_TYPE.upper()}")

def retry_wrapper(func, *args, **kwargs):
    """
    API 请求重试装饰器/包装器
    """
    max_retries = 3

    def _extract_json_body(text: str):
        if not text:
            return None
        if '{' not in text or '}' not in text:
            return None
        s = text.find('{')
        t = text.rfind('}')
        if t > s:
            return text[s:t + 1]
        return None

    def _strip_query_from_urls(text: str):
        if not text:
            return text
        try:
            import re
            def repl(m):
                u = m.group(0)
                return u.split('?', 1)[0]
            return re.sub(r'https?://\S+', repl, text)
        except Exception:
            return text

    def _cn_reason(text: str, func_name: str):
        endpoint_hint = None
        if '/papi/v1/um/openOrders' in text:
            endpoint_hint = '查询统一账户UM挂单'
        elif '/papi/v1/um/positionRisk' in text:
            endpoint_hint = '查询统一账户UM持仓'
        elif '/papi/v1/account' in text:
            endpoint_hint = '查询统一账户账户信息（资产/持仓概览）'
        elif '/papi/v1/listenKey' in text or 'listenKey' in text:
            endpoint_hint = '获取/续期 ListenKey（用户数据流）'

        net_keys = (
            'timed out', 'timeout', 'Connection aborted', 'Connection reset', 'ECONNRESET',
            'ENOTFOUND', 'Name or service not known', 'Temporary failure in name resolution',
            'SSLError', 'SSL', 'CERTIFICATE', 'EOF occurred', 'ProxyError', 'Cannot connect',
            'RemoteDisconnected', 'ReadTimeout', 'ConnectTimeout'
        )
        lower = (text or '').lower()
        if 'code":-2015' in lower or 'invalid api-key' in lower:
            base = 'API Key/IP权限错误：请检查API Key是否有效、是否绑定了当前IP，以及是否开启了【允许统一账户交易】权限'
        elif any(k.lower() in lower for k in net_keys):
            base = '网络连接超时：连接币安服务器超时或被断开，请检查网络环境或代理设置'
        elif '429' in lower or 'too many requests' in lower or 'code":-1003' in lower:
            base = '请求过于频繁：触发了币安的频率限制(429/1003)，系统将自动退避并重载'
        elif '502' in lower or '503' in lower or '504' in lower:
            base = '币安服务端异常：服务器短暂不可用(5xx/维护中)，系统将尝试重连'
        elif 'margin is insufficient' in lower or 'code":-2019' in lower:
            base = '保证金不足：账户余额不足以支撑当前下单规模，请检查持仓或减少本金权重'
        else:
            base = '请求失败：常见原因是网络波动或接口抖动，系统会自动重试'

        if endpoint_hint:
            return f'{endpoint_hint} | {base}'
        if func_name and func_name != 'unknown':
            return f'{func_name} | {base}'
        return base
    # [新增] 定义无需重试的错误码
    # -2011: Unknown order sent (单子已经不在了，没必要重试)
    # -2013: Order does not exist
    # -1121: Invalid symbol
    # -1102: Mandatory parameter missing
    FATAL_CODES = ['-2011', '-2013', '-1121', '-1102', 'Invalid API-key']

    for i in range(max_retries):
        try:
            with _API_LOCK:
                now = time.time()
                min_interval = 1.0 / API_MAX_QPS if API_MAX_QPS > 0 else 0
                wait = (_LAST_API_TS + min_interval) - now
                if wait > 0:
                    time.sleep(wait)
                res = func(*args, **kwargs)
                globals()['_LAST_API_TS'] = time.time()
                return res
        except Exception as e:
            msg = str(e)
            
            # [核心优化] 如果是撤单报 -2011，说明单子已经处理掉了，直接返回成功或静默退出
            if "-2011" in msg and "delete" in str(func).lower():
                # logger.debug(f"撤单提示: 订单已不存在或已成交 (忽略 -2011)")
                return {'status': 'CANCELED', 'id': 'already_gone'}

            json_body = ''
            if '{' in msg and '}' in msg:
                try: json_body = msg[msg.find('{'):msg.rfind('}')+1]
                except: pass
            
            safe_msg = _strip_query_from_urls(msg)
            if SECRET_KEY and len(SECRET_KEY) > 10:
                safe_msg = safe_msg.replace(SECRET_KEY, '***')
            
            safe_msg_no_body = safe_msg
            if json_body and json_body in safe_msg_no_body:
                safe_msg_no_body = safe_msg_no_body.replace(json_body, '').strip()
            
            func_name = getattr(func, '__name__', str(func))
            if 'unbound method' in str(func_name).lower() or '<bound method' in str(func_name) or 'method' in str(func_name).lower():
                obj = getattr(func, '__self__', None)
                if obj:
                    class_name = type(obj).__name__
                    func_real_name = getattr(func, '__name__', 'api_call')
                    func_name = f"{class_name}.{func_real_name}"
                else:
                    func_name = str(func).split(' ')[0].strip('<')

            # 检查是否是致命错误，无需重试
            if any(fc in msg for fc in FATAL_CODES):
                if json_body:
                    logger.error(f"API 请求致命错误 (不重试): {func_name} | {safe_msg_no_body} | body: {json_body}")
                else:
                    logger.error(f"API 请求致命错误 (不重试): {func_name} | {safe_msg_no_body}")
                raise

            reason_cn = _cn_reason(safe_msg, func_name)
            if 'code":-2015' in msg or 'Invalid API-key' in msg:
                logger.error(f"API Key/IP/权限错误 (不重试): {reason_cn} [{func_name}] {safe_msg_no_body}")
                raise
            if json_body:
                logger.error(f"API 请求失败 ({i+1}/{max_retries}): {reason_cn} [{func_name}] {safe_msg_no_body} | body: {json_body}")
            else:
                logger.error(f"API 请求失败 ({i+1}/{max_retries}): {reason_cn} [{func_name}] {safe_msg_no_body}")
            if i == max_retries - 1:
                raise
            if '429' in msg or 'Too Many Requests' in msg:
                backoff = min(4, 1 * (2 ** i)) + random.uniform(0, 0.3)
                time.sleep(backoff)
            else:
                time.sleep(1)

def fetch_ticker_price():
    """
    获取所有交易对最新价格
    返回字典 key 格式: 统一转换为无斜杠的大写格式 (e.g. "ETHUSDC")，以匹配 Config
    """
    tickers = retry_wrapper(exchange.fetch_tickers)
    # 转换为 {symbol: price} 格式
    # CCXT 返回的 symbol 通常是 "ETH/USDT" 或 "ETH/USDT:USDT"
    # 我们需要将其标准化为 "ETHUSDT"
    price_map = {}
    for k, v in tickers.items():
        # 移除 '/' 和 ':USDT', ':USDC' 等后缀 (简单处理: 移除非字母数字字符)
        # 或者更安全的方式: 只移除 '/'
        # 注意: 某些合约可能有后缀 (e.g. delivery futures)，但我们主要关注 perpetual
        
        # 简单处理: 移除 '/'
        clean_symbol = k.replace('/', '').split(':')[0]
        price_map[clean_symbol] = v['last']
        
        # 为了兼容性，保留原始 key (如果需要) - 但这里为了解决 KeyError，我们主要依赖 clean_symbol
        # 也可以同时存两个 key
        price_map[k] = v['last']
        
    return price_map

def fetch_symbol_price(symbol):
    try:
        s = symbol.replace('/', '').upper()
        base = s[:-4]
        quote = s[-4:]
        std = f"{base}/{quote}"
        t = retry_wrapper(exchange.fetch_ticker, std)
        return float(t['last']) if 'last' in t and t['last'] is not None else float(t.get('close', 0) or 0)
    except Exception:
        return 0.0

_markets_loaded = False
_market_map = {}

def _load_markets_once():
    global _markets_loaded, _market_map
    if _markets_loaded:
        return
    try:
        target = {}
        # 优先加载默认客户端市场信息
        try:
            markets = exchange.load_markets()
            for k, v in markets.items():
                key_norm = ''.join(ch for ch in k if ch.isalnum()).upper()
                target[key_norm] = v
        except Exception:
            pass
        # 统一账户模式下，补充加载 PAPI 市场信息，覆盖/新增 USDC 等交易对
        if ACCOUNT_TYPE == 'unified' and papi_exchange:
            try:
                p_markets = papi_exchange.load_markets()
                for k, v in p_markets.items():
                    key_norm = ''.join(ch for ch in k if ch.isalnum()).upper()
                    target[key_norm] = v
            except Exception:
                pass
        _market_map = target
        _markets_loaded = True
    except Exception:
        _markets_loaded = False

def _get_market(symbol):
    _load_markets_once()
    key = symbol.replace('/', '').upper()
    return _market_map.get(key)

def _get_filters(symbol):
    m = _get_market(symbol)
    tick = None
    step = None
    min_notional = None
    if m and 'info' in m:
        flt = m['info'].get('filters', [])
        for f in flt:
            t = f.get('filterType') or f.get('type')
            if t == 'PRICE_FILTER':
                tick = f.get('tickSize') or tick
            elif t == 'LOT_SIZE':
                step = f.get('stepSize') or step
            elif t in ('MIN_NOTIONAL', 'NOTIONAL'):
                min_notional = f.get('minNotional') or f.get('notional') or min_notional
    if not tick and m and m.get('precision'):
        p = m['precision'].get('price')
        if isinstance(p, int):
            tick = str(Decimal('1') / (Decimal('10') ** p))
    if not step and m and m.get('precision'):
        a = m['precision'].get('amount')
        if isinstance(a, int):
            step = str(Decimal('1') / (Decimal('10') ** a))
    if (tick is None or step is None or min_notional is None) and ACCOUNT_TYPE == 'unified' and papi_exchange:
        try:
            raw = symbol.replace('/', '').upper()
            methods = [
                'papiPublicGetUmExchangeInfo',
                'papiPublicGetExchangeInfo',
                'papiGetExchangeInfo'
            ]
            info = None
            for name in methods:
                if hasattr(papi_exchange, name):
                    func = getattr(papi_exchange, name)
                    try:
                        # 优先按 symbol 查询，若不支持则不带参数
                        try:
                            info = retry_wrapper(func, params={'symbol': raw})
                        except Exception:
                            info = retry_wrapper(func)
                    except Exception:
                        info = None
                if info:
                    break
            if isinstance(info, dict):
                symbols = info.get('symbols') or []
                for s in symbols:
                    if s.get('symbol') == raw:
                        flt = s.get('filters', [])
                        for f in flt:
                            t = f.get('filterType') or f.get('type')
                            if t == 'PRICE_FILTER' and not tick:
                                tick = f.get('tickSize') or tick
                            elif t == 'LOT_SIZE' and not step:
                                step = f.get('stepSize') or step
                            elif t in ('MIN_NOTIONAL', 'NOTIONAL') and not min_notional:
                                min_notional = f.get('minNotional') or f.get('notional') or min_notional
                        
                        # 部分 PAPI 不返回 precision，fallback 为价格/数量位数推断
                        break
        except Exception:
            pass
    return tick, step, min_notional

def _floor_to_step(value, step):
    if not step:
        return float(value)
    dv = Decimal(str(value))
    ds = Decimal(str(step))
    q = (dv / ds).to_integral_value(rounding=ROUND_DOWN)
    return float(q * ds)

def _ceil_to_step(value, step):
    if not step:
        return float(value)
    dv = Decimal(str(value))
    ds = Decimal(str(step))
    q = (dv / ds).to_integral_value(rounding=ROUND_UP)
    return float(q * ds)

def _adjust_order(symbol, price, quantity):
    tick, step, min_notional = _get_filters(symbol)
    adj_price = _floor_to_step(price, tick) if tick else float(price)
    adj_qty = _floor_to_step(quantity, step) if step else float(quantity)
    if adj_price <= 0:
        adj_price = float(price)
    if adj_qty <= 0:
        adj_qty = _ceil_to_step(quantity, step) if step else float(quantity)
    if min_notional:
        notional = Decimal(str(adj_price)) * Decimal(str(adj_qty))
        mn = Decimal(str(min_notional))
        if notional < mn:
            need = (mn / Decimal(str(adj_price)))
            adj_qty = float(_ceil_to_step(need, step) if step else need)
    return adj_price, adj_qty

def _papi_place_with_fallback(raw_symbol, side, price, quantity, client_id, position_side=None, time_in_force='GTC'):
    if not papi_exchange:
        raise ValueError("PAPI exchange not initialized")
    try:
        params = {
            'symbol': raw_symbol,
            'side': side.upper(),
            'type': 'LIMIT',
            'quantity': quantity,
            'price': price,
            'timeInForce': time_in_force,
            'newClientOrderId': client_id
        }
        if position_side:
            params['positionSide'] = position_side.upper()
        try:
            return papi_exchange.papiPostUmOrder(params)
        except Exception as e0:
            if 'code":-4061' in str(e0):
                clean = params.copy()
                clean.pop('positionSide', None)
                return papi_exchange.papiPostUmOrder(clean)
            raise e0
    except Exception as e:
        msg = str(e)
        if 'code":-1111' in msg or 'Precision is over the maximum' in msg:
            for p_dec in (3, 2, 1, 0):
                for q_dec in (5, 4, 3, 2, 1, 0):
                    try:
                        rp = float(Decimal(str(price)).quantize(Decimal('1.' + ('0' * p_dec)), rounding=ROUND_DOWN)) if p_dec > 0 else float(Decimal(str(price)).to_integral_value(rounding=ROUND_DOWN))
                        rq = float(Decimal(str(quantity)).quantize(Decimal('1.' + ('0' * q_dec)), rounding=ROUND_DOWN)) if q_dec > 0 else float(Decimal(str(quantity)).to_integral_value(rounding=ROUND_DOWN))
                        if rp <= 0 or rq <= 0:
                            continue
                        payload = {
                            'symbol': raw_symbol,
                            'side': side.upper(),
                            'type': 'LIMIT',
                            'quantity': rq,
                            'price': rp,
                            'timeInForce': time_in_force,
                            'newClientOrderId': client_id
                        }
                        if position_side:
                            payload['positionSide'] = position_side.upper()
                        try:
                            return papi_exchange.papiPostUmOrder(payload)
                        except Exception as e0:
                            if 'code":-4061' in str(e0):
                                clean = payload.copy()
                                clean.pop('positionSide', None)
                                return papi_exchange.papiPostUmOrder(clean)
                            raise e0
                    except Exception as e2:
                        if 'code":-1111' in str(e2) or 'Precision is over the maximum' in str(e2):
                            continue
                        raise e2
        raise e

def fetch_account_equity(asset_name='USDT'):
    """
    获取账户净值 (Equity) = 余额 + 未实现盈亏
    兼容普通账户 (FAPI) 和 统一账户 (PAPI)
    """
    asset_name = asset_name.upper()
    
    if ACCOUNT_TYPE == 'unified' and papi_exchange:
        try:
            # 统一账户 PAPI: 获取账户信息 (包含总净值)
            if hasattr(papi_exchange, 'papiGetAccount'):
                account_data = retry_wrapper(papi_exchange.papiGetAccount)
                # account_data 通常包含 totalEquity 或 totalMarginBalance
                # PAPI 文档: GET /papi/v1/account -> { "totalEquity": "...", "totalMarginBalance": "..." }
                # 这里的 totalEquity 是以 USD 计价的 (统一账户默认 USD)
                # 如果用户主要资产是 USDT，这通常非常接近 USDT 价值
                if isinstance(account_data, dict):
                    # 优先取 accountEquity (实盘返回) 或 totalEquity (文档旧称)
                    equity = float(account_data.get('accountEquity', 0.0))
                    if equity > 0:
                        return equity
                    equity = float(account_data.get('totalEquity', 0.0))
                    if equity > 0:
                        return equity
                    equity = float(account_data.get('totalMarginBalance', 0.0))
                    if equity > 0:
                        return equity
            
            # 备选: PAPI Get Balance (可能返回列表)
            if hasattr(papi_exchange, 'papiGetBalance'):
                balance_data = retry_wrapper(papi_exchange.papiGetBalance)
                if isinstance(balance_data, dict):
                     return float(balance_data.get('totalEquity', 0.0))
                # 如果是列表，很难直接计算总净值，暂不处理，以免算错
        except Exception as e:
            logger.warning(f"PAPI 获取净值失败: {e}，尝试回退...")
            
    # 普通账户 FAPI: GET /fapi/v2/account
    try:
        account_data = retry_wrapper(exchange.fapiPrivateGetAccount)
        # FAPI 返回结构: { "totalMarginBalance": "...", "totalUnrealizedProfit": "...", ... }
        # 注意: totalMarginBalance = totalWalletBalance + totalUnrealizedProfit
        return float(account_data.get('totalMarginBalance', 0.0))
    except Exception as e:
        logger.error(f"获取账户净值失败: {e}")
        return 0.0

def fetch_account_balance(asset_name='USDT'):
    """
    获取账户余额
    兼容普通账户 (FAPI) 和 统一账户 (PAPI)
    :param asset_name: 资产名称，默认为 'USDT'，可传入 'USDC'
    """
    # 自动大写
    asset_name = asset_name.upper()
    
    if ACCOUNT_TYPE == 'unified' and papi_exchange:
        try:
            # 尝试使用 PAPI 获取统一账户余额
            balance_data = None
            
            # 优先尝试 papiGetBalance (部分新版本 ccxt 支持)
            if hasattr(papi_exchange, 'papiGetBalance'):
                balance_data = retry_wrapper(papi_exchange.papiGetBalance)
            # 其次尝试 papiPrivateGetBalance
            elif hasattr(papi_exchange, 'papiPrivateGetBalance'):
                balance_data = retry_wrapper(papi_exchange.papiPrivateGetBalance)
            
            if balance_data:
                # 统一账户返回的数据结构通常是列表，包含各资产信息
                # 例如: [{'asset': 'USDT', 'crossMarginFree': '100.0', ...}, ...]
                
                # 情况 1: 返回的是列表 (Assets List)
                if isinstance(balance_data, list):
                    for asset in balance_data:
                        if asset.get('asset') == asset_name:
                            # 优先取 crossMarginFree (全仓可用余额)
                            return float(asset.get('crossMarginFree', 0.0))
                    # 如果没找到指定资产，尝试找一下常见的其他资产并打印警告(仅调试用)
                    return 0.0 
                
                # 情况 2: 返回的是字典 (Account Info) - 这种情况通常是总资产视图，很难拆分单个币种
                elif isinstance(balance_data, dict):
                    # 只有当查询 USDT 时，totalMarginBalance 才有意义
                    if asset_name == 'USDT':
                        return float(balance_data.get('totalMarginBalance', 0.0))
                    else:
                        logger.warning(f"PAPI 返回字典格式，无法直接获取 {asset_name} 余额，尝试回退")
                        
            else:
                logger.warning("当前 CCXT 版本不支持 PAPI 余额查询方法，尝试使用 FAPI 获取余额 (可能不准确)...")
        except Exception as e:
            logger.error(f"PAPI 获取余额失败: {e}，将回退到 FAPI")
            
    # 普通账户或回退逻辑
    try:
        balance = retry_wrapper(exchange.fetch_balance)
        if asset_name in balance:
            return float(balance[asset_name]['free'])
        else:
            return 0.0
    except Exception as e:
        logger.error(f"获取 {asset_name} 余额失败: {e}")
        return 0.0

def fetch_position(symbol):
    """
    获取单个币种的持仓信息
    返回: {'amount': float, 'entryPrice': float, 'unRealizedProfit': float}
    """
    if ACCOUNT_TYPE == 'unified' and papi_exchange and hasattr(papi_exchange, 'papiGetUmPositionRisk'):
        try:
            # PAPI 方式获取持仓
            # 注意: PAPI symbol 通常不需要 '/'，且需要大写
            raw_symbol = symbol.replace('/', '').upper()
            positions = retry_wrapper(papi_exchange.papiGetUmPositionRisk, params={'symbol': raw_symbol})
            # PAPI 返回的是列表，即使只查一个 symbol
            for pos in positions:
                if pos['symbol'] == raw_symbol:
                    return {
                        'amount': float(pos['positionAmt']),
                        'raw_amount': float(pos['positionAmt']),
                        'entryPrice': float(pos['entryPrice']),
                        'unRealizedProfit': float(pos['unRealizedProfit'])
                    }
            return {'amount': 0.0, 'entryPrice': 0.0, 'unRealizedProfit': 0.0}
        except Exception as e:
            logger.warning(f"PAPI 获取持仓失败: {e}，尝试回退...")

    # fetch_positions 返回所有持仓列表
    positions = retry_wrapper(exchange.fetch_positions, symbols=[symbol])
    for pos in positions:
        if pos['symbol'] == symbol:
            return {
                'amount': float(pos['contracts']) if pos['side'] == 'long' else -float(pos['contracts']) if pos['side'] == 'short' else float(pos['info']['positionAmt']),
                # ccxt 统一化有时会有差异，这里直接用 info 原生字段更稳妥
                # positionAmt: 正数为多，负数为空
                'raw_amount': float(pos['info']['positionAmt']),
                'entryPrice': float(pos['entryPrice']),
                'unRealizedProfit': float(pos['unrealizedPnl'])
            }
    return {'amount': 0.0, 'entryPrice': 0.0, 'unRealizedProfit': 0.0}

def fetch_income_history(symbol=None, start_time_ms=None, end_time_ms=None, limit=1000, income_type=None):
    params = {}
    if symbol:
        params['symbol'] = symbol.replace('/', '').upper()
    if start_time_ms is not None:
        params['startTime'] = int(start_time_ms)
    if end_time_ms is not None:
        params['endTime'] = int(end_time_ms)
    if limit is not None:
        params['limit'] = int(limit)
    if income_type:
        params['incomeType'] = str(income_type)

    if ACCOUNT_TYPE == 'unified':
        if papi_exchange and hasattr(papi_exchange, 'papiGetUmIncome'):
            return retry_wrapper(papi_exchange.papiGetUmIncome, params=params)
        if papi_exchange and hasattr(papi_exchange, 'papiPrivateGetUmIncome'):
            return retry_wrapper(papi_exchange.papiPrivateGetUmIncome, params=params)
        raise RuntimeError("统一账户模式下获取收入流水失败: 未找到 PAPI 接口 papiGetUmIncome")

    if hasattr(exchange, 'fapiPrivateGetIncome'):
        return retry_wrapper(exchange.fapiPrivateGetIncome, params=params)

    raise RuntimeError("获取收入流水失败: 未找到 FAPI 接口 fapiPrivateGetIncome")

def cancel_all_orders(symbol):
    """
    撤销指定交易对的所有挂单
    """
    if ACCOUNT_TYPE == 'unified':
        if papi_exchange and hasattr(papi_exchange, 'papiDeleteUmAllOpenOrders'):
            raw_symbol = symbol.replace('/', '').upper()
            return retry_wrapper(papi_exchange.papiDeleteUmAllOpenOrders, params={'symbol': raw_symbol})
        # 统一账户下不再回退到 FAPI，避免账户模式冲突
        raise RuntimeError("统一账户模式下撤单失败: 未找到 PAPI 撤单接口 papiDeleteUmAllOpenOrders")

    return retry_wrapper(exchange.cancel_all_orders, symbol)

def cancel_order(symbol, order_id, is_conditional=False):
    """撤销单个挂单"""
    if ACCOUNT_TYPE == 'unified':
        raw_symbol = symbol.split(':')[0].replace('/', '').upper()
        if is_conditional:
            if papi_exchange and hasattr(papi_exchange, 'papiDeleteUmConditionalOrder'):
                params = {'symbol': raw_symbol}
                # PAPI 撤单接口非常敏感，id 必须根据性质放在对应字段
                s_id = str(order_id)
                if s_id.isdigit() and len(s_id) > 8: # 粗略判断是否是服务器 ID
                    params['orderId'] = s_id
                else:
                    params['origClientOrderId'] = s_id
                return retry_wrapper(papi_exchange.papiDeleteUmConditionalOrder, params)
            raise RuntimeError("统一账户模式下撤销条件单失败: 未找到 PAPI 接口 papiDeleteUmConditionalOrder")
        else:
            if papi_exchange and hasattr(papi_exchange, 'papiDeleteUmOrder'):
                params = {'symbol': raw_symbol}
                s_id = str(order_id)
                # 策略：如果 ID 全是数字且较长，优先尝试 orderId 字段
                if s_id.isdigit() and len(s_id) > 8:
                    params['orderId'] = s_id
                else:
                    params['origClientOrderId'] = s_id
                
                # [关键点] 必须传位置参数 (params)，不能传关键字参数 (params=params)
                # 许多 CCXT 动态映射方法不支持关键字参数注入
                return retry_wrapper(papi_exchange.papiDeleteUmOrder, params)
            raise RuntimeError("统一账户模式下撤单失败: 未找到 PAPI 撤单接口 papiDeleteUmOrder")

    return retry_wrapper(exchange.cancel_order, id=order_id, symbol=symbol)

def place_limit_order(symbol, side, price, quantity, client_order_id=None, position_side=None, post_only=False):
    """
    下单
    :param post_only: 是否只做 Maker (挂单)，默认为 False。如果为 True，会使用 GTX 模式，确保不吃单。
    """
    time_in_force = 'GTX' if post_only else 'GTC'
    params = {'timeInForce': time_in_force}
    
    # 如果没有指定 client_order_id，则自动生成一个
    if client_order_id:
        params['newClientOrderId'] = client_order_id
    else:
        params['newClientOrderId'] = f"c_grid_{uuid.uuid4().hex[:12]}"

    price, quantity = _adjust_order(symbol, price, quantity)
    # 【关键修改】如果是统一账户模式，强制使用 PAPI 下单接口
    if ACCOUNT_TYPE == 'unified':
        try:
            # PAPI 下单接口: POST /papi/v1/um/order
            # 方法名通常为 papiPostUmOrder
            if papi_exchange and hasattr(papi_exchange, 'papiPostUmOrder'):
                raw_symbol = symbol.replace('/', '').upper()
                return _papi_place_with_fallback(raw_symbol, side, price, quantity, params['newClientOrderId'], position_side, time_in_force=time_in_force)
        except Exception as e:
            logger.error(f"PAPI 下单失败: {e}")
            raise # PAPI 失败不应回退到 FAPI，因为可能会导致账户模式冲突

    return retry_wrapper(
        exchange.create_order,
        symbol=symbol,
        type='LIMIT',
        side=side,
        amount=quantity,
        price=price,
        params=params
    )

def get_listen_key(enable_retry=True):
    """
    获取 User Data Stream ListenKey
    """
    # 【关键修改】统一账户的 ListenKey 获取方式
    # PAPI: POST /papi/v1/listenKey
    
    if ACCOUNT_TYPE == 'unified':
        if papi_exchange and hasattr(papi_exchange, 'papiPostListenKey'):
            data = retry_wrapper(papi_exchange.papiPostListenKey)
            return data['listenKey']
        raise RuntimeError("统一账户模式下获取 ListenKey 失败: 未找到 PAPI 接口 papiPostListenKey")

    data = retry_wrapper(exchange.fapiPrivatePostListenKey)
    return data['listenKey']

def keep_alive_listen_key(enable_retry=True):
    """
    延长 ListenKey 有效期
    """
    if ACCOUNT_TYPE == 'unified':
        if papi_exchange and hasattr(papi_exchange, 'papiPutListenKey'):
            try:
                return retry_wrapper(papi_exchange.papiPutListenKey)
            except Exception as e:
                msg = str(e)
                if 'code":-1125' in msg or 'This listenKey does not exist' in msg:
                    logger.warning("ListenKey 已失效，将在下次 WS 重连时获取新的 ListenKey")
                raise
        raise RuntimeError("统一账户模式下续期 ListenKey 失败: 未找到 PAPI 接口 papiPutListenKey")

    return retry_wrapper(exchange.fapiPrivatePutListenKey)


def fetch_open_orders(symbol):
    """
    获取当前挂单
    """
    if ACCOUNT_TYPE == 'unified' and papi_exchange and hasattr(papi_exchange, 'papiGetUmOpenOrders'):
        try:
            raw_symbol = symbol.replace('/', '').upper()
            # 注意: PAPI 的 openOrders 接口传 symbol 有时会报参数错误 (-1102 Mandatory parameter... or -1100 Illegal chars)
            # 为了稳定性，我们不传 symbol 获取所有 UM 挂单，然后在本地过滤
            all_orders = retry_wrapper(papi_exchange.papiGetUmOpenOrders)

            # 本地过滤 symbol
            orders = [o for o in all_orders if o.get('symbol') == raw_symbol]

            # 优先尝试带 market 解析
            market = _get_market(symbol)
            parsed = papi_exchange.parse_orders(orders, market=market)

            # 如果解析结果为空，但原始数据不为空，说明被过滤了，自动切换到无 market 解析模式
            if not parsed and orders:
                # 这是一个预期的兼容性行为，不需要 Warning，仅 Debug 记录
                logger.debug(f"PAPI 订单解析触发回退 (CCXT Filter) - raw_count={len(orders)}")
                parsed = papi_exchange.parse_orders(orders)
                # 手动补全 symbol，确保上层逻辑能识别
                for o in parsed:
                    if not o.get('symbol'):
                        o['symbol'] = symbol

            return parsed
        except Exception as e:
            # 统一账户模式下，PAPI 是唯一可信数据源，失败时不再回退到 FAPI/ccxt，避免 -2015 噪音
            logger.error(f"PAPI 获取挂单失败 (统一账户，不回退 FAPI): {e}")
            raise

    # 非统一账户模式下，才使用传统 futures 接口
    return retry_wrapper(exchange.fetch_open_orders, symbol)

def fetch_order(symbol, order_id):
    """
    查询单个订单状态
    """
    if ACCOUNT_TYPE == 'unified' and papi_exchange and hasattr(papi_exchange, 'papiGetUmOrder'):
        try:
            raw_symbol = symbol.replace('/', '').upper()
            response = retry_wrapper(papi_exchange.papiGetUmOrder, params={'symbol': raw_symbol, 'orderId': order_id})
            return papi_exchange.parse_order(response, market=_get_market(symbol))
        except Exception as e:
             logger.warning(f"PAPI 查询订单失败: {e}，尝试回退...")

    return retry_wrapper(exchange.fetch_order, id=order_id, symbol=symbol)

import pandas as pd

def fetch_candle_data(symbol, end_time, interval='1m', limit=1000):
    """
    获取 K 线数据 (用于回测数据下载)
    :param symbol: 交易对
    :param end_time: 截止时间 (datetime 对象)
    :param interval: K 线周期
    :param limit: 获取条数
    :return: DataFrame
    """
    # 将 datetime 转换为毫秒时间戳
    end_ts = int(end_time.timestamp() * 1000)
    
    # 使用 ccxt 获取数据
    # 注意: ccxt fetch_ohlcv 的 params 支持 endTime (Binance 特有)
    ohlcv = retry_wrapper(
        exchange.fetch_ohlcv,
        symbol=symbol,
        timeframe=interval,
        limit=limit,
        params={'endTime': end_ts}
    )
    
    # 转换为 DataFrame
    # 格式: [timestamp, open, high, low, close, volume]
    df = pd.DataFrame(ohlcv, columns=['candle_begin_time', 'open', 'high', 'low', 'close', 'volume'])
    
    return df
