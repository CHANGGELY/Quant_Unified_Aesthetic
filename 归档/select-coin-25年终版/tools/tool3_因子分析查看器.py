# -*- coding: utf-8 -*-
"""
因子分析与查看工具
结合批量因子分组分析和单币种因子查看

使用方法：
    streamlit run tools/tool3_因子分析查看器.py
"""
from pathlib import Path
import os
import sys
from datetime import datetime, timedelta
import warnings
import ast

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import tools.utils.pfunctions as pf
import tools.utils.tfunctions as tf
from core.model.strategy_config import FilterFactorConfig, filter_common
from core.utils.path_kit import get_file_path, get_folder_path
from core.utils.factor_hub import FactorHub
import config as cfg


warnings.filterwarnings("ignore")


def list_symbol_files(dir_path: Path):
    if not dir_path.exists():
        return []
    return [p for p in dir_path.glob("*.csv")]


def load_symbol_df(csv_path: Path):
    encodings = ["utf-8", "utf-8-sig", "gbk", "cp1252", "latin1"]
    seps = [",", ";", "\t", None]
    last_err = None
    for enc in encodings:
        for sep in seps:
            try:
                kwargs = dict(encoding=enc, on_bad_lines="skip")
                if sep is None:
                    kwargs["sep"] = None
                    kwargs["engine"] = "python"
                    df = pd.read_csv(csv_path, **kwargs)
                else:
                    kwargs["sep"] = sep
                    df = pd.read_csv(csv_path, **kwargs)
                df.columns = [str(c).strip().lower() for c in df.columns]

                suspicious_tokens = ["本数据供", "邢不行", "策略分享会专用", "微信"]
                if (len(df.columns) == 1) or any(tok in "".join(df.columns) for tok in suspicious_tokens):
                    for skip in [1, 2, 3]:
                        try:
                            df2 = pd.read_csv(csv_path, **kwargs, skiprows=skip)
                            df2.columns = [str(c).strip().lower() for c in df2.columns]
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
                            if any(c in df2.columns for c in ["close", "open", "high", "low"]):
                                df = df2
                                st.caption(f"检测到非标准首行，已自动跳过前 {skip} 行作为标题以继续解析")
                                break
                        except Exception:
                            pass

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


def trans_period_for_day(df: pd.DataFrame, date_col: str = "candle_begin_time") -> pd.DataFrame:
    if date_col not in df.columns:
        return df
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col])
    if df.empty:
        return df
    df = df.set_index(date_col)
    agg_dict = {}
    if "open" in df.columns:
        agg_dict["open"] = "first"
    if "high" in df.columns:
        agg_dict["high"] = "max"
    if "low" in df.columns:
        agg_dict["low"] = "min"
    if "close" in df.columns:
        agg_dict["close"] = "last"
    if "volume" in df.columns:
        agg_dict["volume"] = "sum"
    if "quote_volume" in df.columns:
        agg_dict["quote_volume"] = "sum"
    for col in df.columns:
        if col not in agg_dict:
            agg_dict[col] = "last"
    df = df.resample("1D").agg(agg_dict)
    df = df.reset_index()
    return df


