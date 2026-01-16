"""
【3号对冲策略】实盘交易脚本：
1. 基于 WebSocket 实时价格，围绕 base_price 生成上下各5格挂单（同时开多与开空）
2. 成交后按一步网格距离设置止盈，并以“平劣”原则减少账本持仓
3. 使用二号策略的 API/WS 模块复用，确保 post_only 与统一账户支持
"""

import sys
import os
import asyncio
import logging
from pathlib import Path

# 自动计算项目根目录 (Quant_Unified)
# 结构: Quant_Unified/策略仓库/三号对冲策略/real_trading.py
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]

# 将项目子目录加入搜索路径
for folder in ['基础库', '服务', '策略仓库', '应用']:
    p = PROJECT_ROOT / folder
    if p.exists() and str(p) not in sys.path:
        sys.path.append(str(p))
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.append(str(PROJECT_ROOT))

from 策略仓库.三号对冲策略.config_live import live_strategies
from 策略仓库.三号对冲策略.program.engine import HedgeStrategy
from 策略仓库.二号网格策略.api import binance as api
from 策略仓库.二号网格策略.api.ws_manager import BinanceWsManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class HedgeSymbolTrader:
    """
    单交易对的 3号对冲策略执行器：
    - 价格触发：实时 ticker 触发逐格事件
    - 下单策略：在每个网格价位同时挂多与空的限价开仓单，post_only 保证 maker
    - 止盈与平劣：由内部引擎在价格跨格时进行账本更新；实盘下单的止盈单暂用限价 reduceOnly 实现
    """
    def __init__(self, conf):
        self.conf = conf
        self.symbol = conf.symbol
        self.engine = HedgeStrategy(conf)
        self.latest_price = 0.0
        self.ws = None

    async def on_event(self, event):
        try:
            if isinstance(event, dict) and ('s' in event and 'c' in event):
                # 行情 ticker
                if event.get('s').upper() == self.symbol.replace('/', '').upper():
                    price = float(event.get('c', 0) or 0)
                    if price > 0:
                        self.latest_price = price
                        self.engine.处理价格(price)
                        await self._sync_orders()
        except Exception as e:
            logger.error(f"事件处理失败: {e}")

    async def on_connected(self):
        logger.info(f"[{self.symbol}] WebSocket 已连接，进行初始下单同步...")
        await self._sync_orders()

    async def _sync_orders(self):
        # 基于当前 base_price，生成上下各5格价位，并在这些价位挂双向限价单
        if self.engine.基础价 is None:
            if self.latest_price > 0:
                self.engine.初始化(self.latest_price)
            else:
                # 尝试拉一次最新价
                p = api.fetch_symbol_price(self.symbol)
                if p > 0:
                    self.latest_price = p
                    self.engine.初始化(p)
                else:
                    return

        价位列表 = self.engine.当前网格价列表()
        for 价 in 价位列表:
            # 多与空双向挂单（post_only）
            try:
                # 多方向：BUY LONG
                api.place_limit_order(self.symbol, 'BUY', 价, self.engine.多头规模, position_side='LONG', post_only=getattr(self.conf, 'post_only', True))
                # 空方向：SELL SHORT
                api.place_limit_order(self.symbol, 'SELL', 价, self.engine.空头规模, position_side='SHORT', post_only=getattr(self.conf, 'post_only', True))
            except Exception as e:
                logger.error(f"[{self.symbol}] 挂单失败 @ {价}: {e}")


async def main():
    logger.info("=== 启动 3号对冲策略 实盘 ===")
    traders = [HedgeSymbolTrader(cfg) for cfg in live_strategies]
    ws = BinanceWsManager(symbols=[cfg.symbol for cfg in live_strategies])
    for t in traders:
        ws.add_listener(t.on_event)
        ws.add_connected_listener(t.on_connected)
    await ws.start()


if __name__ == '__main__':
    asyncio.run(main())

