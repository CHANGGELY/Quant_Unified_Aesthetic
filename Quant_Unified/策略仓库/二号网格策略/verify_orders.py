import asyncio
import logging

from 策略仓库.二号网格策略.api import binance as api

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def verify_orders():
    if api.ACCOUNT_TYPE == 'unified':
        logger.info("检测到统一账户模式")
    else:
        logger.info("检测到普通账户模式")

    logger.info("=== 开始验证挂单状态 ===")

    symbols = ['SOLUSDC', 'ETHUSDC']

    for symbol in symbols:
        try:
            logger.info(f"\n正在查询 {symbol} 挂单...")
            # 强制使用 fetch_open_orders (封装好的)
            orders = await asyncio.to_thread(api.fetch_open_orders, symbol)

            buy_orders = [o for o in orders if o['side'].upper() == 'BUY']
            sell_orders = [o for o in orders if o['side'].upper() == 'SELL']

            logger.info(f"[{symbol}] 挂单统计:")
            logger.info(f"  - 买单数量: {len(buy_orders)}")
            logger.info(f"  - 卖单数量: {len(sell_orders)}")
            logger.info(f"  - 总计: {len(orders)}")

            if len(buy_orders) > 0:
                logger.info("  - 买单详情 (Top 5):")
                for o in buy_orders[:5]:
                    logger.info(f"    价格: {o['price']} / 数量: {o['amount']}")

            if len(sell_orders) > 0:
                logger.info("  - 卖单详情 (Top 5):")
                for o in sell_orders[:5]:
                    logger.info(f"    价格: {o['price']} / 数量: {o['amount']}")

            if len(buy_orders) < 4 or len(sell_orders) < 4:
                logger.warning(f"⚠️ [{symbol}] 挂单数量不足! 期望每边至少 4 个。")
            else:
                logger.info(f"✅ [{symbol}] 挂单数量符合预期。")

        except Exception as e:
            logger.error(f"查询 {symbol} 失败: {e}")

if __name__ == "__main__":
    asyncio.run(verify_orders())