def factor_viewer_page(market: str, hold_period: str, data_dir: Path, factor_name: str, param: int,
                       enable_multi_params: bool, param_mode: str, range_start, range_stop, range_step,
                       params_text: str, out_prefix: str, out_col: str, run_single: bool):
    symbol_files = list_symbol_files(data_dir)
    if not symbol_files:
        st.warning("数据目录下未找到 CSV 文件，请检查 config 中的路径设置或数据准备流程。")
    else:
        colL = st.columns([1])[0]
        with colL:
            symbol_file = st.selectbox("选择单个币种文件（用于单币种查看）", options=symbol_files, format_func=lambda p: p.name)

    if run_single and symbol_files:
        df = load_symbol_df(symbol_file)
        required_cols = ["close"]
        if factor_name.lower() in {"cci", "cci.py", "cci"} or factor_name == "Cci":
            required_cols = ["high", "low", "close"]
        if not ensure_required_cols(df, required_cols):
            st.stop()

        time_candidates = ["candle_begin_time", "time", "timestamp", "date", "datetime"]
        time_col_pre = next((c for c in time_candidates if c in df.columns), None)
        if time_col_pre:
            df[time_col_pre] = pd.to_datetime(df[time_col_pre], errors="coerce")
            if df[time_col_pre].notna().sum() == 0:
                time_col_pre = None
        if time_col_pre and ("D" in hold_period):
            if time_col_pre != "candle_begin_time":
                df = df.rename(columns={time_col_pre: "candle_begin_time"})
                time_col_pre = "candle_begin_time"
            df = trans_period_for_day(df, date_col="candle_begin_time")
            st.caption("已按持仓期单位(D)将小时K线聚合为日线进行因子计算")
        elif ("D" in hold_period) and (time_col_pre is None):
            st.warning("未检测到时间列，无法按日线重采样。已按原始频率计算因子")

        try:
            factor = FactorHub.get_by_name(factor_name)
        except ValueError as e:
            st.error(f"因子加载失败：{e}")
            st.stop()

        factor_cols = []
        try:
            if enable_multi_params:
                param_list = []
                if param_mode == "区间(range)":
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
                    try:
                        raw = (params_text or "").replace("，", ",")
                        param_list = [int(x.strip()) for x in raw.split(",") if x.strip() != ""]
                    except Exception:
                        st.error("参数列表解析失败，请使用逗号分隔的整数，如：10,20,30")
                        st.stop()
                if not param_list:
                    st.error("参数列表为空，请输入有效的参数范围或列表")
                    st.stop()
                for p in param_list:
                    colname = f"{out_prefix}_{int(p)}"
                    try:
                        df = factor.signal(df, int(p), colname)
                        factor_cols.append(colname)
                    except Exception as e:
                        st.warning(f"参数 {p} 计算失败：{e}")
            else:
                df = factor.signal(df, int(param), out_col)
                factor_cols = [out_col]
        except Exception as e:
            st.error(f"因子计算异常：{e}")
            st.stop()

        st.session_state["single_df"] = df
        st.session_state["single_factor_cols"] = factor_cols
        st.session_state["single_symbol_file"] = symbol_file
        st.session_state["single_factor_name"] = factor_name

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
                min_dt = min_ts.to_pydatetime() if pd.notna(min_ts) else None
                max_dt = max_ts.to_pydatetime() if pd.notna(max_ts) else None
                if min_dt is None or max_dt is None:
                    st.warning("时间列解析失败，已切换为按最近N行显示。")
                    n_max = int(min(5000, len(df)))
                    n_rows = st.slider("显示最近N行", min_value=100, max_value=max(n_max, 100),
                                       value=min(500, n_max), step=50)
                    df_disp = df.tail(n_rows).copy()
                else:
                    default_start = max_dt - timedelta(days=30)
                    if default_start < min_dt:
                        default_start = min_dt
                    start_end = st.slider("时间范围", min_value=min_dt, max_value=max_dt,
                                          value=(default_start, max_dt))
                    mask = (df[time_col] >= start_end[0]) & (df[time_col] <= start_end[1])
                    df_disp = df.loc[mask].copy()
        if not time_col:
            st.markdown("**显示范围**：按行数选择最近数据")
            n_max = int(min(5000, len(df)))
            n_rows = st.slider("显示最近N行", min_value=100, max_value=max(n_max, 100),
                               value=min(500, n_max), step=50)
            df_disp = df.tail(n_rows).copy()

        st.subheader("单币种因子视图")
        st.caption(f"文件：{symbol_file.name}；因子：{factor_name}")

        factor_cols_present = [c for c in factor_cols if c in df_disp.columns]
        if not factor_cols_present:
            st.warning("没有可展示的因子列，请检查参数设置或数据")
            st.stop()
        selected_factor_cols = st.multiselect("选择展示的因子列", options=factor_cols_present,
                                              default=factor_cols_present)

        st.dataframe(df_disp.tail(200), use_container_width=True)

        try:
            import plotly.graph_objects as go

            fig = go.Figure()
            if all(col in df_disp.columns for col in ["open", "high", "low", "close"]):
                if time_col:
                    fig.add_trace(go.Candlestick(x=df_disp[time_col], open=df_disp["open"],
                                                 high=df_disp["high"], low=df_disp["low"],
                                                 close=df_disp["close"], name="K线"))
                else:
                    fig.add_trace(go.Candlestick(open=df_disp["open"], high=df_disp["high"],
                                                 low=df_disp["low"], close=df_disp["close"],
                                                 name="K线"))
            else:
                if time_col:
                    fig.add_trace(go.Scatter(x=df_disp[time_col], y=df_disp["close"], name="close",
                                             mode="lines", yaxis="y1"))
                else:
                    fig.add_trace(go.Scatter(y=df_disp["close"], name="close",
                                             mode="lines", yaxis="y1"))
            for c in selected_factor_cols:
                if time_col:
                    fig.add_trace(go.Scatter(x=df_disp[time_col], y=df_disp[c], name=c,
                                             mode="lines", yaxis="y2"))
                else:
                    fig.add_trace(go.Scatter(y=df_disp[c], name=c, mode="lines", yaxis="y2"))
            fig.update_layout(
                title="价格与因子曲线（时间轴显示）",
                xaxis=dict(title="时间"),
                yaxis=dict(title="价格/收盘"),
                yaxis2=dict(
                    title=(selected_factor_cols[0] if len(selected_factor_cols) == 1 else "因子值"),
                    overlaying="y",
                    side="right",
                ),
            )
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            df_plot = df_disp[["close"] + selected_factor_cols].copy()
            if time_col and time_col in df_disp.columns:
                df_plot = df_plot.set_index(df_disp[time_col])
            st.line_chart(df_plot.tail(500))

        st.subheader("因子分布（直方图）")
        layout_mode = st.radio("图形布局", options=["堆积到一个图", "分开多个图"], index=0, horizontal=True)
        hist_selected_cols = st.multiselect("选择直方图因子列（按时间轴展示）",
                                            options=selected_factor_cols,
                                            default=selected_factor_cols)
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
                    fig.update_layout(
                        barmode="stack",
                        title="因子随时间柱状图（堆积）",
                        xaxis=dict(title=("时间" if x_vals is not None else "样本索引")),
                        yaxis=dict(title="因子值"),
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    fig = make_subplots(rows=len(hist_selected_cols), cols=1, shared_xaxes=True,
                                        subplot_titles=hist_selected_cols)
                    for i, c in enumerate(hist_selected_cols, start=1):
                        y_vals = pd.Series(df_disp[c]).fillna(0)
                        if x_vals is not None:
                            fig.add_trace(go.Bar(x=x_vals, y=y_vals, name=c), row=i, col=1)
                        else:
                            fig.add_trace(go.Bar(y=y_vals, name=c), row=i, col=1)
                    fig.update_layout(
                        height=max(320, 250 * len(hist_selected_cols)),
                        title="因子随时间柱状图（分开多个图）",
                        showlegend=False,
                    )
                    st.plotly_chart(fig, use_container_width=True)
            except Exception:
                if layout_mode == "堆积到一个图":
                    st.bar_chart(df_disp[hist_selected_cols].tail(200))
                else:
                    for c in hist_selected_cols:
                        st.bar_chart(pd.DataFrame({c: pd.Series(df_disp[c]).fillna(0)}).tail(200))

    st.write("\n")
    st.info("提示：本查看器用于轻量探索。")

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
                min_dt = min_ts.to_pydatetime() if pd.notna(min_ts) else None
                max_dt = max_ts.to_pydatetime() if pd.notna(max_ts) else None
                if min_dt is None or max_dt is None:
                    st.warning("时间列解析失败，已切换为按最近N行显示。")
                    n_max = int(min(5000, len(df)))
                    n_rows = st.slider("显示最近N行", min_value=100, max_value=max(n_max, 100),
                                       value=min(500, n_max), step=50)
                    df_disp = df.tail(n_rows).copy()
                else:
                    default_start = max_dt - timedelta(days=30)
                    if default_start < min_dt:
                        default_start = min_dt
                    start_end = st.slider("时间范围", min_value=min_dt, max_value=max_dt,
                                          value=(default_start, max_dt))
                    mask = (df[time_col] >= start_end[0]) & (df[time_col] <= start_end[1])
                    df_disp = df.loc[mask].copy()
        if not time_col:
            st.markdown("**显示范围**：按行数选择最近数据")
            n_max = int(min(5000, len(df)))
            n_rows = st.slider("显示最近N行", min_value=100, max_value=max(n_max, 100),
                               value=min(500, n_max), step=50)
            df_disp = df.tail(n_rows).copy()

        st.subheader("单币种因子视图")
        if symbol_file is not None:
            from pathlib import Path as _P

            st.caption(f"文件：{_P(symbol_file).name if hasattr(symbol_file, 'name') else str(symbol_file)}；因子：{factor_name}")

        factor_cols_present = [c for c in factor_cols if c in df_disp.columns]
        if not factor_cols_present:
            st.warning("没有可展示的因子列，请检查参数设置或数据")
        else:
            selected_factor_cols = st.multiselect("选择展示的因子列", options=factor_cols_present,
                                                  default=factor_cols_present)
            st.dataframe(df_disp.tail(200), use_container_width=True)
            try:
                import plotly.graph_objects as go

                fig = go.Figure()
                if all(col in df_disp.columns for col in ["open", "high", "low", "close"]):
                    if time_col:
                        fig.add_trace(go.Candlestick(x=df_disp[time_col], open=df_disp["open"],
                                                     high=df_disp["high"], low=df_disp["low"],
                                                     close=df_disp["close"], name="K线"))
                    else:
                        fig.add_trace(go.Candlestick(open=df_disp["open"], high=df_disp["high"],
                                                     low=df_disp["low"], close=df_disp["close"],
                                                     name="K线"))
                else:
                    if time_col:
                        fig.add_trace(go.Scatter(x=df_disp[time_col], y=df_disp["close"], name="close",
                                                 mode="lines", yaxis="y1"))
                    else:
                        fig.add_trace(go.Scatter(y=df_disp["close"], name="close",
                                                 mode="lines", yaxis="y1"))
                for c in selected_factor_cols:
                    if time_col:
                        fig.add_trace(go.Scatter(x=df_disp[time_col], y=df_disp[c], name=c,
                                                 mode="lines", yaxis="y2"))
                    else:
                        fig.add_trace(go.Scatter(y=df_disp[c], name=c, mode="lines", yaxis="y2"))
                fig.update_layout(
                    title="价格与因子曲线（时间轴显示）",
                    xaxis=dict(title="时间"),
                    yaxis=dict(title="价格/收盘"),
                    yaxis2=dict(
                        title=(selected_factor_cols[0] if len(selected_factor_cols) == 1 else "因子值"),
                        overlaying="y",
                        side="right",
                    ),
                )
                st.plotly_chart(fig, use_container_width=True)
            except Exception:
                df_plot = df_disp[["close"] + selected_factor_cols].copy()
                if time_col and time_col in df_disp.columns:
                    df_plot = df_plot.set_index(df_disp[time_col])
                st.line_chart(df_plot.tail(500))

            st.subheader("因子分布（直方图）")
            layout_mode = st.radio("图形布局", options=["堆积到一个图", "分开多个图"], index=0, horizontal=True)
            hist_selected_cols = st.multiselect("选择直方图因子列（按时间轴展示）",
                                                options=selected_factor_cols,
                                                default=selected_factor_cols)
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
                        fig.update_layout(
                            barmode="stack",
                            title="因子随时间柱状图（堆积）",
                            xaxis=dict(title=("时间" if x_vals is not None else "样本索引")),
                            yaxis=dict(title="因子值"),
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        fig = make_subplots(rows=len(hist_selected_cols), cols=1, shared_xaxes=True,
                                            subplot_titles=hist_selected_cols)
                        for i, c in enumerate(hist_selected_cols, start=1):
                            y_vals = pd.Series(df_disp[c]).fillna(0)
                            if x_vals is not None:
                                fig.add_trace(go.Bar(x=x_vals, y=y_vals, name=c), row=i, col=1)
                            else:
                                fig.add_trace(go.Bar(y=y_vals, name=c), row=i, col=1)
                        fig.update_layout(
                            height=max(320, 250 * len(hist_selected_cols)),
                            title="因子随时间柱状图（分开多个图）",
                            showlegend=False,
                        )
                        st.plotly_chart(fig, use_container_width=True)
                except Exception:
                    if layout_mode == "堆积到一个图":
                        st.bar_chart(df_disp[hist_selected_cols].tail(200))
                    else:
                        for c in hist_selected_cols:
                            st.bar_chart(pd.DataFrame({c: pd.Series(df_disp[c]).fillna(0)}).tail(200))


def run_factor_analysis_once(factor_dict_info, filter_list_info, mode_info: str, bins: int = 5,
                             enable_ls: bool | None = None):
    st.write("开始进行因子分析...")

    factor_name_list = [
        f"factor_{factor}_{param}"
        for factor, params in factor_dict_info.items()
        for param in params
    ]

    st.write("读取处理后的所有币K线数据...")
    all_factors_kline = pd.read_pickle(get_file_path("data", "cache", "all_factors_df.pkl"))

    for factor_name in factor_name_list:
        st.write(f"读取因子数据：{factor_name}...")
        factor = pd.read_pickle(get_file_path("data", "cache", f"{factor_name}.pkl"))
        if factor.empty:
            st.error(f"{factor_name} 数据为空，请检查因子数据")
            return
        all_factors_kline[factor_name] = factor

    filter_factor_list = [FilterFactorConfig.init(item) for item in filter_list_info] if filter_list_info else []
    for filter_config in filter_factor_list:
        filter_path = get_file_path("data", "cache", f"factor_{filter_config.col_name}.pkl")
        st.write(f"读取过滤因子数据：{filter_config.col_name}...")
        filter_factor = pd.read_pickle(filter_path)
        if filter_factor.empty:
            st.error(f"{filter_config.col_name} 数据为空，请检查因子数据")
            return
        all_factors_kline[filter_config.col_name] = filter_factor

    if mode_info == "spot":
        mode_kline = all_factors_kline[all_factors_kline["is_spot"] == 1]
        if mode_kline.empty:
            st.error("现货数据为空，请检查数据")
            return
    elif mode_info == "swap":
        mode_kline = all_factors_kline[all_factors_kline["is_spot"] == 0]
        if mode_kline.empty:
            st.error("合约数据为空，请检查数据")
            return
    elif mode_info == "spot+swap":
        mode_kline = all_factors_kline
        if mode_kline.empty:
            st.error("现货及合约数据为空，请检查数据")
            return
    else:
        st.error("mode 错误，只能选择 spot / swap / spot+swap")
        return

    if filter_factor_list:
        filter_condition = filter_common(mode_kline, filter_factor_list)
        mode_kline = mode_kline[filter_condition]

    for factor_name in factor_name_list:
        st.write(f"开始绘制因子 {factor_name} 的分箱图和分组净值曲线...")
        group_curve, bar_df, labels = tf.group_analysis(mode_kline, factor_name, bins=bins)
        group_curve = group_curve.resample("D").last()

        is_spot_mode = mode_info in ("spot", "spot+swap")
        if enable_ls is True:
            is_spot_mode = False
        elif enable_ls is False:
            is_spot_mode = True

        if not is_spot_mode:
            labels += ["多空净值"]
        bar_df = bar_df[bar_df["groups"].isin(labels)]
        factor_labels = ["因子值最小"] + [""] * 3 + ["因子值最大"]
        if not is_spot_mode:
            factor_labels.append("")
        bar_df["因子值标识"] = factor_labels

        bar_fig = go.Figure()
        bar_fig.add_trace(
            go.Bar(
                x=bar_df["groups"],
                y=bar_df["asset"],
                text=bar_df["因子值标识"],
                name="分组净值",
            )
        )
        bar_fig.update_layout(
            title="分组净值",
            xaxis_title="分组",
            yaxis_title="资产净值",
        )
        cols_list = [col for col in group_curve.columns if "第" in col]

        y2_cols = []
        if not is_spot_mode:
            for name in ["多空净值", "多头组合净值", "空头组合净值"]:
                if name in group_curve.columns:
                    y2_cols.append(name)
        y2_data = group_curve[y2_cols] if y2_cols else pd.DataFrame()

        line_fig = make_subplots(specs=[[{"secondary_y": not is_spot_mode}]])
        for col in cols_list:
            line_fig.add_trace(
                go.Scatter(
                    x=group_curve.index,
                    y=group_curve[col],
                    name=col,
                ),
                secondary_y=False,
            )
        if not is_spot_mode:
            if "多空净值" in group_curve.columns:
                line_fig.add_trace(
                    go.Scatter(
                        x=group_curve.index,
                        y=group_curve["多空净值"],
                        name="多空净值",
                        line=dict(dash="dot"),
                    ),
                    secondary_y=True,
                )
            if "多头组合净值" in group_curve.columns:
                line_fig.add_trace(
                    go.Scatter(
                        x=group_curve.index,
                        y=group_curve["多头组合净值"],
                        name="多头组合净值",
                    ),
                    secondary_y=True,
                )
            if "空头组合净值" in group_curve.columns:
                line_fig.add_trace(
                    go.Scatter(
                        x=group_curve.index,
                        y=group_curve["空头组合净值"],
                        name="空头组合净值",
                        line=dict(dash="dashdot"),
                    ),
                    secondary_y=True,
                )
        line_fig.update_layout(
            title="分组资金曲线",
            hovermode="x unified",
        )

        st.plotly_chart(bar_fig, use_container_width=True)
        st.plotly_chart(line_fig, use_container_width=True)
        st.info(f"因子 {factor_name} 的分组分析已完成并在页面中展示。")


def calc_combo_score(df: pd.DataFrame, factor_cfg_list):
    if not factor_cfg_list:
        return None
    total_weight = sum(item[3] for item in factor_cfg_list)
    if total_weight == 0:
        total_weight = 1
    combo = pd.Series(0.0, index=df.index)
    for name, is_sort_asc, param, weight in factor_cfg_list:
        col_name = f"factor_{name}_{param}"
        if col_name not in df.columns:
            st.warning(f"综合因子计算缺少列: {col_name}")
            continue
        rank = df.groupby("candle_begin_time")[col_name].rank(ascending=is_sort_asc, method="min")
        combo += rank * (weight / total_weight)
    if combo.isna().all():
        return None
    return combo


def run_combo_factor_analysis(side: str, filter_list_info, mode_info: str, bins: int = 5,
                              enable_ls: bool | None = None, factor_cfg_list=None):
    if side == "long":
        combo_col = "combo_long_score"
        combo_title = "多头综合因子"
        if factor_cfg_list is None:
            factor_cfg_list = cfg.strategy.get("long_factor_list", [])
        st.subheader("多头综合因子分箱")
    else:
        combo_col = "combo_short_score"
        combo_title = "空头综合因子"
        if factor_cfg_list is None:
            factor_cfg_list = cfg.strategy.get("short_factor_list", [])
        st.subheader("空头综合因子分箱")

    st.write("开始进行综合因子分组分析...")

    if not factor_cfg_list:
        st.error("当前策略中对应方向的因子列表为空，请在 config.strategy 中配置。")
        return

    factor_name_list = [
        f"factor_{name}_{param}"
        for name, is_sort_asc, param, weight in factor_cfg_list
    ]

    st.write("读取处理后的所有币K线数据...")
    all_factors_kline = pd.read_pickle(get_file_path("data", "cache", "all_factors_df.pkl"))

    for factor_name in factor_name_list:
        st.write(f"读取因子数据：{factor_name}...")
        factor = pd.read_pickle(get_file_path("data", "cache", f"{factor_name}.pkl"))
        if factor.empty:
            st.error(f"{factor_name} 数据为空，请检查因子数据")
            return
        all_factors_kline[factor_name] = factor

    filter_factor_list = [FilterFactorConfig.init(item) for item in filter_list_info] if filter_list_info else []
    for filter_config in filter_factor_list:
        filter_path = get_file_path("data", "cache", f"factor_{filter_config.col_name}.pkl")
        st.write(f"读取过滤因子数据：{filter_config.col_name}...")
        filter_factor = pd.read_pickle(filter_path)
        if filter_factor.empty:
            st.error(f"{filter_config.col_name} 数据为空，请检查因子数据")
            return
        all_factors_kline[filter_config.col_name] = filter_factor

    if mode_info == "spot":
        mode_kline = all_factors_kline[all_factors_kline["is_spot"] == 1]
        if mode_kline.empty:
            st.error("现货数据为空，请检查数据")
            return
    elif mode_info == "swap":
        mode_kline = all_factors_kline[all_factors_kline["is_spot"] == 0]
        if mode_kline.empty:
            st.error("合约数据为空，请检查数据")
            return
    elif mode_info == "spot+swap":
        mode_kline = all_factors_kline
        if mode_kline.empty:
            st.error("现货及合约数据为空，请检查数据")
            return
    else:
        st.error("mode 错误，只能选择 spot / swap / spot+swap")
        return

    if filter_factor_list:
        filter_condition = filter_common(mode_kline, filter_factor_list)
        mode_kline = mode_kline[filter_condition]

    combo_series = calc_combo_score(mode_kline, factor_cfg_list)
    if combo_series is None:
        st.error("综合因子计算失败，请检查因子配置或数据。")
        return
    mode_kline[combo_col] = combo_series

    st.write(f"开始绘制 {combo_title} 的分箱图和分组净值曲线...")
    group_curve, bar_df, labels = tf.group_analysis(mode_kline, combo_col, bins=bins)
    group_curve = group_curve.resample("D").last()
    is_spot_mode = mode_info in ("spot", "spot+swap")
    if enable_ls is True:
        is_spot_mode = False
    elif enable_ls is False:
        is_spot_mode = True

    if not is_spot_mode:
        labels += ["多空净值"]
    bar_df = bar_df[bar_df["groups"].isin(labels)]
    factor_labels = ["因子值最小"] + [""] * 3 + ["因子值最大"]
    if not is_spot_mode:
        factor_labels.append("")
    bar_df["因子值标识"] = factor_labels

    bar_fig = go.Figure()
    bar_fig.add_trace(
        go.Bar(
            x=bar_df["groups"],
            y=bar_df["asset"],
            text=bar_df["因子值标识"],
            name="分组净值",
        )
    )
    bar_fig.update_layout(
        title=f"{combo_title} 分组净值",
        xaxis_title="分组",
        yaxis_title="资产净值",
    )

    cols_list = [col for col in group_curve.columns if "第" in col]

    y2_cols = []
    if not is_spot_mode:
        for name in ["多空净值", "多头组合净值", "空头组合净值"]:
            if name in group_curve.columns:
                y2_cols.append(name)
    y2_data = group_curve[y2_cols] if y2_cols else pd.DataFrame()

    line_fig = make_subplots(specs=[[{"secondary_y": not is_spot_mode}]])
    for col in cols_list:
        line_fig.add_trace(
            go.Scatter(
                x=group_curve.index,
                y=group_curve[col],
                name=col,
            ),
            secondary_y=False,
        )
    if not is_spot_mode:
        if "多空净值" in group_curve.columns:
            line_fig.add_trace(
                go.Scatter(
                    x=group_curve.index,
                    y=group_curve["多空净值"],
                    name="多空净值",
                    line=dict(dash="dot"),
                ),
                secondary_y=True,
            )
        if "多头组合净值" in group_curve.columns:
            line_fig.add_trace(
                go.Scatter(
                    x=group_curve.index,
                    y=group_curve["多头组合净值"],
                    name="多头组合净值",
                ),
                secondary_y=True,
            )
        if "空头组合净值" in group_curve.columns:
            line_fig.add_trace(
                go.Scatter(
                    x=group_curve.index,
                    y=group_curve["空头组合净值"],
                    name="空头组合净值",
                    line=dict(dash="dashdot"),
                ),
                secondary_y=True,
            )
    line_fig.update_layout(
        title=f"{combo_title} 分组资金曲线",
        hovermode="x unified",
    )

    st.plotly_chart(bar_fig, use_container_width=True)
    st.plotly_chart(line_fig, use_container_width=True)
    st.info(f"{combo_title} 的分组分析已完成并在页面中展示。")


def factor_analysis_page():
    st.header("因子分组分析")
    st.caption("使用 data/cache 中的因子结果，对不同分组的净值表现进行分析。")

    mode_options = ["spot", "swap", "spot+swap"]
    mode_info = st.selectbox("数据模式", options=mode_options, index=0)

    bins = st.number_input("分组数量 bins", min_value=2, max_value=20, value=5, step=1)

    ls_mode = st.radio(
        "多空模式",
        options=[
            "按市场自动（现货只看多头，swap 显示多空组合）",
            "总是看多空组合（无论选择什么市场）",
        ],
        index=0,
        horizontal=False,
    )
    enable_ls = None if ls_mode.startswith("按市场") else True

    analysis_mode = st.radio(
        "分析类型",
        options=[
            "单因子分箱（使用下方 factor_dict）",
            "多头综合因子分箱（使用 config.strategy.long_factor_list）",
            "空头综合因子分箱（使用 config.strategy.short_factor_list）",
            "多空因子分箱（同时跑多头与空头综合因子）",
        ],
        index=0,
    )

    factor_dict_text = filter_list_text = filter_post_list_text = None
    long_factor_text = long_filter_text = long_filter_post_text = None
    short_factor_text = short_filter_text = short_filter_post_text = None

    if "多空因子分箱" not in analysis_mode:
        default_factor_dict = "{\n    'VWapBias': [1000],\n}"
        factor_dict_text = st.text_area("因子配置 factor_dict", value=default_factor_dict, height=140)

        default_filter_list = "[]"
        filter_list_text = st.text_area("前置过滤因子配置 filter_list（可选）", value=default_filter_list, height=100)

        default_filter_post_list = "[]"
        filter_post_list_text = st.text_area("后置过滤因子配置 filter_list_post（可选）", value=default_filter_post_list, height=100)

    if "多空因子分箱" in analysis_mode:
        long_factor_default = repr(cfg.strategy.get("long_factor_list", [])) if cfg.strategy.get("long_factor_list", []) else "[]"
        long_factor_text = st.text_area(
            "多头因子列表 long_factor_list（config 风格，例：[('VWapBias', False, 1000, 1)]）",
            value=long_factor_default,
            height=100,
        )

        long_filter_default = repr(cfg.strategy.get("long_filter_list", [])) if cfg.strategy.get("long_filter_list", []) else "[]"
        long_filter_text = st.text_area(
            "多头前置过滤因子配置 long_filter_list（可选）",
            value=long_filter_default,
            height=80,
        )

        long_filter_post_default = repr(cfg.strategy.get("long_filter_list_post", [])) if cfg.strategy.get("long_filter_list_post", []) else "[]"
        long_filter_post_text = st.text_area(
            "多头后置过滤因子配置 long_filter_list_post（可选）",
            value=long_filter_post_default,
            height=80,
        )

        short_factor_default = repr(cfg.strategy.get("short_factor_list", [])) if cfg.strategy.get("short_factor_list", []) else "[]"
        short_factor_text = st.text_area(
            "空头因子列表 short_factor_list（config 风格，例：[('Cci', False, 48, 1)]）",
            value=short_factor_default,
            height=100,
        )

        short_filter_default = repr(cfg.strategy.get("short_filter_list", [])) if cfg.strategy.get("short_filter_list", []) else "[]"
        short_filter_text = st.text_area(
            "空头前置过滤因子配置 short_filter_list（可选）",
            value=short_filter_default,
            height=80,
        )

        short_filter_post_default = repr(cfg.strategy.get("short_filter_list_post", [])) if cfg.strategy.get("short_filter_list_post", []) else "[]"
        short_filter_post_text = st.text_area(
            "空头后置过滤因子配置 short_filter_list_post（可选）",
            value=short_filter_post_default,
            height=80,
        )

    if st.button("运行因子分组分析"):
        st.write(f"当前分析类型: {analysis_mode}")
        combined_filter_list = []
        if analysis_mode.startswith("单因子") or ("综合因子分箱" in analysis_mode and "多空" not in analysis_mode):
            try:
                filter_list = ast.literal_eval(filter_list_text) if filter_list_text.strip() else []
                if not isinstance(filter_list, list):
                    st.error("filter_list 必须是列表，例如 [('QuoteVolumeMean', 48, 'pct:>=0.8')] 或 []")
                    return
            except Exception as e:
                st.error(f"过滤因子配置解析失败: {e}")
                return

            try:
                filter_post_list = ast.literal_eval(filter_post_list_text) if filter_post_list_text.strip() else []
                if not isinstance(filter_post_list, list):
                    st.error("filter_list_post 必须是列表，例如 [('UpTimeRatio', 800, 'val:>=0.5')] 或 []")
                    return
            except Exception as e:
                st.error(f"后置过滤因子配置解析失败: {e}")
                return

            combined_filter_list = list(filter_list) + list(filter_post_list)

        if analysis_mode.startswith("单因子"):
            try:
                factor_dict = ast.literal_eval(factor_dict_text)
                if not isinstance(factor_dict, dict):
                    st.error("factor_dict 必须是字典，例如 {'VWapBias': [1000]}")
                    return
            except Exception as e:
                st.error(f"因子配置解析失败: {e}")
                return

            if not factor_dict:
                st.error("因子配置为空，请至少配置一个因子及参数。")
                return

            with st.spinner("因子分析运行中..."):
                run_factor_analysis_once(factor_dict, combined_filter_list, mode_info, bins=int(bins), enable_ls=enable_ls)
        elif "多空因子分箱" in analysis_mode:
            try:
                long_factor_list = ast.literal_eval(long_factor_text) if (long_factor_text and long_factor_text.strip()) else []
                if not isinstance(long_factor_list, list):
                    st.error("多头因子列表 long_factor_list 必须是列表，例如 [('VWapBias', False, 1000, 1)] 或 []")
                    return
            except Exception as e:
                st.error(f"多头因子列表解析失败: {e}")
                return

            try:
                long_filter_list = ast.literal_eval(long_filter_text) if (long_filter_text and long_filter_text.strip()) else []
                if not isinstance(long_filter_list, list):
                    st.error("多头前置过滤 long_filter_list 必须是列表")
                    return
            except Exception as e:
                st.error(f"多头前置过滤解析失败: {e}")
                return

            try:
                long_filter_post_list = ast.literal_eval(long_filter_post_text) if (long_filter_post_text and long_filter_post_text.strip()) else []
                if not isinstance(long_filter_post_list, list):
                    st.error("多头后置过滤 long_filter_list_post 必须是列表")
                    return
            except Exception as e:
                st.error(f"多头后置过滤解析失败: {e}")
                return

            try:
                short_factor_list = ast.literal_eval(short_factor_text) if (short_factor_text and short_factor_text.strip()) else []
                if not isinstance(short_factor_list, list):
                    st.error("空头因子列表 short_factor_list 必须是列表，例如 [('Cci', False, 48, 1)] 或 []")
                    return
            except Exception as e:
                st.error(f"空头因子列表解析失败: {e}")
                return

            try:
                short_filter_list = ast.literal_eval(short_filter_text) if (short_filter_text and short_filter_text.strip()) else []
                if not isinstance(short_filter_list, list):
                    st.error("空头前置过滤 short_filter_list 必须是列表")
                    return
            except Exception as e:
                st.error(f"空头前置过滤解析失败: {e}")
                return

            try:
                short_filter_post_list = ast.literal_eval(short_filter_post_text) if (short_filter_post_text and short_filter_post_text.strip()) else []
                if not isinstance(short_filter_post_list, list):
                    st.error("空头后置过滤 short_filter_list_post 必须是列表")
                    return
            except Exception as e:
                st.error(f"空头后置过滤解析失败: {e}")
                return

            long_combined_filter = list(long_filter_list) + list(long_filter_post_list)
            short_combined_filter = list(short_filter_list) + list(short_filter_post_list)

            with st.spinner("多头综合因子分析运行中..."):
                run_combo_factor_analysis("long", long_combined_filter, mode_info, bins=int(bins),
                                          enable_ls=enable_ls, factor_cfg_list=long_factor_list)
            with st.spinner("空头综合因子分析运行中..."):
                run_combo_factor_analysis("short", short_combined_filter, mode_info, bins=int(bins),
                                          enable_ls=enable_ls, factor_cfg_list=short_factor_list)
        elif "多头综合" in analysis_mode:
            with st.spinner("综合因子分析运行中..."):
                run_combo_factor_analysis("long", combined_filter_list, mode_info, bins=int(bins), enable_ls=enable_ls)
        elif "空头综合" in analysis_mode:
            with st.spinner("综合因子分析运行中..."):
                run_combo_factor_analysis("short", combined_filter_list, mode_info, bins=int(bins), enable_ls=enable_ls)

        if not analysis_mode.startswith("多空因子分箱"):
            st.markdown(
                "配置示例（与 config 中用法一致）：\n"
                "```python\n"
                "filter_list = [\n"
                "    ('QuoteVolumeMean', 48, 'pct:>=0.8'),\n"
                "]\n"
                "\n"
                "filter_list_post = [\n"
                "    ('UpTimeRatio', 800, 'val:>=0.5'),\n"
                "]\n"
                "```"
            )


def main():
    st.set_page_config(page_title="因子分析与查看工具", layout="wide")
    st.title("因子分析与查看工具")

    with st.sidebar:
        st.header("基础设置（因子查看器）")
        market = st.selectbox("市场", options=["spot", "swap"], index=1)
        hp_unit = st.radio("持仓期单位", options=["小时(H)", "天(D)"], index=0, horizontal=True)
        hp_value = st.number_input("周期长度", value=8, min_value=1, step=1)
        hold_period = f"{int(hp_value)}H" if hp_unit.startswith("小时") else f"{int(hp_value)}D"
        st.caption(f"当前持仓期：{hold_period}")
        data_dir = Path(cfg.swap_path if market == "swap" else cfg.spot_path)
        st.caption(f"数据路径：{data_dir}")

        try:
            factor_files = [f[:-3] for f in os.listdir("factors") if f.endswith(".py") and f != "__init__.py"]
        except FileNotFoundError:
            factor_files = []
        factor_name = st.selectbox("因子名称（来自 factors 目录）", options=sorted(factor_files))

        param = st.number_input("参数（整数或主参数）", value=14, step=1)
        enable_multi_params = st.checkbox(
            "启用多参数遍历",
            value=False,
            help="在单因子下同时计算多个参数，例如 range(0,100,10)",
        )
        param_mode = "区间(range)"
        range_start = range_stop = range_step = None
        params_text = ""
        out_prefix = factor_name
        out_col = f"{factor_name}_{int(param)}"
        if enable_multi_params:
            param_mode = st.radio("参数输入方式", options=["区间(range)", "列表"], index=0, horizontal=True)
            if param_mode == "区间(range)":
                range_start = st.number_input("起始(start)", value=0, step=1)
                range_stop = st.number_input("终止(stop，非包含)", value=100, step=1)
                range_step = st.number_input("步长(step)", value=10, step=1, min_value=1)
                params_text = ""
            else:
                params_text = st.text_input("参数列表（逗号分隔）", value="0,10,20,30")
                range_start = range_stop = range_step = None
            out_prefix = st.text_input("输出列前缀", value=factor_name,
                                       help="多参数模式下的输出列将为 前缀_参数，例如 Rsi_10、Rsi_20")
            out_col = ""
        else:
            out_col = st.text_input("输出列名（可选）", value=f"{factor_name}_{int(param)}")

        st.header("执行")
        run_single = st.button("计算单币种因子（下方选择币种）")
        clear_single = st.button("清空结果", help="清除已计算的单币种结果，恢复初始状态")
        if clear_single:
            for k in ["single_df", "single_factor_cols", "single_symbol_file", "single_factor_name"]:
                st.session_state.pop(k, None)

    tab_viewer, tab_analysis = st.tabs(["单币种因子查看", "因子分组分析"])

    with tab_viewer:
        factor_viewer_page(
            market=market,
            hold_period=hold_period,
            data_dir=data_dir,
            factor_name=factor_name,
            param=int(param),
            enable_multi_params=enable_multi_params,
            param_mode=param_mode,
            range_start=range_start,
            range_stop=range_stop,
            range_step=range_step,
            params_text=params_text,
            out_prefix=out_prefix,
            out_col=out_col,
            run_single=run_single,
        )

    with tab_analysis:
        factor_analysis_page()


if __name__ == "__main__":
    try:
        import streamlit.runtime.scriptrunner

        main()
    except (ImportError, ModuleNotFoundError):
        if st.runtime.exists():
            main()
        else:
            print("\n" + "=" * 80)
            print("  因子分析与查看工具 (Streamlit版)")
            print("=" * 80)
            print("\n  请使用 Streamlit 运行此工具：")
            print(f"\n  streamlit run {Path(__file__).name}")
            print("\n" + "=" * 80 + "\n")

