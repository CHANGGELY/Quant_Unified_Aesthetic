"""
因子查看器（Factor Viewer）
- 目标：快速查看单个或多个币种的因子值、分布与基本表现，用于因子探索与参数预检。
- 依赖：FactorHub 动态加载因子；config 中的数据路径配置；factors 目录下的因子文件。

使用方法：
    streamlit run tools/tool2_因子查看器.py
"""
import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 移除未使用的 numpy 依赖
# import numpy as np
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

from core.utils.factor_hub import FactorHub
import config as cfg

# ---------------------------------
# 基础设置（侧边栏）
# ---------------------------------
st.set_page_config(page_title="因子查看器", layout="wide")
st.title("因子查看器 (Factor Viewer)")

with st.sidebar:
    st.header("基础设置")
    market = st.selectbox("市场", options=["spot", "swap"], index=1)
    # 简化持仓期为“小时/天”的组合
    hp_unit = st.radio("持仓期单位", options=["小时(H)", "天(D)"], index=0, horizontal=True)
    hp_value = st.number_input("周期长度", value=8, min_value=1, step=1)
    hold_period = f"{int(hp_value)}H" if hp_unit.startswith("小时") else f"{int(hp_value)}D"
    st.caption(f"当前持仓期：{hold_period}")
    data_dir = Path(cfg.swap_path if market == "swap" else cfg.spot_path)
    st.caption(f"数据路径：{data_dir}")

    # 移除横截面相关的扫描上限
    # max_files = st.slider("扫描文件数量上限（用于横截面分析）", min_value=10, max_value=500, value=100, step=10)

    # 数据路径
    data_dir = Path(cfg.swap_path if market == "swap" else cfg.spot_path)
    st.caption(f"数据路径：{data_dir}")

    # 列出可用因子（按文件名）
    try:
        factor_files = [f[:-3] for f in os.listdir("factors") if f.endswith(".py") and f != "__init__.py"]
    except FileNotFoundError:
        factor_files = []
    factor_name = st.selectbox("因子名称（来自 factors 目录）", options=sorted(factor_files))

    # 参数输入（简单版本）
    param = st.number_input("参数（整数或主参数）", value=14, step=1)
    # 多参数遍历开关与输入
    enable_multi_params = st.checkbox("启用多参数遍历", value=False, help="在单因子下同时计算多个参数，例如 range(0,100,10)")
    if enable_multi_params:
        param_mode = st.radio("参数输入方式", options=["区间(range)", "列表"], index=0, horizontal=True)
        if param_mode == "区间(range)":
            range_start = st.number_input("起始(start)", value=0, step=1)
            range_stop = st.number_input("终止(stop，非包含)", value=100, step=1)
            range_step = st.number_input("步长(step)", value=10, step=1, min_value=1)
            params_text = None
        else:
            params_text = st.text_input("参数列表（逗号分隔）", value="0,10,20,30")
            range_start = range_stop = range_step = None
        out_prefix = st.text_input("输出列前缀", value=factor_name, help="多参数模式下的输出列将为 前缀_参数，例如 Rsi_10、Rsi_20")
    else:
        out_col = st.text_input("输出列名（可选）", value=f"{factor_name}_{int(param)}")
    
    # 移除小币种筛选（横截面专用）
    # st.header("小币种筛选（可选）")
    # enable_small_cap = st.checkbox("启用小币种筛选（基于长期成交额均值低分位）", value=False)
    # qv_window_long = st.number_input("长期成交额窗口（小时）", value=1000, step=50)
    # small_cap_pct = st.slider("保留底部百分比", min_value=0.1, max_value=0.9, value=0.4, step=0.1)

    st.header("执行")
    run_single = st.button("计算单币种因子（下方选择币种）")
    # 新增：清空已计算的单币种结果，避免交互后恢复初始状态
    clear_single = st.button("清空结果", help="清除已计算的单币种结果，恢复初始状态")
    if clear_single:
        for k in ["single_df", "single_factor_cols", "single_symbol_file", "single_factor_name"]:
            st.session_state.pop(k, None)
    # 已取消横截面计算按钮

