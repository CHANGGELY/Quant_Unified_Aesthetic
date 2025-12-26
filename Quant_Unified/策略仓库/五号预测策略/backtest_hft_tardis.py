#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
高频回测脚本 (Tardis + 100ms)
功能：加载训练好的模型，在 100ms 频率下模拟交易并生成收益报告。
"""

import os
import sys
import pandas as pd
import numpy as np
import joblib
import logging
from pathlib import Path
import matplotlib.pyplot as plt

# 添加项目根目录
sys.path.append(os.getcwd())

from Quant_Unified.策略仓库.五号预测策略.config import Config
from Quant_Unified.策略仓库.五号预测策略.train_hft_tardis import HFTTrainer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class HFTBacktester:
    def __init__(self, config: Config):
        self.cfg = config
        self.trainer = HFTTrainer(config)
        self.models = {}
        self._load_models()

    def _load_models(self):
        """加载所有 Horizon 的模型"""
        model_dir = Path(__file__).parent / "models"
        for h in self.cfg.horizons:
            model_name = f"{self.cfg.symbol}_h{h}_100ms.pkl"
            model_path = model_dir / model_name
            if model_path.exists():
                self.models[h] = joblib.load(model_path)
                logger.info(f"成功加载模型: {model_name}")
            else:
                logger.warning(f"未找到模型文件: {model_name}")

    def run_backtest(self, date_str: str):
        """运行单日回测"""
        if not self.models:
            logger.error("无可用模型，回测停止。")
            return
            
        logger.info(f"🚀 开始回测日期: {date_str}")
        
        # 1. 加载并生成特征
        snaps = list(self.trainer.loader.load_day(date_str))
        if not snaps:
            return
            
        df = pd.DataFrame(snaps)
        df_feat = self.trainer.extract_features(df)
        
        # 特征列
        feature_cols = [c for c in df_feat.columns if not c.startswith('target_') and c not in ['timestamp', 'symbol']]
        X = df_feat[feature_cols]
        
        # 2. 预测
        # 我们用最大的 Horizon 作为主信号，或者加权平均
        main_h = max(self.cfg.horizons)
        if main_h not in self.models:
            main_h = list(self.models.keys())[0]
            
        df_feat['prob_return'] = self.models[main_h].predict(X)
        
        # 3. 模拟交易 (Simple Fixed Time In)
        # 这里使用“滞后”信号策略：
        # 如果预测未来收益 > 阈值 -> 做多
        # 如果预测未来收益 < -阈值 -> 做空
        
        threshold = self.cfg.label_threshold
        df_feat['signal'] = 0
        df_feat.loc[df_feat['prob_return'] > threshold, 'signal'] = 1
        df_feat.loc[df_feat['prob_return'] < -threshold, 'signal'] = -1
        
        # 4. 计算收益
        # 假设我们每一帧 (100ms) 调仓
        df_feat['next_ret'] = df_feat['wap1'].shift(-1) / df_feat['wap1'] - 1
        
        # 考虑手续费: 只有信号变化时才产生费用
        df_feat['signal_change'] = df_feat['signal'].diff().abs()
        df_feat['strat_ret'] = df_feat['signal'] * df_feat['next_ret'] - df_feat['signal_change'] * self.cfg.fee_rate
        
        df_feat['cum_ret'] = (1 + df_feat['strat_ret'].fillna(0)).cumprod()
        
        # 5. 统计结果
        total_ret = df_feat['cum_ret'].iloc[-1] - 1
        trades = df_feat[df_feat['signal_change'] != 0].shape[0]
        
        logger.info(f"📈 回测完成! 总收益: {total_ret:.2%}, 交易次数: {trades}")
        
        # 6. 可视化
        self._plot_result(df_feat, date_str)
        
    def _plot_result(self, df, date_str):
        plt.figure(figsize=(12, 6))
        plt.plot(df['cum_ret'], label='Strategy')
        plt.title(f"HFT Backtest Result: {self.cfg.symbol} - {date_str}")
        plt.xlabel("Time (100ms ticks)")
        plt.ylabel("Cumulative Return")
        plt.legend()
        plt.grid(True)
        
        save_path = Path(__file__).parent / f"equity_curve_{date_str}.png"
        plt.savefig(save_path)
        logger.info(f"收益曲线已保存: {save_path}")

if __name__ == "__main__":
    cfg = Config(symbol="BTCUSDT", data_source="tardis")
    backtester = HFTBacktester(cfg)
    # backtester.run_backtest("2024-03-01")
    print("Backtester 初始化成功，高频回测框架已就绪。")
