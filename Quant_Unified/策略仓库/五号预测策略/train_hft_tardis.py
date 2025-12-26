#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
高频模型训练脚本 (Tardis + 100ms)
功能：从 Tardis Parquet 数据重放快照，提取高频特征，并训练 LightGBM 模型。
"""

import os
import sys
import pandas as pd
import numpy as np
import lightgbm as lgb
from pathlib import Path
import joblib
import logging
from datetime import datetime

# 添加项目根目录
sys.path.append(os.getcwd())

from Quant_Unified.策略仓库.五号预测策略.config import Config
from Quant_Unified.策略仓库.五号预测策略.data_loader_tardis import TardisDataLoader

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class HFTTrainer:
    def __init__(self, config: Config):
        self.cfg = config
        self.loader = TardisDataLoader(config)
        
    def extract_features(self, df_snap: pd.DataFrame) -> pd.DataFrame:
        """
        特征提取逻辑 (100ms 级别)
        """
        df = df_snap.copy()
        
        # 1. 基础价格
        df['mid_p'] = (df['bid1_p'] + df['ask1_p']) / 2
        df['wap1'] = (df['bid1_p'] * df['ask1_q'] + df['ask1_p'] * df['bid1_q']) / (df['bid1_q'] + df['ask1_q'])
        
        # 2. 盘口特征
        df['spread'] = (df['ask1_p'] - df['bid1_p']) / df['mid_p']
        df['imbalance1'] = (df['bid1_q'] - df['ask1_q']) / (df['bid1_q'] + df['ask1_q'])
        
        # 多档位 Imbalance (前 5 档)
        for i in range(1, 6):
            b_q = df[f'bid{i}_q']
            a_q = df[f'ask{i}_q']
            df[f'imb{i}'] = (b_q - a_q) / (b_q + a_q + 1e-8)
            
        # 3. 价格变动特征 (以 100ms 采样点为基准)
        # 注意：这里需要对时间序列敏感
        df['log_ret'] = np.log(df['wap1'] / df['wap1'].shift(1))
        
        # 滚动窗口 (如 1s = 10 帧, 5s = 50 帧)
        df['vol_1s'] = df['log_ret'].rolling(10).std()
        df['vol_5s'] = df['log_ret'].rolling(50).std()
        
        return df.dropna()

    def create_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成预测标签 (未来收益率)
        """
        for h in self.cfg.horizons:
            # 未来 h 个 100ms 的收益率 (WAP 价格)
            # 例如 h=50 表示未来 5 秒
            label_col = f'target_{h}'
            df[label_col] = df['wap1'].shift(-h) / df['wap1'] - 1
            
        return df.dropna()

    def train(self, date_list: list[str]):
        """
        主训练流程
        """
        all_features = []
        
        for date_str in date_list:
            logger.info(f"正在处理训练数据: {date_str}")
            snaps = list(self.loader.load_day(date_str))
            if not snaps:
                continue
                
            df_day = pd.DataFrame(snaps)
            df_day = self.extract_features(df_day)
            df_day = self.create_labels(df_day)
            
            all_features.append(df_day)
            
        if not all_features:
            logger.error("无可用训练数据")
            return
            
        full_df = pd.concat(all_features, ignore_index=True)
        
        # 特征列
        feature_cols = [c for c in full_df.columns if not c.startswith('target_') and c not in ['timestamp', 'symbol']]
        
        # 为每个 horizon 训练一个模型
        for h in self.cfg.horizons:
            target_col = f'target_{h}'
            logger.info(f"开始训练模型: Horizon={h} (约 {h/10}s)")
            
            # 简单的回归任务 (预测收益率)
            X = full_df[feature_cols]
            y = full_df[target_col]
            
            # 划分训练/测试
            split_idx = int(len(X) * self.cfg.train_frac)
            X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
            y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
            
            model = lgb.LGBMRegressor(
                n_estimators=1000,
                learning_rate=0.05,
                max_depth=6,
                num_leaves=31,
                random_state=self.cfg.random_state,
                n_jobs=-1,
                importance_type='gain'
            )
            
            model.fit(
                X_train, y_train,
                eval_set=[(X_test, y_test)],
                eval_metric='l2',
                callbacks=[lgb.early_stopping(stopping_rounds=50)]
            )
            
            # 保存
            model_name = f"{self.cfg.symbol}_h{h}_100ms.pkl"
            model_path = Path(__file__).parent / "models" / model_name
            os.makedirs(model_path.parent, exist_ok=True)
            joblib.dump(model, model_path)
            logger.info(f"模型已保存: {model_path}")

if __name__ == "__main__":
    cfg = Config(symbol="BTCUSDT", data_source="tardis")
    # 示例：训练 2024-03-01 的数据
    trainer = HFTTrainer(cfg)
    # trainer.train(["2024-03-01"])
    print("Trainer 初始化成功，准备开始高频训练任务。")