# ---------------------------------
# 工具函数
# ---------------------------------
@st.cache_data(show_spinner=False)
def list_symbol_files(dir_path: Path):
    if not dir_path.exists():
        return []
    files = [p for p in dir_path.glob("*.csv")]
    return files

@st.cache_data(show_spinner=False)
def load_symbol_df(csv_path: Path):
    encodings = ["utf-8", "utf-8-sig", "gbk", "cp1252", "latin1"]
    seps = [",", ";", "\t", None]
    last_err = None
    for enc in encodings:
        for sep in seps:
            try:
                kwargs = dict(encoding=enc, on_bad_lines="skip")
                if sep is None:
                    # 需要 python 引擎做分隔符自动检测
                    kwargs["sep"] = None
                    kwargs["engine"] = "python"
                    df = pd.read_csv(csv_path, **kwargs)
                else:
                    kwargs["sep"] = sep
                    df = pd.read_csv(csv_path, **kwargs)
                # 规范列名到小写，去除空格
                df.columns = [str(c).strip().lower() for c in df.columns]

                # 若检测到非标准首行（如免责声明），尝试跳过前几行后再读
                suspicious_tokens = ["本数据供", "邢不行", "策略分享会专用", "微信"]
                if (len(df.columns) == 1) or any(tok in "".join(df.columns) for tok in suspicious_tokens):
                    for skip in [1, 2, 3]:
                        try:
                            df2 = pd.read_csv(csv_path, **kwargs, skiprows=skip)
                            df2.columns = [str(c).strip().lower() for c in df2.columns]
                            # 常见中文列名映射到标准英文（精确匹配）
                            colmap_exact = {
                                "收盘": "close", "收盘价": "close",
                                "开盘": "open", "开盘价": "open",
                                "最高": "high", "最高价": "high",
                                "最低": "low", "最低价": "low",
                                "成交量": "volume", "成交额": "quote_volume",
                                "时间": "candle_begin_time"
                            }
                            rename_map = {c: colmap_exact[c] for c in df2.columns if c in colmap_exact}
                            if rename_map:
                                df2 = df2.rename(columns=rename_map)
                            # 模糊匹配补充
                            def fuzzy_rename(df_cols, std, keywords):
                                if std in df2.columns:
                                    return
                                for c in df_cols:
                                    lc = str(c).lower()
                                    if any(k in lc for k in keywords):
                                        df2.rename(columns={c: std}, inplace=True)
                                        break
                            fuzzy_rename(df2.columns, "close", ["close", "closing", "last", "收盘"])  
                            fuzzy_rename(df2.columns, "open", ["open", "opening", "开盘"])      
                            fuzzy_rename(df2.columns, "high", ["high", "最高"])                 
                            fuzzy_rename(df2.columns, "low", ["low", "最低"])                   
                            fuzzy_rename(df2.columns, "volume", ["volume", "vol", "成交量"])   
                            fuzzy_rename(df2.columns, "quote_volume", ["quote_volume", "turnover", "amount", "quotevol", "quote_vol", "成交额"]) 
                            fuzzy_rename(df2.columns, "candle_begin_time", ["time", "timestamp", "date", "datetime", "时间"]) 
                            # 若已找到常见价格列，则采用 df2
                            if any(c in df2.columns for c in ["close", "open", "high", "low"]):
                                df = df2
                                st.caption(f"检测到非标准首行，已自动跳过前 {skip} 行作为标题以继续解析")
                                break
                        except Exception:
                            pass

                # 常见中文列名映射到标准英文（精确匹配）
                colmap_exact = {
                    "收盘": "close", "收盘价": "close",
                    "开盘": "open", "开盘价": "open",
                    "最高": "high", "最高价": "high",
                    "最低": "low", "最低价": "low",
                    "成交量": "volume", "成交额": "quote_volume",
                    "时间": "candle_begin_time"
                }
                rename_map = {c: colmap_exact[c] for c in df.columns if c in colmap_exact}
                if rename_map:
                    df = df.rename(columns=rename_map)
                # 模糊匹配：若标准列仍缺失，则按关键词猜测并重命名
                def fuzzy_rename(df_cols, std, keywords):
                    if std in df.columns:
                        return
                    for c in df_cols:
                        lc = str(c).lower()
                        if any(k in lc for k in keywords):
                            df.rename(columns={c: std}, inplace=True)
                            break
                fuzzy_rename(df.columns, "close", ["close", "closing", "last", "收盘"])  
                fuzzy_rename(df.columns, "open", ["open", "opening", "开盘"])      
                fuzzy_rename(df.columns, "high", ["high", "最高"])                 
                fuzzy_rename(df.columns, "low", ["low", "最低"])                   
                fuzzy_rename(df.columns, "volume", ["volume", "vol", "成交量"])   
                fuzzy_rename(df.columns, "quote_volume", ["quote_volume", "turnover", "amount", "quotevol", "quote_vol", "成交额"]) 
                fuzzy_rename(df.columns, "candle_begin_time", ["time", "timestamp", "date", "datetime", "时间"]) 

                st.caption(f"已加载 {csv_path.name}，编码={enc}，分隔符={'自动' if sep is None else repr(sep)}；列名={list(df.columns)[:8]}...")
                return df
            except Exception as e:
                last_err = e
                continue
    st.warning(f"读取失败：{csv_path.name}，尝试编码 {encodings} 与分隔符 {seps} 皆失败。最后错误：{last_err}")
    return pd.DataFrame()

