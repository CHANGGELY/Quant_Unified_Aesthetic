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

def _加载环境变量文件() -> list[Path]:
    """
    加载 .env（兼容你的项目结构）

    你现在的 Key 放在 `Quant_Unified/.env`，但这个模块在 `策略仓库/.../api/` 目录下。
    如果只读“策略目录/.env”，就会出现“明明有 Key 但程序读不到”的错觉。

    规则（不覆盖系统环境变量）：
    1) 优先加载：策略目录的 `.env`（如果你未来想给某个策略单独配 Key）
    2) 再向上查找：最近的 `.env`（通常就是 `Quant_Unified/.env`）
    """
    当前目录 = Path(__file__).resolve().parent
    策略目录 = 当前目录.parent

    候选路径: list[Path] = []

    策略env = 策略目录 / ".env"
    if 策略env.is_file():
        候选路径.append(策略env)

    # 向上查找最近的 .env（作为“全局兜底配置”）
    for 上级目录 in 策略目录.parents:
        上级env = 上级目录 / ".env"
        if 上级env.is_file() and 上级env not in 候选路径:
            候选路径.append(上级env)
            break

    for 路径 in 候选路径:
        load_dotenv(dotenv_path=路径, override=False)

    return 候选路径


已加载_env路径列表 = _加载环境变量文件()

logger = logging.getLogger(__name__)
if 已加载_env路径列表:
    logger.info("✅ 已加载环境变量文件: %s", " , ".join(str(p) for p in 已加载_env路径列表))
else:
    logger.warning("⚠️ 未找到任何 .env 文件：将只能读取系统环境变量（export 的那种）")

# ============================================================
# 环境与密钥配置 (Dual Key Support)
# ============================================================

# 1. 确定运行模式
# 优先读取 USE_REAL_TRADING (由 config_live.py 统一控制)
# 缺省时检查 BINANCE_TESTNET
_is_real_trading = os.getenv("USE_REAL_TRADING", "").lower() in ("true", "1", "yes")
_is_testnet_env = os.getenv("BINANCE_TESTNET", "false").lower() == "true"

if _is_real_trading:
    USE_TESTNET = False
elif _is_testnet_env:
    USE_TESTNET = True
else:
    # 默认安全模式：测试网
    USE_TESTNET = True

# 2. 根据模式加载对应的 API Key
# 逻辑：优先读取专用 Key (REAL_... / TESTNET_...)，读不到则回退到通用 Key (BINANCE_...)
if not USE_TESTNET:
    # --- 实盘模式 ---
    API_KEY = os.getenv("REAL_API_KEY") or os.getenv("BINANCE_API_KEY")
    SECRET_KEY = os.getenv("REAL_SECRET_KEY") or os.getenv("BINANCE_SECRET_KEY")
    logger.info("🚀 正在初始化 [实盘] 环境...")
else:
    # --- 测试网模式 ---
    API_KEY = os.getenv("TESTNET_API_KEY") or os.getenv("BINANCE_API_KEY")
    SECRET_KEY = os.getenv("TESTNET_SECRET_KEY") or os.getenv("BINANCE_SECRET_KEY")
    logger.info("🧪 正在初始化 [测试网] 环境...")

# ============================================================
# 基础 URL 配置 (根据环境切换)
# ============================================================
if USE_TESTNET:
    # Demo Trading 期货端点
    BASE_URL = "https://testnet.binancefuture.com"
    WS_BASE_URL = "wss://stream.binancefuture.com"
    logger.info(f"   REST 端点: {BASE_URL}")
else:
    # 生产环境
    BASE_URL = "https://fapi.binance.com"
    WS_BASE_URL = "wss://fstream.binance.com"
    logger.info("🔴 警告: 使用生产环境，请确保资金安全！")

if not API_KEY or not SECRET_KEY:
    logger.warning("❌ 未检测到有效的 API KEY！请检查环境变量设置 (REAL_... / TESTNET_... / BINANCE_...)")

# API 限速配置 (动态权重)
# 币安标准: 1分钟 2400 权重
# 安全阈值: 2000 (留 400 给撤单等紧急操作)
RATE_LIMIT_WEIGHT_MAX = 2400
RATE_LIMIT_WEIGHT_SAFE = 2000

# 全局限速状态
_API_LOCK = threading.Lock()
_current_weight_1m = 0      # 当前分钟已用权重
_last_weight_update_ts = 0  # 上次更新时间

