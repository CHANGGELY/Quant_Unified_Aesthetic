"""
Simple Backtester (Zero-Dependency)
-----------------------------------
这是一个超轻量级的回测运行器，专门用于在不支持 Nautilus Trader 的环境 (如 Py3.14) 中
验证 strategy.py 的核心逻辑。

它做了什么：
1. 欺骗 Python 导入本地的 mock nautilus_trader 包。
2. 加载 Parquet 数据。
3. 手动把 Tick 喂给 Strategy。
4. 打印生成的订单日志。
"""
import sys
import os
import time

# 确保能导入当前目录的 mock 包
sys.path.append(os.getcwd())

from data_loader import load_depth5_parquet, load_trades_parquet, merge_tick_streams
from strategy import MarketMakerConfig, MarketMakerStrategy
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue

def main():
    print("=== 启动简易回测 (Python 3.14 兼容模式) ===")
    
    depth_path = "/Users/chuan/Desktop/xiangmu/客户端/Quant_Unified/data/行情数据_整理/BTCUSDC/2025-12-21/depth.parquet"
    trades_path = "/Users/chuan/Desktop/xiangmu/客户端/Quant_Unified/data/行情数据_整理/BTCUSDC/2025-12-21/trade.parquet"
    
    # 1. 准备配置
    instrument_id = InstrumentId(Symbol("BTCUSDC"), Venue("BINANCE"))
    config = MarketMakerConfig(
        instrument_id=instrument_id,
        window_sec=30.0, # 配合 .pkl 模型 h30
    )
    
    # 2. 初始化策略
    print("正在初始化策略...")
    strategy = MarketMakerStrategy(config)
    strategy.on_start()
    
    # 3. 加载数据
    print("加载数据...")
    # 模拟 Instrument 对象用于精度处理
    class MockInstrument:
        def make_price(self, p): return round(float(p), 2)
        def make_qty(self, q): return round(float(q), 3)
        
    quotes = load_depth5_parquet(depth_path, instrument_id, "ms", instrument=MockInstrument())
    trades = load_trades_parquet(trades_path, instrument_id, "ms", instrument=MockInstrument())
    
    stream = merge_tick_streams(quotes, trades)
    
    print("开始播放行情...")
    import warnings
    warnings.filterwarnings("ignore") # 屏蔽烦人的 sklearn/lightgbm 警告

    count = 0
    start_time = time.time()
    
    for tick in stream:
        count += 1
        
        if hasattr(tick, "bid_price"): # QuoteTick
            strategy.on_quote_tick(tick)
        else:
            strategy.on_trade_tick(tick)
            
        if count % 10000 == 0:
            print(f"处理进度: {count} ticks...")
            
    end_time = time.time()
    print(f"回测完成! 耗时: {end_time - start_time:.2f}s")
    print(f"一共生成了 {len(strategy._grid_orders)} (当前挂单数) / (日志里应该有很多提交记录)")
    
    # 简单的逻辑验证
    if strategy.signal_engine and strategy.signal_engine.model:
        print("✅ LightGBM 模型加载并调用成功")
        
    print(f"Strategy Grid Orders: {len(strategy._grid_orders)}")

if __name__ == "__main__":
    main()