def ensure_required_cols(df: pd.DataFrame, cols: list[str]) -> bool:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        st.error(f"缺少必要列：{missing}，请检查数据或选择其他币种")
        st.caption("当前列名：")
        try:
            st.code(str(list(df.columns)))
        except Exception:
            pass
        return False
    return True

# 新增：将小时K线转化为日线（按持仓期单位）
def trans_period_for_day(df: pd.DataFrame, date_col: str = 'candle_begin_time') -> pd.DataFrame:
    """
    将单币种小时K线重采样为日线K线；只聚合存在的列，避免缺列报错
    """
    if date_col not in df.columns:
        return df
    df = df.copy()
    # 标准化时间列
    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
    df = df.dropna(subset=[date_col])
    if df.empty:
        return df
    df = df.set_index(date_col)
    agg_dict = {}
    if 'open' in df.columns:
        agg_dict['open'] = 'first'
    if 'high' in df.columns:
        agg_dict['high'] = 'max'
    if 'low' in df.columns:
        agg_dict['low'] = 'min'
    if 'close' in df.columns:
        agg_dict['close'] = 'last'
    if 'volume' in df.columns:
        agg_dict['volume'] = 'sum'
    if 'quote_volume' in df.columns:
        agg_dict['quote_volume'] = 'sum'
    # 其他列使用最后值，尽量保留信息（如 symbol）
    for col in df.columns:
        if col not in agg_dict:
            agg_dict[col] = 'last'
    df = df.resample('1D').agg(agg_dict)
    df = df.reset_index()
    return df

# ---------------------------------
# 币种选择与数据加载
# ---------------------------------
symbol_files = list_symbol_files(data_dir)
if not symbol_files:
    st.warning("数据目录下未找到 CSV 文件，请检查 config 中的路径设置或数据准备流程。")
else:
    # 币种选择（单）
    colL = st.columns([1])[0]
    with colL:
        symbol_file = st.selectbox("选择单个币种文件（用于单币种查看）", options=symbol_files, format_func=lambda p: p.name)
    # 已取消多币种选择（横截面对比）
    # 已取消多币种选择（横截面对比）