# ============================================================
# 签名生成
# ============================================================
def 生成签名(参数: dict) -> str:
    """
    使用 HMAC-SHA256 生成币安 API 签名
    
    Args:
        参数: 请求参数字典
    Returns:
        签名字符串 (hex)
    """
    if not SECRET_KEY:
        raise RuntimeError(
            "缺少币安 SECRET_KEY：请在 `.env` 或系统环境变量里配置 "
            "`TESTNET_SECRET_KEY/REAL_SECRET_KEY`（或兼容旧名 `BINANCE_SECRET_KEY`）。"
        )
    查询字符串 = urlencode(参数)
    签名 = hmac.new(
        SECRET_KEY.encode('utf-8'),
        查询字符串.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return 签名

# 全局限速状态
_API_LOCK = threading.Lock()
_current_weight_1m = 0      # 当前分钟已用权重
_last_weight_update_ts = 0  # 上次更新时间

def _更新权重状态(响应头: dict):
    """
    从响应头解析 X-MBX-USED-WEIGHT-1M
    """
    global _current_weight_1m, _last_weight_update_ts
    
    # 尝试读取: x-mbx-used-weight-1m (不区分大小写)
    # requests 的 headers 是 case-insensitive 的
    used_weight = 响应头.get('x-mbx-used-weight-1m')
    
    if used_weight:
        with _API_LOCK:
            try:
                val = int(used_weight)
                _current_weight_1m = val
                _last_weight_update_ts = time.time()
                
                # Debug logging (每增加 100 打印一次，避免刷屏)
                if val % 100 < 5: 
                   # logger.debug(f"当前 API 权重: {val}/{RATE_LIMIT_WEIGHT_MAX}")
                   pass
            except ValueError:
                pass

def _检查风控():
    """
    请求前检查: 如果权重过高，强制等待到下一分钟
    """
    global _current_weight_1m
    
    with _API_LOCK:
        if _current_weight_1m >= RATE_LIMIT_WEIGHT_SAFE:
            logger.warning(f"⚠️ API 权重告急 ({_current_weight_1m}/{RATE_LIMIT_WEIGHT_MAX})，暂停请求等待重置...")
            
            # 简单策略: 睡 60 秒 (不够精确但绝对安全) -> 也可以计算距离下一分钟剩余秒数
            # 币安的计数器是每分钟重置，但具体时刻不确定，通常是滚动或自然分？
            # 官方文档: "1m" interval.
            # 稳妥起见，sleep 30s 再试
            time.sleep(30)
            
            # 醒来后归零猜测 (实际会通过下一次请求头校准)
            _current_weight_1m = 0


def _网络异常中文解释(异常: Exception, *, 端点: str | None = None) -> str:
    """
    把“看不懂的英文网络异常”翻译成中文人话，方便你快速判断问题在哪。

    说明：
    - 这里的“SSL”指的是网页/接口的“加密通道”（像打电话先要确认身份并加密通话）。
    - 这里的“DNS”指的是“域名电话本”（把 testnet.binancefuture.com 这种名字翻译成 IP 地址）。
    """
    try:
        异常文本 = str(异常) or ""
    except Exception:
        异常文本 = ""
    小写文本 = 异常文本.lower()

    业务补充 = ""
    if 端点 == "/fapi/v1/listenKey":
        业务补充 = "（这是 ListenKey：用户数据流“临时门票”，短暂失败一般重试就能恢复；持续失败会影响订单推送）"

    # 1) SSL（加密通道）相关
    if isinstance(异常, requests.exceptions.SSLError):
        if "unexpected_eof_while_reading" in 小写文本 or "ssleoferror" in 小写文本:
            return (
                "中文解释：SSL（加密通道）握手时连接被提前断开，像“刚接通电话就被挂断”。"
                "常见原因：网络抖动、代理/公司网关拦截、对方服务器瞬时不稳定；一般重试即可。"
                f"{业务补充}"
            )
        if "certificate verify failed" in 小写文本 or "cert" in 小写文本 and "verify" in 小写文本:
            return (
                "中文解释：SSL（加密通道）证书校验失败，像“身份证真，但系统不认可发证机构”。"
                "常见原因：系统根证书缺失、被代理改写证书；可尝试更新系统证书或关闭/更换代理后再试。"
                f"{业务补充}"
            )
        if "wrong version number" in 小写文本:
            return (
                "中文解释：SSL（加密通道）协议版本不匹配，通常是被代理/网关劫持成了非加密连接。"
                "建议检查代理配置或切换网络。"
                f"{业务补充}"
            )
        return f"中文解释：SSL（加密通道）连接失败，常见原因是网络/代理/证书问题。{业务补充}"

    # 2) 代理相关
    if isinstance(异常, requests.exceptions.ProxyError):
        return f"中文解释：代理连接失败，请检查代理地址/账号密码是否正确，或先关闭代理排查。{业务补充}"

    # 3) 超时相关
    if isinstance(异常, requests.exceptions.ConnectTimeout):
        return f"中文解释：连接超时，像“敲门没人开”。常见原因是网络不通/防火墙拦截/代理太慢。{业务补充}"
    if isinstance(异常, requests.exceptions.ReadTimeout):
        return f"中文解释：读取超时，像“对方接了电话但一直不说话”。可能是服务器拥堵或网络卡顿。{业务补充}"

    # 4) 连接相关（包含 DNS、被重置等）
    if isinstance(异常, requests.exceptions.ConnectionError):
        if "name or service not known" in 小写文本 or "temporary failure in name resolution" in 小写文本:
            return f"中文解释：DNS（域名电话本）解析失败，找不到服务器地址；可尝试更换网络或 DNS。{业务补充}"
        if "nodename nor servname provided" in 小写文本:
            return f"中文解释：DNS（域名电话本）解析失败，域名解析不到 IP；可尝试更换网络或 DNS。{业务补充}"
        if "connection reset" in 小写文本 or "reset by peer" in 小写文本:
            return (
                "中文解释：连接被对方强制断开（reset），像“聊一半被挂断”。"
                "常见原因：网络抖动、代理不稳定、对方限流；建议重试并适当降低请求频率。"
                f"{业务补充}"
            )
        return f"中文解释：网络连接失败，常见原因是网络不稳定、代理或防火墙拦截。{业务补充}"

    # 兜底：未知类型
    return f"中文解释：网络请求异常，可能是网络/代理/服务器波动导致；建议重试并检查网络环境。{业务补充}"


def _请求(方法: str, 端点: str, 参数: dict = None, 需要签名: bool = False, 重试次数: int = 3) -> dict:
    """
    统一的 HTTP 请求封装 (集成动态风控)
    """
    if 参数 is None:
        参数 = {}
    
    URL = BASE_URL + 端点
    # 需要签名的接口一定需要 Key；否则会在生成签名时出现 None.encode 这种“看不懂的报错”
    if 需要签名 and (not API_KEY or not SECRET_KEY):
        raise RuntimeError(
            "缺少币安 API Key/Secret：请在 `.env` 或系统环境变量里配置 "
            "`TESTNET_API_KEY/TESTNET_SECRET_KEY`（测试网）或 `REAL_API_KEY/REAL_SECRET_KEY`（实盘）。"
        )

    # listenKey（用户数据流）接口也必须带 API Key（但不需要签名）
    if (端点 == "/fapi/v1/listenKey") and (not API_KEY):
        raise RuntimeError(
            "缺少币安 API Key：获取 ListenKey 需要 `TESTNET_API_KEY/REAL_API_KEY`（或兼容旧名 `BINANCE_API_KEY`）。"
        )

    请求头 = {'X-MBX-APIKEY': API_KEY} if API_KEY else {}
    
    if 需要签名:
        参数['timestamp'] = int(time.time() * 1000)
        参数['recvWindow'] = 60000
        参数['signature'] = 生成签名(参数)
    
    for 尝试 in range(重试次数):
        # 1. 动态风控检查
        _检查风控()
        
        try:
            if 方法 == 'GET':
                响应 = requests.get(URL, params=参数, headers=请求头, timeout=10)
            elif 方法 == 'POST':
                响应 = requests.post(URL, params=参数, headers=请求头, timeout=10)
            elif 方法 == 'DELETE':
                响应 = requests.delete(URL, params=参数, headers=请求头, timeout=10)
            elif 方法 == 'PUT':
                响应 = requests.put(URL, params=参数, headers=请求头, timeout=10)
            else:
                raise ValueError(f"不支持的 HTTP 方法: {方法}")
            
            # 2. 更新风控权重
            _更新权重状态(响应.headers)
            
            数据 = 响应.json()
            
            if 响应.status_code == 200:
                return 数据
            else:
                错误码 = 数据.get('code', 响应.status_code)
                错误信息 = 数据.get('msg', '未知错误')
                
                # 418 / 429: 必须停止!
                if 响应.status_code in [418, 429]:
                    retry_after = int(响应.headers.get('Retry-After', 60))
                    logger.error(f"⛔️ 触发币安 API 限制 (HTTP {响应.status_code})! 暂停 {retry_after} 秒...")
                    time.sleep(retry_after)
                    # 抛出异常中断策略，不要重试了
                    raise Exception(f"API Limit Reached: {错误信息}")

                # 判断是否可重试
                if 错误码 in [-1001, -1003, -1015]:  # 网络/限速错误
                    logger.warning(f"API 请求失败 ({尝试+1}/{重试次数}): [{错误码}] {错误信息}")
                    time.sleep(1)
                    continue
                else:
                    raise Exception(f"[{错误码}] {错误信息}")
                    
        except requests.exceptions.RequestException as e:
            中文解释 = _网络异常中文解释(e, 端点=端点)
            logger.warning(f"网络请求失败 ({尝试+1}/{重试次数}): {e} | {中文解释}")
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


def set_leverage(symbol: str, leverage: int) -> dict:
    """
    设置逐笔杠杆（合约 leverage）
    文档: POST /fapi/v1/leverage
    """
    lev = int(leverage)
    if lev < 1:
        raise ValueError(f"leverage 必须 >= 1, 当前={lev}")
    参数 = {'symbol': symbol, 'leverage': lev}
    res = _请求('POST', '/fapi/v1/leverage', 参数, 需要签名=True)
    logger.info(f"设置杠杆成功: {symbol} leverage={lev}")
    return res


def set_margin_type(symbol: str, margin_type: str = "CROSSED") -> dict:
    """
    设置保证金模式（CROSSED / ISOLATED）
    文档: POST /fapi/v1/marginType
    """
    mt = str(margin_type).upper().strip()
    if mt == "CROSS":
        mt = "CROSSED"
    if mt not in {"CROSSED", "ISOLATED"}:
        raise ValueError(f"margin_type 只支持 CROSSED/ISOLATED, 当前={margin_type}")

    参数 = {'symbol': symbol, 'marginType': mt}
    try:
        res = _请求('POST', '/fapi/v1/marginType', 参数, 需要签名=True)
        logger.info(f"设置保证金模式成功: {symbol} marginType={mt}")
        return res
    except Exception as e:
        msg = str(e)
        # Binance: code -4046, "No need to change margin type."
        if "-4046" in msg or "No need to change margin type" in msg:
            logger.info(f"保证金模式无需修改: {symbol} (已是 {mt})")
            return {"symbol": symbol, "marginType": mt, "msg": "already_set"}
        raise


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
# 成交/交易明细 (私有)
# ============================================================

def fetch_user_trades(
    symbol: str,
    *,
    from_id: int | None = None,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
    limit: int = 1000,
) -> list[dict]:
    """
    获取用户成交明细（真实成交记录，带 trade id）

    文档：GET /fapi/v1/userTrades
    - 这是“账本”（像银行流水），用于脚本重启后重建 FIFO 等状态
    - 需要签名（私有接口）
    """
    if not symbol:
        raise ValueError("symbol 不能为空")

    参数: dict = {"symbol": symbol, "limit": int(limit)}
    if from_id is not None:
        参数["fromId"] = int(from_id)
    if start_time_ms is not None:
        参数["startTime"] = int(start_time_ms)
    if end_time_ms is not None:
        参数["endTime"] = int(end_time_ms)

    数据 = _请求("GET", "/fapi/v1/userTrades", 参数, 需要签名=True)
    结果: list[dict] = []
    for t in 数据:
        结果.append(
            {
                "id": int(t.get("id", 0)),
                "orderId": int(t.get("orderId", 0)),
                "symbol": t.get("symbol", symbol),
                "side": t.get("side", ""),
                "positionSide": t.get("positionSide", "BOTH"),
                "price": float(t.get("price", 0)),
                "qty": float(t.get("qty", 0)),
                "realizedPnl": float(t.get("realizedPnl", 0)),
                "commission": float(t.get("commission", 0)),
                "commissionAsset": t.get("commissionAsset", ""),
                "time": int(t.get("time", 0)),
                "maker": bool(t.get("maker", False)),
            }
        )
    return 结果


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
