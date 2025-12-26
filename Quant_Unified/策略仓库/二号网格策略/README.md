项目说明：这是一个基于 Binance 期货K线数据的网格策略回测框架，帮助你在上线实盘前量化评估在过去若干小时内的最大盈利、最大回撤、已配对与未配对盈亏、每格下单数量与配对次数等关键指标。

**项目简介**
- 目标：用真实历史K线重放价格轨迹，严格按网格机器人规则模拟挂单、触网与配对，评估风险与收益。
- 特点：支持等差与等比两种网格间隔；计算每格下单量；统计最大盈利、最大亏损、配对次数与收益。
- 数据：直接从交易所获取真实K线数据，不使用任何模拟数据。

**核心思想**
- 在当前价格的上一档挂空单，在下一档挂多单；价格触及即成交并更新持仓网格数。
- 通过 `positions_grids` 记录净持仓格数；当触网后净持仓从正到非正或从负到非负，视为完成一次配对并累计配对收益。
- 通过重放每根K线的真实运行路径（开→高/低→收）逐步推进账户状态。

**关键数据结构**
- `grid_dict`：网格参数，含 `interval`、`price_central`、`one_grid_quantity`、`max_price`、`min_price`。
- `account_dict`：账户状态，含 `positions_grids`、`pairing_count`、`pair_profit`、`positions_cost`、`positions_profit`、`up_price`、`down_price`。
- `Interval_mode`：`AS` 等差间隔；`GS` 等比间隔。

**价格轨迹模拟**
- 阳线：`curr_price -> open -> low -> high -> close`。
- 阴线：`curr_price -> open -> high -> low -> close`。
- 每一步调用 `update_price(ts, new_price)`，若价格跨过 `up_price` 或 `down_price` 则触网并触发 `update_order(ts, price, side)`。

**回测流程**
- 调用 `fetch_candle_data(symbol, end_time, '1m', num_kline)` 拉取过去 `num_hours` 小时的 1 分钟K线。
- 设定 `curr_price = df['open'].iloc[0]`，初始化网格参数与账户状态。
- 逐根K线按轨迹推进，记录持仓、配对与盈利；统计最大盈利与最大亏损。

**参数说明**
- `money`：初始投入资金（USDT）。
- `leverage`：杠杆倍数，用于计算每格下单量。
- `symbol`：交易对（如 `TRBUSDT`）。
- `interval_mode`：`AS` 等差；`GS` 等比。
- `num_hours`：回测时长（小时，支持小数如 `12.5`）。
- `end_time`：回测终点时间（北京时间，精确到分钟）。
- `num_steps`：网格总数量。
- `min_price` / `max_price`：网格上下界。
- `price_range`：可选，按现价的相对区间生成上下界（设定后覆盖 `min_price/max_price`）。

**输出解读**
- `最大盈利` / `最大亏损`：回测期间组合的最大浮盈与最大回撤。
- `每笔数量`：单格下单数量，已考虑网格价格序列的加权。
- `已配对次数`：完成的网格配对数量。
- `已配对盈利` / `未配对盈利` / `总盈利`：对应配对部分、未配对持仓部分与合计的收益及收益率。
- 注：未计入手续费、价格精度与最小下单量，实盘盈利会略低于回测估算。

**局限与注意事项**
- 分辨率限制：使用 1 分钟K线；若同一分钟内价格多次触网，K线无法还原全部细节，密集网格的误差会增大，稀疏网格更准确。
- 交易细则：未在回测中处理手续费、最小下单金额与价格/数量精度，请在实盘模块落地时纳入。
- 网络代理：`api/binance.py` 默认设置了 `https_proxy = 'http://127.0.0.1:7897/'`；无代理可注释或删除该行。

**环境依赖**
- Python 3.9+。
- 依赖库：`ccxt`、`pandas`、`tqdm`、`pytz`。
- 安装：`pip install ccxt pandas tqdm pytz`。

**目录结构**
- `api/binance.py`：交易所接口封装，拉取账户、持仓、K线与行情。
- `common/utils.py`：通用工具，含重试封装与时间计算。
- `grid/grid_backtest.py`：核心回测逻辑与示例参数。

**快速开始**
- 安装依赖：`pip install ccxt pandas tqdm pytz`。
- 如需代理，在 `api/binance.py` 配置 `exchange.https_proxy`；公共K线无需 API Key。
- 根据你的币对与网格参数修改 `grid/grid_backtest.py` 中的示例字段：`money`、`leverage`、`symbol`、`interval_mode`、`num_hours`、`end_time`、`num_steps`、`min_price`、`max_price` 或 `price_range`。
- 运行回测：`python -X utf8 grid/grid_backtest.py`。

**参数示例**
- `money = 1163.88`
- `leverage = 10`
- `symbol = 'TRBUSDT'`
- `interval_mode = Interval_mode.GS`
- `num_hours = 12`
- `end_time = timezone('Asia/Shanghai').localize(datetime(2023, 11, 5, 10, 48))`
- `num_steps = 64`
- `min_price = 72.847`
- `max_price = 151.299`

**实践建议**
- 网格密度：尽量选择分钟级难以多次触网的稀疏网格，提高回测与实盘的一致性。
- 风险评估：重点关注 `最大亏损` 与 `总盈利` 的波动区间，结合自身止损容忍度设置上下界与间隔模式。
- 实盘集成：在下单模块中纳入手续费与精度规则，并引入最小下单金额与精度校验（`api/binance.py` 已提供相关信息接口）。

**常见问题**
- 无法联网或超时：检查代理设置；必要时关闭 `https_proxy` 并直接访问。
- 回测结果与实盘不一致：考虑手续费与精度；密集网格在 1 分钟K线下误差更大。
- 价格区间设置：可用 `price_range` 按现价的百分比生成上下界，或手动指定 `min_price/max_price`。