# ---------------------------------
# 单币种因子查看（含时间筛选与改进图表）
# ---------------------------------
if run_single and symbol_files:
    df = load_symbol_df(symbol_file)
    # 常见列检测
    required_cols = ["close"]
    # 某些因子需要高低价（如 Cci）
    if factor_name.lower() in {"cci", "cci.py", "cci"} or factor_name == "Cci":
        required_cols = ["high", "low", "close"]
    if not ensure_required_cols(df, required_cols):
        st.stop()

    # 新增：根据持仓期单位决定因子计算的K线频率（D=日线则重采样）
    time_candidates = ["candle_begin_time", "time", "timestamp", "date", "datetime"]
    time_col_pre = next((c for c in time_candidates if c in df.columns), None)
    if time_col_pre:
        df[time_col_pre] = pd.to_datetime(df[time_col_pre], errors="coerce")
        if df[time_col_pre].notna().sum() == 0:
            time_col_pre = None
    if time_col_pre and ('D' in hold_period):
        # 标准化为 candle_begin_time
        if time_col_pre != 'candle_begin_time':
            df = df.rename(columns={time_col_pre: 'candle_begin_time'})
            time_col_pre = 'candle_begin_time'
        df = trans_period_for_day(df, date_col='candle_begin_time')
        st.caption("已按持仓期单位(D)将小时K线聚合为日线进行因子计算")
    elif ('D' in hold_period) and (time_col_pre is None):
        st.warning("未检测到时间列，无法按日线重采样。已按原始频率计算因子")

    # 计算因子（支持多参数）
    try:
        factor = FactorHub.get_by_name(factor_name)
    except ValueError as e:
        st.error(f"因子加载失败：{e}")
        st.stop()

    factor_cols = []
    try:
        if 'enable_multi_params' in globals() and enable_multi_params:
            # 构造参数列表
            param_list = []
            if 'param_mode' in globals() and param_mode == "区间(range)":
                try:
                    start_i = int(range_start)
                    stop_i = int(range_stop)
                    step_i = int(range_step)
                    if step_i <= 0:
                        st.error("步长(step)必须为正整数")
                        st.stop()
                    param_list = list(range(start_i, stop_i, step_i))
                except Exception:
                    st.error("区间参数解析失败，请检查起始/终止/步长输入")
                    st.stop()
            else:
                # 列表解析
                try:
                    raw = (params_text or "").replace("，", ",")
                    param_list = [int(x.strip()) for x in raw.split(",") if x.strip() != ""]
                except Exception:
                    st.error("参数列表解析失败，请使用逗号分隔的整数，如：10,20,30")
                    st.stop()
            if not param_list:
                st.error("参数列表为空，请输入有效的参数范围或列表")
                st.stop()
            # 逐参数计算并追加列
            for p in param_list:
                colname = f"{out_prefix}_{int(p)}"
                try:
                    df = factor.signal(df, int(p), colname)
                    factor_cols.append(colname)
                except Exception as e:
                    st.warning(f"参数 {p} 计算失败：{e}")
        else:
            # 单参数计算
            df = factor.signal(df, int(param), out_col)
            factor_cols = [out_col]
    except Exception as e:
        st.error(f"因子计算异常：{e}")
        st.stop()

    # 将结果持久化到 session_state，避免交互导致页面重置后丢失
    st.session_state["single_df"] = df
    st.session_state["single_factor_cols"] = factor_cols
    st.session_state["single_symbol_file"] = symbol_file
    st.session_state["single_factor_name"] = factor_name

    # 时间列识别与转换
    time_candidates = ["candle_begin_time", "time", "timestamp", "date", "datetime"]
    time_col = next((c for c in time_candidates if c in df.columns), None)
    if time_col:
        # 先将整列统一转换为 pandas datetime
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
        # 如存在全 NaT，则不使用时间列并降级为按最近N行
        if df[time_col].notna().sum() == 0:
            time_col = None
        else:
            st.markdown("**时间筛选**：选择需要观察的时间范围")
            # 取 pandas.Timestamp 的最小/最大，并转为 Python datetime 供 slider 使用
            min_ts = df[time_col].min()
            max_ts = df[time_col].max()
            min_dt = (min_ts.to_pydatetime() if pd.notna(min_ts) else None)
            max_dt = (max_ts.to_pydatetime() if pd.notna(max_ts) else None)
            if min_dt is None or max_dt is None:
                st.warning("时间列解析失败，已切换为按最近N行显示。")
                n_max = int(min(5000, len(df)))
                n_rows = st.slider("显示最近N行", min_value=100, max_value=max(n_max, 100), value=min(500, n_max), step=50)
                df_disp = df.tail(n_rows).copy()
            else:
                default_start = max_dt - timedelta(days=30)
                if default_start < min_dt:
                    default_start = min_dt
                start_end = st.slider("时间范围", min_value=min_dt, max_value=max_dt, value=(default_start, max_dt))
                mask = (df[time_col] >= start_end[0]) & (df[time_col] <= start_end[1])
                df_disp = df.loc[mask].copy()
    if not time_col:
        st.markdown("**显示范围**：按行数选择最近数据")
        n_max = int(min(5000, len(df)))
        n_rows = st.slider("显示最近N行", min_value=100, max_value=max(n_max, 100), value=min(500, n_max), step=50)
        df_disp = df.tail(n_rows).copy()

    st.subheader("单币种因子视图")
    st.caption(f"文件：{symbol_file.name}；因子：{factor_name}")

    # 选择要展示的因子列
    factor_cols_present = [c for c in factor_cols if c in df_disp.columns]
    if not factor_cols_present:
        st.warning("没有可展示的因子列，请检查参数设置或数据")
        st.stop()
    selected_factor_cols = st.multiselect("选择展示的因子列", options=factor_cols_present, default=factor_cols_present)

    # 显示数据表
    st.dataframe(df_disp.tail(200), use_container_width=True)

    # 改进图表：时间轴为横轴，叠加多个因子曲线
    try:
        import plotly.graph_objects as go
        fig = go.Figure()
        # K线或收盘线
        if all(col in df_disp.columns for col in ["open", "high", "low", "close"]):
            if time_col:
                fig.add_trace(go.Candlestick(x=df_disp[time_col], open=df_disp["open"], high=df_disp["high"], low=df_disp["low"], close=df_disp["close"], name="K线"))
            else:
                fig.add_trace(go.Candlestick(open=df_disp["open"], high=df_disp["high"], low=df_disp["low"], close=df_disp["close"], name="K线"))
        else:
            if time_col:
                fig.add_trace(go.Scatter(x=df_disp[time_col], y=df_disp["close"], name="close", mode="lines", yaxis="y1"))
            else:
                fig.add_trace(go.Scatter(y=df_disp["close"], name="close", mode="lines", yaxis="y1"))
        # 因子曲线（右轴），支持多列
        for c in selected_factor_cols:
            if time_col:
                fig.add_trace(go.Scatter(x=df_disp[time_col], y=df_disp[c], name=c, mode="lines", yaxis="y2"))
            else:
                fig.add_trace(go.Scatter(y=df_disp[c], name=c, mode="lines", yaxis="y2"))
        fig.update_layout(
            title="价格与因子曲线（时间轴显示）",
            xaxis=dict(title="时间"),
            yaxis=dict(title="价格/收盘"),
            yaxis2=dict(title=(selected_factor_cols[0] if len(selected_factor_cols)==1 else "因子值"), overlaying="y", side="right")
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception:
        # Fallback：使用 Streamlit 原生图，若存在时间列则设为索引
        df_plot = df_disp[["close"] + selected_factor_cols].copy()
        if time_col and time_col in df_disp.columns:
            df_plot = df_plot.set_index(df_disp[time_col])
        st.line_chart(df_plot.tail(500))

    # 因子分布（直方图）：选择一个因子列展示
    st.subheader("因子分布（直方图）")
    layout_mode = st.radio("图形布局", options=["堆积到一个图", "分开多个图"], index=0, horizontal=True)
    hist_selected_cols = st.multiselect("选择直方图因子列（按时间轴展示）", options=selected_factor_cols, default=selected_factor_cols)
    if not hist_selected_cols:
        st.warning("请至少选择一个因子列用于直方图展示")
    else:
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
            x_vals = df_disp[time_col] if time_col and time_col in df_disp.columns else None
            if layout_mode == "堆积到一个图":
                fig = go.Figure()
                for c in hist_selected_cols:
                    y_vals = pd.Series(df_disp[c]).fillna(0)
                    if x_vals is not None:
                        fig.add_trace(go.Bar(x=x_vals, y=y_vals, name=c))
                    else:
                        fig.add_trace(go.Bar(y=y_vals, name=c))
                fig.update_layout(barmode="stack", title="因子随时间柱状图（堆积）", xaxis=dict(title=("时间" if x_vals is not None else "样本索引")), yaxis=dict(title="因子值"))
                st.plotly_chart(fig, use_container_width=True)
            else:
                fig = make_subplots(rows=len(hist_selected_cols), cols=1, shared_xaxes=True, subplot_titles=hist_selected_cols)
                for i, c in enumerate(hist_selected_cols, start=1):
                    y_vals = pd.Series(df_disp[c]).fillna(0)
                    if x_vals is not None:
                        fig.add_trace(go.Bar(x=x_vals, y=y_vals, name=c), row=i, col=1)
                    else:
                        fig.add_trace(go.Bar(y=y_vals, name=c), row=i, col=1)
                fig.update_layout(height=max(320, 250*len(hist_selected_cols)), title="因子随时间柱状图（分开多个图）", showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
        except Exception:
            # Fallback：Plotly 不可用时的简化展示
            if layout_mode == "堆积到一个图":
                st.bar_chart(df_disp[hist_selected_cols].tail(200))
            else:
                for c in hist_selected_cols:
                    st.bar_chart(pd.DataFrame({c: pd.Series(df_disp[c]).fillna(0)}).tail(200))

st.write("\n")
st.info("提示：本查看器用于轻量探索。")

# 当不是当前点击计算，但会话中已有结果时，继续展示以避免交互重置
if (not run_single) and ("single_df" in st.session_state) and (st.session_state["single_df"] is not None):
    df = st.session_state["single_df"]
    factor_cols = st.session_state.get("single_factor_cols", [])
    symbol_file = st.session_state.get("single_symbol_file")
    factor_name = st.session_state.get("single_factor_name", "")

    time_candidates = ["candle_begin_time", "time", "timestamp", "date", "datetime"]
    time_col = next((c for c in time_candidates if c in df.columns), None)
    if time_col:
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
        if df[time_col].notna().sum() == 0:
            time_col = None
        else:
            st.markdown("**时间筛选**：选择需要观察的时间范围")
            min_ts = df[time_col].min()
            max_ts = df[time_col].max()
            min_dt = (min_ts.to_pydatetime() if pd.notna(min_ts) else None)
            max_dt = (max_ts.to_pydatetime() if pd.notna(max_ts) else None)
            if min_dt is None or max_dt is None:
                st.warning("时间列解析失败，已切换为按最近N行显示。")
                n_max = int(min(5000, len(df)))
                n_rows = st.slider("显示最近N行", min_value=100, max_value=max(n_max, 100), value=min(500, n_max), step=50)
                df_disp = df.tail(n_rows).copy()
            else:
                default_start = max_dt - timedelta(days=30)
                if default_start < min_dt:
                    default_start = min_dt
                start_end = st.slider("时间范围", min_value=min_dt, max_value=max_dt, value=(default_start, max_dt))
                mask = (df[time_col] >= start_end[0]) & (df[time_col] <= start_end[1])
                df_disp = df.loc[mask].copy()
    if not time_col:
        st.markdown("**显示范围**：按行数选择最近数据")
        n_max = int(min(5000, len(df)))
        n_rows = st.slider("显示最近N行", min_value=100, max_value=max(n_max, 100), value=min(500, n_max), step=50)
        df_disp = df.tail(n_rows).copy()

    st.subheader("单币种因子视图")
    if symbol_file is not None:
        from pathlib import Path as _P
        st.caption(f"文件：{_P(symbol_file).name if hasattr(symbol_file,'name') else str(symbol_file)}；因子：{factor_name}")

    factor_cols_present = [c for c in factor_cols if c in df_disp.columns]
    if not factor_cols_present:
        st.warning("没有可展示的因子列，请检查参数设置或数据")
    else:
        selected_factor_cols = st.multiselect("选择展示的因子列", options=factor_cols_present, default=factor_cols_present)
        st.dataframe(df_disp.tail(200), use_container_width=True)
        try:
            import plotly.graph_objects as go
            fig = go.Figure()
            if all(col in df_disp.columns for col in ["open", "high", "low", "close"]):
                if time_col:
                    fig.add_trace(go.Candlestick(x=df_disp[time_col], open=df_disp["open"], high=df_disp["high"], low=df_disp["low"], close=df_disp["close"], name="K线"))
                else:
                    fig.add_trace(go.Candlestick(open=df_disp["open"], high=df_disp["high"], low=df_disp["low"], close=df_disp["close"], name="K线"))
            else:
                if time_col:
                    fig.add_trace(go.Scatter(x=df_disp[time_col], y=df_disp["close"], name="close", mode="lines", yaxis="y1"))
                else:
                    fig.add_trace(go.Scatter(y=df_disp["close"], name="close", mode="lines", yaxis="y1"))
            for c in selected_factor_cols:
                if time_col:
                    fig.add_trace(go.Scatter(x=df_disp[time_col], y=df_disp[c], name=c, mode="lines", yaxis="y2"))
                else:
                    fig.add_trace(go.Scatter(y=df_disp[c], name=c, mode="lines", yaxis="y2"))
            fig.update_layout(
                title="价格与因子曲线（时间轴显示）",
                xaxis=dict(title="时间"),
                yaxis=dict(title="价格/收盘"),
                yaxis2=dict(title=(selected_factor_cols[0] if len(selected_factor_cols)==1 else "因子值"), overlaying="y", side="right")
            )
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            df_plot = df_disp[["close"] + selected_factor_cols].copy()
            if time_col and time_col in df_disp.columns:
                df_plot = df_plot.set_index(df_disp[time_col])
            st.line_chart(df_plot.tail(500))

        st.subheader("因子分布（直方图）")
        layout_mode = st.radio("图形布局", options=["堆积到一个图", "分开多个图"], index=0, horizontal=True)
        hist_selected_cols = st.multiselect("选择直方图因子列（按时间轴展示）", options=selected_factor_cols, default=selected_factor_cols)
        if not hist_selected_cols:
            st.warning("请至少选择一个因子列用于直方图展示")
        else:
            try:
                import plotly.graph_objects as go
                from plotly.subplots import make_subplots
                x_vals = df_disp[time_col] if time_col and time_col in df_disp.columns else None
                if layout_mode == "堆积到一个图":
                    fig = go.Figure()
                    for c in hist_selected_cols:
                        y_vals = pd.Series(df_disp[c]).fillna(0)
                        if x_vals is not None:
                            fig.add_trace(go.Bar(x=x_vals, y=y_vals, name=c))
                        else:
                            fig.add_trace(go.Bar(y=y_vals, name=c))
                    fig.update_layout(barmode="stack", title="因子随时间柱状图（堆积）", xaxis=dict(title=("时间" if x_vals is not None else "样本索引")), yaxis=dict(title="因子值"))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    fig = make_subplots(rows=len(hist_selected_cols), cols=1, shared_xaxes=True, subplot_titles=hist_selected_cols)
                    for i, c in enumerate(hist_selected_cols, start=1):
                        y_vals = pd.Series(df_disp[c]).fillna(0)
                        if x_vals is not None:
                            fig.add_trace(go.Bar(x=x_vals, y=y_vals, name=c), row=i, col=1)
                        else:
                            fig.add_trace(go.Bar(y=y_vals, name=c), row=i, col=1)
                    fig.update_layout(height=max(320, 250*len(hist_selected_cols)), title="因子随时间柱状图（分开多个图）", showlegend=False)
                    st.plotly_chart(fig, use_container_width=True)
            except Exception:
                # Fallback：Plotly 不可用时的简化展示
                if layout_mode == "堆积到一个图":
                    st.bar_chart(df_disp[hist_selected_cols].tail(200))
                else:
                    for c in hist_selected_cols:
                        st.bar_chart(pd.DataFrame({c: pd.Series(df_disp[c]).fillna(0)}).tail(200))