## 选币回测框架（开箱即用说明）

这个仓库包含一个「数字货币选币 + 组合回测」的完整流程（数据准备 → 因子计算 → 选币 → 资金曲线模拟），并提供了一组可视化/分析工具（`tools/`），用于快速查看因子、回测结果、参数遍历与参数平原等。

---

## 1. 环境要求

- 操作系统：Windows / macOS / Linux 均可
- Python：建议 `3.10` / `3.11` / `3.12`
  - 原因：项目依赖 `numba`，它对 Python 大版本支持通常滞后，优先用上述版本更稳

---

## 2. 一键安装依赖

本项目已提供 `requirements.txt`（基础必需依赖）。

### 2.1 创建虚拟环境（推荐）

Windows PowerShell：

```powershell
cd "项目根目录"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
```

macOS / Linux：

```bash
cd 项目根目录
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
```

### 2.2 安装基础依赖（必装）

```bash
pip install -r requirements.txt
```

`requirements.txt` 当前包含：
- `pandas` / `numpy`：数据处理
- `tqdm`：进度条
- `numba`：性能加速（首次运行会有编译缓存）
- `plotly`：绘图（HTML/交互图）
- `streamlit`：可视化工具（网页界面）

国内网络可选镜像（可自行替换）：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2.3 建议额外安装（为了“所有工具都能跑”）

部分脚本会写 `xlsx`、或使用额外绘图/机器学习库，建议一起装上：

```bash
pip install openpyxl matplotlib seaborn scikit-learn
```

可选依赖（只在 `tools/tool11_因子AI代码分析.py` 启用联网 AI 分析时需要）：

```bash
pip install requests
```

---

## 3. 你需要准备什么数据？

框架的输入是「按币种拆分的 1 小时 K 线 CSV 文件」，文件名形如：

- `BTC-USDT.csv`
- `ETH-USDT.csv`
- `1000BONK-USDT.csv`

并放在你自己电脑的某个目录下（现货与合约分别一个目录）。项目会在该目录下递归搜索 `*-USDT.csv`。

### 3.1 CSV 字段要求（建议）

`program/step1_prepare_data.py` 在读取时使用：
- `pd.read_csv(..., encoding='gbk', parse_dates=['candle_begin_time'], skiprows=1)`

因此你的 CSV 最好满足：
- 编码：`GBK`（如果你的数据是 `utf-8`，把脚本里的 `encoding='gbk'` 改成 `utf-8` 即可）
- 第一行：可有一行无关内容（因为 `skiprows=1` 会跳过第一行）；如果你的 CSV 没有“额外首行”，把 `skiprows=1` 改成 `skiprows=0`
- 至少包含这些列（越全越好）：
  - `candle_begin_time`（时间戳，1 小时粒度）
  - `symbol`
  - `open` / `high` / `low` / `close`
  - `volume` / `quote_volume` / `trade_num`
  - `taker_buy_base_asset_volume` / `taker_buy_quote_asset_volume`
  - `avg_price_1m` / `avg_price_5m`（用于更贴近真实换仓价格的模拟）
- 合约数据建议额外包含：
  - `fundingRate`（资金费率）

---

## 4. 配置你的本地路径与策略参数

核心配置在 `config.py`：

- 数据目录（务必改成你自己的路径）：
  - `spot_path`：现货 1h K 线 CSV 根目录
  - `swap_path`：合约 1h K 线 CSV 根目录
- 回测时间：
  - `start_date` / `end_date`
- 策略参数：
  - `strategy` 字典（持仓周期、市场类型、多空数量、因子与过滤因子等）
- 结果输出目录：
  - 默认输出到 `data/回测结果/<backtest_name>/...`

注意：`config.py` 里当前示例路径是作者本机的 `F:\...`，你在新电脑上必须改成可用路径，否则会直接退出。

---

## 5. 跑一次完整回测（主程序）

在项目根目录运行：

```bash
python backtest.py
```

首次运行会做：
- 数据准备：读取 CSV、补齐小时序列、生成 `data/candle_data_dict.pkl`、`data/market_pivot_*.pkl` 等
- 因子计算：在 `data/cache/` 写入缓存
- 选币：聚合选币结果
- 模拟资金曲线：生成各类结果文件（csv/html 等）

回测结果一般会出现在：
- `data/回测结果/`
- `data/遍历结果/`（做参数遍历时）
- `data/分析结果/`（一些对比/相似度工具会写这里）

---

## 6. tools/ 工具怎么用？

工具分两类：

1) 直接运行（命令行输出 + 生成文件）
- `python tools/tool1_因子分析.py`
- `python tools/tool5_选币相似度.py`
- `python tools/tool6_资金曲线涨跌幅对比.py`
- `python tools/tool7_多策略选币相似度与资金曲线涨跌幅对比.py`
- `python tools/tool8_参数遍历与参数平原图.py`
- `python tools/tool10_pkl转csv.py`

2) Streamlit 网页工具（推荐在浏览器里交互）

在项目根目录运行：

```bash
streamlit run tools/tool2_因子查看器.py
streamlit run tools/tool3_因子分析查看器.py
streamlit run tools/tool4_策略查看器.py
streamlit run tools/tool9_参数平原全能可视化.py
streamlit run tools/tool11_因子AI代码分析.py
```

常见习惯：
- 先跑 `python backtest.py` 得到回测/遍历结果，再用这些工具做可视化分析
- 如果 Streamlit 端口冲突，可指定端口：

```bash
streamlit run tools/tool4_策略查看器.py --server.port 8502
```

### 6.1 tool11（因子 AI 代码分析）可选联网配置

不配置任何 API 时，也能使用“静态规则”检查（未来函数/标签风险等）。

若要开启联网 AI（可选），按脚本内说明配置环境变量后运行：

Windows PowerShell 示例：

```powershell
$env:DEEPSEEK_API_KEY="你的密钥"
$env:DEEPSEEK_BASE_URL="https://api.deepseek.com/v1"
$env:DEEPSEEK_MODEL="deepseek-chat"
streamlit run tools/tool11_因子AI代码分析.py
```

---

## 7. 常见问题（新电脑最容易踩坑的点）

- 读 CSV 报编码错误：把 `program/step1_prepare_data.py` 里的 `encoding='gbk'` 改成 `utf-8`
- 读 CSV 报列缺失：确认 `candle_begin_time` 列存在且能被解析为时间；字段名要与脚本一致
- CSV 第一行不符合预期：如果你的 CSV 没有“多余首行”，把 `skiprows=1` 改成 `skiprows=0`
- Streamlit 提示找不到模块：确保在“项目根目录”运行 `streamlit run ...`，并且已经 `pip install -r requirements.txt`
- 写 `xlsx` 报错：安装 `openpyxl`（见上面的“建议额外安装”）
- 某些因子选择后报 `sklearn` 缺失：安装 `scikit-learn`（见上面的“建议额外安装”）
