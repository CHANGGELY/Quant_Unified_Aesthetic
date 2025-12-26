from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path to allow importing from 策略仓库
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pandas as pd
import numpy as np
from program.step3_train_calibrate import load_artifacts, TrainArtifacts
from program.step2_build_dataset import build_features_1s

def main():
    # 1. 加载模型
    # 假设我们使用 horizon=10s, mode=wmp 的模型
    model_path = "models/BTCUSDT_wmp_h10.pkl"
    if not Path(model_path).exists():
        print(f"Model not found: {model_path}")
        print("Please run backtest.py first to generate models.")
        return

    print(f"Loading model from {model_path}...")
    art: TrainArtifacts = load_artifacts(model_path)
    print(f"Model loaded: {art.model_name}")
    print(f"Features required: {art.feature_names}")

    # 2. 模拟新的实时数据 (Mock Data)
    # 在实盘中，这里会替换为从 WebSocket 获取的实时 OrderBook 快照
    # 构造一个简单的 DataFrame，包含必要的深度列
    print("\nSimulating incoming real-time data...")
    
    # 模拟 5 条数据，包含 50 档深度
    rows = []
    base_price = 60000.0
    for i in range(5):
        row = {
            "exchange_time": 1700000000000 + i * 1000,
            "bid1_p": base_price, "bid1_q": 1.0,
            "ask1_p": base_price + 0.1, "ask1_q": 1.0,
        }
        # 填充 bid2..50, ask2..50
        for lvl in range(2, 51):
            row[f"bid{lvl}_p"] = base_price - (lvl-1)*0.1
            row[f"bid{lvl}_q"] = 1.0 + lvl * 0.1
            row[f"ask{lvl}_p"] = base_price + 0.1 + (lvl-1)*0.1
            row[f"ask{lvl}_q"] = 1.0 + lvl * 0.1
        
        # 添加一些波动
        base_price += np.random.choice([-0.5, 0.5])
        rows.append(row)
    
    df_new = pd.DataFrame(rows)
    df_new.index = pd.to_datetime(df_new["exchange_time"], unit="ms", utc=True)
    
    # 3. 特征工程 (实时)
    # 注意：build_features_1s 内部有一些 rolling 操作 (e.g. ma_60, rsi_14)
    # 在实盘中，需要维护一个历史 buffer 来计算这些状态特征
    # 这里为了演示，我们假设 buffer 已经有了（实际上我们用刚刚生成的 5 条，前面的 rolling 可能会是 NaN）
    print("Computing features...")
    feat, _ = build_features_1s(df_new)
    
    # 填充 NaN (实盘中 buffer 足够长就不会有 NaN)
    feat = feat.fillna(0.0)
    
    # 4. 预测 (Inference)
    # 确保特征列对齐
    X_live = feat[art.feature_names]
    
    print("\nPredicting...")
    # 得到原始概率
    raw_proba = art.base_model.predict_proba(X_live)
    # 得到校准后概率
    cal_proba = art.calibrated_model.predict_proba(X_live)
    
    for i in range(len(X_live)):
        p_down, p_hold, p_up = cal_proba[i]
        print(f"Time: {X_live.index[i].time()} | Down: {p_down:.4f} | Hold: {p_hold:.4f} | Up: {p_up:.4f}")
        
        # 简单的交易逻辑示例
        if p_up > 0.6:
            print("  >>> SIGNAL: BUY")
        elif p_down > 0.6:
            print("  >>> SIGNAL: SELL")

if __name__ == "__main__":
    main()
