"""
邢不行选币框架 - 参数平原全能工具 tool9
集成参数遍历生成与参数平原可视化分析

使用说明：
在终端运行: streamlit run tools/tool9_参数平原全能可视化.py
"""

import sys
import os
import time
import warnings
import traceback
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


try:
    from core.model.backtest_config import create_factory
    from core.utils.path_kit import get_folder_path
    from program.step1_prepare_data import prepare_data
    from program.step2_calculate_factors import calc_factors
    from program.step3_select_coins import aggregate_select_results, select_coins
    from program.step4_simulate_performance import simulate_performance
    import config
except ImportError as e:
    st.error(f"Import Error: {e}. 请确认在项目根目录下运行此工具。错误信息: {e}")


warnings.filterwarnings("ignore")


st.set_page_config(
    page_title="邢不行 参数平原全能工具 tool10",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)


def get_traversal_root() -> Path:
    return get_folder_path("data", "遍历结果", path_type=True)


def get_group_root(group_name: str) -> Path:
    root = get_traversal_root()
    return root / group_name


def run_parameter_traversal(task_name, strategies_list, status_callback=None):
    try:
        if status_callback:
            status_callback("正在生成策略配置...")

        original_backtest_name = config.backtest_name
        config.backtest_name = task_name

        backtest_factory = create_factory(strategies_list)

        if status_callback:
            status_callback(f"一共需要回测的参数组合数：{len(backtest_factory.config_list)}")

        dummy_conf_with_all_factors = backtest_factory.generate_all_factor_config()
        calc_factors(dummy_conf_with_all_factors)

        reports = []
        total = len(backtest_factory.config_list)
        progress_bar = st.progress(0.0)

        for i, backtest_config in enumerate(backtest_factory.config_list):
            if status_callback:
                status_callback(f"正在回测组合 {i + 1}/{total}: {backtest_config.get_fullname()}")

            select_coins(backtest_config)
            if backtest_config.strategy_short is not None:
                select_coins(backtest_config, is_short=True)

            select_results = aggregate_select_results(backtest_config)
            report = simulate_performance(backtest_config, select_results, show_plot=False)
            reports.append(report)

            progress_bar.progress((i + 1) / total)

        if status_callback:
            status_callback("正在保存汇总结果...")

        all_params_map = pd.concat(reports, ignore_index=True)
        report_columns = all_params_map.columns

        sheet = backtest_factory.get_name_params_sheet()
        all_params_map = all_params_map.merge(sheet, left_on="param", right_on="fullname", how="left")

        all_params_map.sort_values(by="累积净值", ascending=False, inplace=True)

        result_folder = get_folder_path("data", "遍历结果", task_name, path_type=True)

        final_df = all_params_map[[*sheet.columns, *report_columns]].drop(columns=["param"])
        final_df.to_excel(result_folder / "最优参数.xlsx", index=False)

        config.backtest_name = original_backtest_name

        return True, f"完成！结果已保存至 data/遍历结果/{task_name}"

    except Exception as e:
        return False, f"Error: {str(e)}\n{traceback.format_exc()}"


def get_available_param_groups():
    param_groups = []
    base_path = get_traversal_root()
    if base_path.exists():
        for folder in base_path.iterdir():
            if folder.is_dir() and (folder / "最优参数.xlsx").exists():
                param_groups.append(folder.name)
    return sorted(param_groups, reverse=True)


def load_param_data(group_name: str):
    try:
        base_path = get_group_root(group_name)
        optimal_params_file = base_path / "最优参数.xlsx"
        param_sheet_file = base_path / "策略回测参数总表.xlsx"

        if optimal_params_file.exists():
            optimal_df = pd.read_excel(optimal_params_file)
        else:
            optimal_df = pd.DataFrame()

        if param_sheet_file.exists():
            param_sheet_df = pd.read_excel(param_sheet_file)
        else:
            param_sheet_df = pd.DataFrame()

        return optimal_df, param_sheet_df
    except Exception as e:
        st.error(f"加载参数数据失败: {e}")
        return pd.DataFrame(), pd.DataFrame()


