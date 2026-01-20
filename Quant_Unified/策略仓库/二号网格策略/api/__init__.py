"""
二号网格策略 / api 包

这个目录放什么？
    这里放的是“跟币安打交道”的代码，比如：
    - 拉取 K 线（历史价格）
    - 查询余额/持仓/挂单
    - 下单/撤单
    - WebSocket（网络长连接：交易所主动推送消息给你，而不是你不停去问）

怎么用？
    一般不需要直接运行本文件。
    你会在别的脚本里这样导入：
        from 策略仓库.二号网格策略.api import binance as api
        from 策略仓库.二号网格策略.api.ws_manager import BinanceWsManager
"""

