# 这个文件用于快速排查二号网格策略在币安统一账户(PAPI)下的挂单查询是否正常

import hashlib
import logging
import os
from dotenv import load_dotenv

from Quant_Unified.策略仓库.二号网格策略.api import binance as api


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _密钥摘要(密钥: str) -> str:
    if not 密钥:
        return "<未配置>"
    digest = hashlib.sha256(密钥.encode('utf-8')).hexdigest()
    return f"len={len(密钥)} sha256={digest[:10]}"


def test_fetch_orders():
    根目录 = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(根目录, 'Quant_Unified', '策略仓库', '二号网格策略', '.env')
    load_dotenv(dotenv_path=env_path)

    logger.info(f"ACCOUNT_TYPE: {api.ACCOUNT_TYPE}")
    logger.info(f"API_KEY: {_密钥摘要(getattr(api, 'API_KEY', '') or '')}")

    raw_symbol = "SOLUSDC"
    if api.ACCOUNT_TYPE != 'unified':
        logger.info("当前不是统一账户模式，跳过 PAPI 调试")
        return

    try:
        orders = api.fetch_open_orders(raw_symbol)
        logger.info(f"封装接口 fetch_open_orders 返回挂单数: {len(orders)}")
        for o in (orders or [])[:5]:
            oid = o.get('id') or (o.get('info') or {}).get('orderId')
            side = (o.get('side') or '').upper()
            price = o.get('price')
            amount = o.get('amount')
            status = o.get('status')
            logger.info(f"挂单摘要: id={oid} side={side} price={price} qty={amount} status={status}")
    except Exception as e:
        logger.error(f"调用封装接口 fetch_open_orders 失败: {e}")

    try:
        orders_raw = api.papi_exchange.papiGetUmOpenOrders(params={'symbol': raw_symbol})
        logger.info(f"PAPI 原始接口 openOrders 返回条数: {len(orders_raw)}")
        for o in (orders_raw or [])[:5]:
            logger.info(
                "PAPI挂单摘要: "
                + f"orderId={o.get('orderId')} side={o.get('side')} price={o.get('price')} qty={o.get('origQty')} status={o.get('status')} type={o.get('type')}"
            )
    except Exception as e:
        logger.error(f"调用 PAPI 原始接口 openOrders 失败: {e}")


if __name__ == "__main__":
    test_fetch_orders()