def extract_factor_params(df: pd.DataFrame):
    prefixes = [
        "#FACTOR-",
        "#LONG-",
        "#SHORT-",
        "#LONG-FILTER-",
        "#SHORT-FILTER-",
        "#LONG-POST-",
        "#SHORT-POST-",
    ]
    cols = []
    for col in df.columns:
        for p in prefixes:
            if isinstance(col, str) and col.startswith(p):
                cols.append(col)
                break
    return cols


def create_param_sensitivity_analysis(df: pd.DataFrame, factor_cols):
    sensitivity_data = []
    if df.empty or not factor_cols:
        return pd.DataFrame()

    for factor_col in factor_cols:
        factor_name = factor_col
        for p in [
            "#FACTOR-",
            "#LONG-",
            "#SHORT-",
            "#LONG-FILTER-",
            "#SHORT-FILTER-",
            "#LONG-POST-",
            "#SHORT-POST-",
        ]:
            factor_name = factor_name.replace(p, "")

        param_values = sorted(df[factor_col].dropna().unique())

        for param_value in param_values:
            param_data = df[df[factor_col] == param_value]
            if param_data.empty:
                continue
            avg_net_value = param_data["累积净值"].mean()
            max_net_value = param_data["累积净值"].max()
            min_net_value = param_data["累积净值"].min()
            std_net_value = param_data["累积净值"].std()
            count = len(param_data)

            sensitivity_data.append(
                {
                    "因子": factor_name,
                    "参数值": str(param_value),
                    "平均累积净值": float(avg_net_value),
                    "最大累积净值": float(max_net_value),
                    "最小累积净值": float(min_net_value),
                    "标准差": float(std_net_value),
                    "组合数量": int(count),
                }
            )

    result_df = pd.DataFrame(sensitivity_data)
    if not result_df.empty:
        result_df["参数值"] = result_df["参数值"].astype(str)
    return result_df


def create_sensitivity_charts(sensitivity_df: pd.DataFrame):
    if sensitivity_df.empty:
        return []
    factors = sensitivity_df["因子"].unique()
    charts = []
    for factor in factors:
        factor_data = sensitivity_df[sensitivity_df["因子"] == factor].copy()
        try:
            factor_data["参数值_数值"] = factor_data["参数值"].astype(float)
            factor_data = factor_data.sort_values("参数值_数值")
            x_values = factor_data["参数值"].tolist()
        except Exception:
            factor_data = factor_data.sort_values("参数值")
            x_values = factor_data["参数值"].tolist()

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=factor_data["平均累积净值"],
                mode="lines+markers",
                name="平均累积净值",
                line=dict(color="blue", width=2),
                marker=dict(size=8),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=factor_data["最大累积净值"],
                mode="lines+markers",
                name="最大累积净值",
                line=dict(color="green", width=1, dash="dash"),
                marker=dict(size=6),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=factor_data["最小累积净值"],
                mode="lines+markers",
                name="最小累积净值",
                line=dict(color="red", width=1, dash="dash"),
                marker=dict(size=6),
            )
        )
        fig.update_layout(
            title=f"{factor} 参数敏感度分析",
            height=500,
            width=1000,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
            ),
            xaxis_title="参数值",
            yaxis_title="累积净值",
        )
        charts.append((factor, fig))
    return charts


