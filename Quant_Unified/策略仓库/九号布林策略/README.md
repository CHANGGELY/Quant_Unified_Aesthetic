# 九号布林策略（只推送信号，不下单）

## 1. 这是什么？
这是一个“信号雷达”：
- 只订阅币安 BTC 的 **1 分钟 K 线**（K 线就是“这一分钟开盘价/最高价/最低价/收盘价”的小表格）
- 每分钟计算一次你定义的布林带/均线条件
- 满足条件后，在 **下一分钟** 给钉钉机器人推送一条包含关键词 **“布林”** 的消息

重要结论（你最关心的）：
- **这个策略不下单**，只读公开行情，所以 **不需要 Binance API Key / Secret**（API=接口，Key=钥匙；Secret=密码）
- 真正需要 Key/Secret 的场景是：你要“发真实订单”或“读取你账户的私密数据/成交推送”

---

## 2. 你需要准备什么？
- 一台能联网的电脑
- Python 3（建议 3.10+）
- 能访问币安（网络别被墙/代理别拦证书）
- 一个钉钉群机器人 Webhook（你已经有了）

---

## 3. 安装依赖
在终端进入这个目录后运行：

```bash
python3 -m pip install -r requirements.txt
```

---

## 4. 配置（最重要）
### 4.1 只配置钉钉就能跑（推荐）
复制一份配置模板：

```bash
cp .env.example .env.local
```

然后编辑 `.env.local`，至少填这一行：

```bash
DINGTALK_WEBHOOK_URL=你的钉钉机器人Webhook完整URL
```

安全提醒：
- `.env.local` 里放的是“密码本”，**不要发给任何人**，也不要放进压缩包里。

### 4.2 证书报错怎么办（常见）
如果你启动时看到类似：
`CERTIFICATE_VERIFY_FAILED`（证书校验失败）

你可以在 `.env.local` 里加：

```bash
BINANCE_WS_SSL_VERIFY=false
```

解释：这等于“先不检查证书真假”，能解决某些代理/公司网络插证书导致的问题；但安全性会下降，尽量只在你确认网络环境可信时用。

---

## 5. 一键验证：你能不能收到钉钉
运行（会立刻发送 1 条消息并退出）：

```bash
python3 -X utf8 real_trading.py --test-dingtalk
```

解释：`-X utf8` 是让 Python 强制用 UTF-8 编码，避免中文乱码。

---

## 6. 正式运行（实时）
```bash
python3 -X utf8 real_trading.py
```

你会看到实时日志（程序在“动”）：
- 预热：拉取少量历史 1m/1d K 线，用来让指标一启动就有窗口
- WebSocket（长连接：像电话不挂断）：开始接收每分钟 K 线
- 满足条件后：排程下一分钟推送钉钉（并做 1 分钟 20 条限频）

---

## 6.1 （可选）用历史数据快速验证逻辑：回测
如果你不想等实盘行情触发，可以用回测“快进”验证有没有信号：

```bash
python3 -X utf8 backtest.py --days 30
```

它会从币安公开接口拉取真实历史 1m/1d K 线，然后离线回放策略逻辑。

---

## 7. 常用可调参数（都写进 `.env.local`）
只要你不填，程序就用默认值：
- `BOLL9_SYMBOL`：交易对，默认 `BTCUSDT`
- `BOLL9_USE_TESTNET`：是否测试网（Demo 行情），默认 `false`
- `BOLL9_WARMUP_1M_DAYS`：预热分钟 K 线天数，默认 `12`
- `BOLL9_WARMUP_1D_DAYS`：预热日线 K 线天数，默认 `70`
- `BOLL9_DINGTALK_KEYWORD`：钉钉关键词，默认 `布林`
- `BOLL9_DINGTALK_RPM_LIMIT`：钉钉每分钟最多发送，默认 `20`

阈值（你策略里写死的那些，也可以改）：
- `BOLL9_TH_15M_MA_SPREAD`（默认 500）
- `BOLL9_TH_30M_MA_SPREAD`（默认 1000）
- `BOLL9_TH_1H_MA_SPREAD_UP`（默认 1800）
- `BOLL9_TH_1H_MA_SPREAD_DOWN`（默认 1500）
- `BOLL9_TH_4H_MA_SPREAD`（默认 1800）
- `BOLL9_TH_1D_MA_SPREAD`（默认 2900）

---

## 8. 打包给别人怎么做（重点）
### 8.1 最稳妥的“最小可运行包”需要包含哪些目录？
因为 `real_trading.py` 只用到了公共库 `common_core` 的**两个小工具**：
- 行情 WebSocket 管理器（负责“电话不断线”接收 1m K 线推送）
- `.env` 加载器（负责读取 `.env.local`，把内容填进系统环境变量）

所以真正需要的最小文件集合是：

1) 策略本体（整个目录保留即可）
- `Quant_Unified/策略仓库/九号布林策略/`

2) 公共底座（只要这 5 个文件，其他都不需要）
- `Quant_Unified/基础库/common_core/__init__.py`
- `Quant_Unified/基础库/common_core/exchange/__init__.py`
- `Quant_Unified/基础库/common_core/exchange/binance_ws_manager.py`
- `Quant_Unified/基础库/common_core/utils/__init__.py`
- `Quant_Unified/基础库/common_core/utils/env_kit.py`

并且要保持它们的相对目录结构不变（否则 Python 的 import 会找不到）。

### 8.2 压缩包里 **绝对不要包含** 的文件
- `Quant_Unified/策略仓库/九号布林策略/.env.local`（里面是你的 webhook/可能还有密钥）
- 任何 `.env`（除非你确认里面完全没有密钥）

### 8.3 一条命令打包（会自动排除敏感文件与缓存）
在仓库根目录执行：

```bash
zip -r 九号布林策略_发布包.zip \
  Quant_Unified/策略仓库/九号布林策略 \
  Quant_Unified/基础库/common_core/__init__.py \
  Quant_Unified/基础库/common_core/exchange/__init__.py \
  Quant_Unified/基础库/common_core/exchange/binance_ws_manager.py \
  Quant_Unified/基础库/common_core/utils/__init__.py \
  Quant_Unified/基础库/common_core/utils/env_kit.py \
  -x "**/.env.local" -x "**/.env" -x "**/__pycache__/**" -x "**/*.pyc" -x "**/.DS_Store"
```

发给别人后，对方解压、安装依赖、写自己的 `.env.local`，就能运行。
