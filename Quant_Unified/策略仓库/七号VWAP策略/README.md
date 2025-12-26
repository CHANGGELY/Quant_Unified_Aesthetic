# 七号VWAP策略

## 策略简介
基于 VWAP (成交量加权平均价) 的择时策略。

**核心逻辑**：
- **做多信号**: 收盘价 > VWAP_n
- **做空信号**: 收盘价 < VWAP_n

**最优参数**: N = 1196 (约 20 小时)

## 回测结果 (2021-01-01 至今, ETHUSDT, 0手续费)
| 指标 | 值 |
|---|---|
| 年化收益 | 60.01% |
| 最大回撤 | -59.2% |
| Calmar | 1.01 |
| 最终净值 | 8.11 倍 |
| 超额收益 | +28.2% (vs Buy & Hold) |

## 文件结构
```
七号VWAP策略/
├── seven_strategy_optimization.py   # 暴力遍历优化
├── seven_strategy_bayesian.py       # 贝叶斯优化 (Optuna)
├── generate_chart_data.py           # 生成可视化数据
├── dashboard/
│   ├── index.html                   # 需服务器版
│   ├── vwap_dashboard_standalone.html  # 独立版 (推荐)
│   └── chart_data.json              # 图表数据
└── README.md                        # 本文件
```

## 使用方法

### 1. 查看回测结果
双击打开 `dashboard/vwap_dashboard_standalone.html`

### 2. 重新优化参数
```bash
python seven_strategy_optimization.py
```

### 3. 贝叶斯快速优化 (大区间)
```bash
python seven_strategy_bayesian.py
```