def create_3d_param_visualization(df: pd.DataFrame, x_factor, y_factor, z_metric="累积净值"):
    if df.empty or x_factor not in df.columns or y_factor not in df.columns:
        return None
    fig = go.Figure()
    fig.add_trace(
        go.Scatter3d(
            x=df[x_factor],
            y=df[y_factor],
            z=df[z_metric],
            mode="markers",
            marker=dict(
                size=8,
                color=df[z_metric],
                colorscale="Viridis",
                showscale=True,
                colorbar=dict(title=z_metric),
            ),
            text=df.get("策略", None),
            hovertemplate=(
                "<b>策略</b>: %{text}<br>"
                f"<b>{x_factor}</b>: %{{x}}<br>"
                f"<b>{y_factor}</b>: %{{y}}<br>"
                f"<b>{z_metric}</b>: %{{z}}<br>"
                "<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        title=f"三维参数空间可视化 - {x_factor} vs {y_factor} vs {z_metric}",
        scene=dict(
            xaxis_title=x_factor,
            yaxis_title=y_factor,
            zaxis_title=z_metric,
        ),
        width=900,
        height=700,
    )
    return fig


def create_param_heatmap(df: pd.DataFrame, x_factor, y_factor, z_metric="累积净值"):
    if df.empty or x_factor not in df.columns or y_factor not in df.columns:
        return None
    pivot_table = df.pivot_table(values=z_metric, index=y_factor, columns=x_factor, aggfunc="mean")
    fig = px.imshow(
        pivot_table,
        labels=dict(x=x_factor, y=y_factor, color=z_metric),
        color_continuous_scale="RdYlGn",
        aspect="auto",
        text_auto=True,
        color_continuous_midpoint=0,
    )
    fig.update_layout(
        title=f"参数组合收益热力图 - {x_factor} vs {y_factor}",
        width=800,
        height=600,
    )
    return fig


def create_param_distribution(df: pd.DataFrame, factor_col: str):
    if df.empty or factor_col not in df.columns:
        return None
    fig = px.scatter(
        df,
        x=factor_col,
        y="累积净值",
        color="累积净值",
        color_continuous_scale="RdYlGn",
    )
    fig.update_layout(
        title=f"{factor_col.replace('#FACTOR-', '')} 参数分布与收益关系",
        xaxis_title=factor_col.replace("#FACTOR-", ""),
        yaxis_title="累积净值",
        width=800,
        height=500,
    )
    return fig


def load_period_return_data(group_name: str, param_combination: str, period_type: str) -> pd.DataFrame:
    file_map = {
        "年度": "年度账户收益.csv",
        "季度": "季度账户收益.csv",
        "月度": "月度账户收益.csv",
    }
    if period_type not in file_map:
        return pd.DataFrame()
    base_path = get_group_root(group_name) / param_combination
    file_path = base_path / file_map[period_type]
    if not file_path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(file_path)
        if "candle_begin_time" not in df.columns or "涨跌幅" not in df.columns:
            return pd.DataFrame()
        df["candle_begin_time"] = pd.to_datetime(df["candle_begin_time"])
        if period_type == "年度":
            df["周期"] = df["candle_begin_time"].dt.year.astype(str)
        elif period_type == "季度":
            df["周期"] = df["candle_begin_time"].dt.to_period("Q").astype(str)
        elif period_type == "月度":
            df["周期"] = df["candle_begin_time"].dt.to_period("M").astype(str)
        df["涨跌幅"] = df["涨跌幅"].astype(str).str.replace("%", "").astype(float)
        return df
    except Exception:
        return pd.DataFrame()


def create_period_plane_heatmap(group_name: str, period_type: str):
    group_root = get_group_root(group_name)
    if not group_root.exists():
        return None
    combinations = [
        item.name for item in group_root.iterdir() if item.is_dir() and item.name.startswith("参数组合_")
    ]
    if not combinations:
        return None

    value_map = {}
    periods_set = set()

    for comb in combinations:
        df = load_period_return_data(group_name, comb, period_type)
        if df.empty:
            continue
        agg = df.groupby("周期")["涨跌幅"].mean()
        periods_set.update(agg.index.tolist())
        value_map[comb] = agg

    if not value_map:
        return None

    periods = sorted(periods_set)
    z_data = []
    y_labels = []
    for comb in sorted(value_map.keys()):
        series = value_map[comb]
        row = []
        for p in periods:
            row.append(float(series.get(p, np.nan)))
        z_data.append(row)
        y_labels.append(comb)

    fig = go.Figure(
        data=go.Heatmap(
            z=z_data,
            x=periods,
            y=y_labels,
            colorscale="RdYlGn",
            colorbar=dict(title="涨跌幅 (%)"),
        )
    )
    fig.update_layout(
        title=f"{period_type} 参数平原热力图",
        xaxis_title=period_type,
        yaxis_title="参数组合",
        width=900,
        height=700,
    )
    return fig


def render_generation_ui():
    st.header("运行参数遍历")
    st.markdown("在此页面配置策略模板和参数范围，运行新的回测遍历任务。")

    default_name = f"遍历任务_{datetime.now().strftime('%Y%m%d_%H%M')}"
    task_name = st.text_input("任务名称 (输出文件夹名)", value=default_name)

    st.subheader("策略模板配置")
    st.markdown("在下方字典中使用 `{param}` 作为待遍历参数占位符。")

    default_template = """{
    "hold_period": "8H",
    "market": "swap_swap",
    "offset_list": range(0, 8, 1),
    "long_select_coin_num": 0.2,
    "short_select_coin_num": 0,

    "long_factor_list": [
        ('VWapBias', False, 1000, 1),
    ],
    "long_filter_list": [
        ('QuoteVolumeMean', 48, 'pct:>=0.8'),
    ],
    "long_filter_list_post": [
        ('UpTimeRatio', 800, 'val:>=0.5'),
    ],

    "short_factor_list": [

    ],
    "short_filter_list": [

    ],
    "short_filter_list_post": [

    ],
}"""

    strategy_str = st.text_area("策略配置字典 (Python)", value=default_template, height=380)

    st.subheader("遍历参数范围")
    col1, col2, col3 = st.columns(3)
    start_val = col1.number_input("开始值", value=50, step=10)
    end_val = col2.number_input("结束值 (包含)", value=200, step=10)
    step_val = col3.number_input("步长", value=50, step=10, min_value=1)

    if st.button("开始运行遍历"):
        status_text = st.empty()

        if "{param}" not in strategy_str:
            st.error("策略模板中未找到 `{param}` 占位符。")
            return

        try:
            param_range = range(int(start_val), int(end_val) + 1, int(step_val))
            if len(param_range) <= 0:
                st.error("参数范围无效，请检查开始值、结束值和步长。")
                return

            status_text.text(f"正在生成 {len(param_range)} 个策略配置...")

            strategies = []
            context = {"range": range, "True": True, "False": False}
            for p in param_range:
                current_str = strategy_str.replace("{param}", str(p))
                strategy_dict = eval(current_str, context)
                strategies.append(strategy_dict)

            start_time = time.time()
            success, msg = run_parameter_traversal(task_name, strategies, status_text.text)
            elapsed = time.time() - start_time

            if success:
                st.success(msg + f" 总耗时约 {elapsed:.1f} 秒。")
            else:
                st.error(msg)

        except Exception as e:
            st.error(f"配置解析或执行错误: {e}")
            st.code(traceback.format_exc())


def render_visualization_ui():
    st.header("查看遍历结果与参数平原")

    available_groups = get_available_param_groups()
    if not available_groups:
        st.error("未找到任何遍历结果。请先在“运行参数遍历”页生成数据。")
        return

    selected_group = st.selectbox("选择任务 (Folder)", available_groups)
    if not selected_group:
        return

    with st.spinner("正在加载遍历结果数据..."):
        optimal_df, param_sheet_df = load_param_data(selected_group)

    if optimal_df.empty:
        st.error("无法加载最优参数结果文件。")
        return

    st.subheader("数据概览")
    c1, c2, c3 = st.columns(3)
    c1.metric("组合总数", len(optimal_df))
    c2.metric("最高净值", f"{optimal_df['累积净值'].max():.2f}")
    c3.metric("平均净值", f"{optimal_df['累积净值'].mean():.2f}")

    st.subheader("Top 5 组合")
    top_cols = [col for col in ["策略", "累积净值", "年化收益", "最大回撤"] if col in optimal_df.columns]
    if top_cols:
        st.dataframe(optimal_df.nlargest(5, "累积净值")[top_cols].reset_index(drop=True), use_container_width=True)

    factor_cols = extract_factor_params(optimal_df)
    if not factor_cols:
        st.info("未识别到因子参数列，后续参数平原分析功能将受限。")

    st.subheader("参数敏感性分析")
    sensitivity_df = create_param_sensitivity_analysis(optimal_df, factor_cols) if factor_cols else pd.DataFrame()
    if sensitivity_df.empty:
        st.info("无法生成参数敏感性分析数据。")
    else:
        st.dataframe(sensitivity_df, use_container_width=True)
        charts = create_sensitivity_charts(sensitivity_df)
        if charts:
            for factor, fig in charts:
                st.plotly_chart(fig, use_container_width=True)

    st.subheader("三维参数空间可视化")
    if len(factor_cols) >= 2:
        col1, col2 = st.columns(2)
        x_factor = col1.selectbox("X 轴因子", factor_cols, index=0)
        y_candidates = [c for c in factor_cols if c != x_factor]
        if not y_candidates:
            y_candidates = factor_cols
        y_factor = col2.selectbox("Y 轴因子", y_candidates, index=0)
        fig_3d = create_3d_param_visualization(optimal_df, x_factor, y_factor)
        if fig_3d:
            st.plotly_chart(fig_3d, use_container_width=True)
    else:
        st.info("需要至少两个因子参数才能进行三维可视化分析。")

    st.subheader("参数组合收益热力图")
    if len(factor_cols) >= 2:
        col1, col2 = st.columns(2)
        heatmap_x = col1.selectbox("热力图 X 轴因子", factor_cols, index=0)
        y_candidates = [c for c in factor_cols if c != heatmap_x]
        if not y_candidates:
            y_candidates = factor_cols
        heatmap_y = col2.selectbox("热力图 Y 轴因子", y_candidates, index=0)
        fig_heatmap = create_param_heatmap(optimal_df, heatmap_x, heatmap_y)
        if fig_heatmap:
            st.plotly_chart(fig_heatmap, use_container_width=True)
    else:
        st.info("需要至少两个因子参数才能生成收益热力图。")

    st.subheader("按周期划分的参数平原热力图")
    period_type = st.selectbox("周期类型", ["年度", "季度", "月度"], index=0)
    fig_plane = create_period_plane_heatmap(selected_group, period_type)
    if fig_plane:
        st.plotly_chart(fig_plane, use_container_width=True)
    else:
        st.info(f"未能生成 {period_type} 参数平原热力图，可能缺少对应周期收益文件。")

    st.subheader("参数优化详细数据与筛选")
    col1, col2 = st.columns(2)
    with col1:
        min_net_value = st.number_input(
            "最小累积净值",
            min_value=float(optimal_df["累积净值"].min()),
            max_value=float(optimal_df["累积净值"].max()),
            value=float(optimal_df["累积净值"].min()),
            step=0.1,
        )
    with col2:
        sort_by = st.selectbox(
            "排序方式",
            ["累积净值", "年化收益", "最大回撤"],
            index=0,
        )

    filtered_df = optimal_df[optimal_df["累积净值"] >= min_net_value].copy()

    if "年化收益" in filtered_df.columns:
        filtered_df["年化收益数值"] = (
            pd.Series(filtered_df["年化收益"]).astype(str).str.replace("%", "").astype(float)
        )
    if "最大回撤" in filtered_df.columns:
        filtered_df["最大回撤数值"] = (
            -pd.Series(filtered_df["最大回撤"]).astype(str).str.replace("-", "").str.replace("%", "").astype(float)
        )

    sort_column_map = {
        "累积净值": "累积净值",
        "年化收益": "年化收益数值",
        "最大回撤": "最大回撤数值",
    }
    actual_sort_by = sort_column_map.get(sort_by, "累积净值")
    if actual_sort_by in filtered_df.columns:
        filtered_df = filtered_df.sort_values(actual_sort_by, ascending=False)

    st.info(f"筛选结果: 共 {len(filtered_df)} 个参数组合")
    st.dataframe(filtered_df, use_container_width=True)

    csv_bytes = filtered_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="下载筛选结果 CSV",
        data=csv_bytes,
        file_name=f"参数优化结果_{selected_group}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )


def main():
    st.title("邢不行 参数平原全能工具 tool9")
    st.markdown("---")

    mode = st.sidebar.radio("选择模式", ["运行参数遍历", "查看遍历结果"], index=0)
    if mode == "运行参数遍历":
        render_generation_ui()
    else:
        render_visualization_ui()


if __name__ == "__main__":
    main()

