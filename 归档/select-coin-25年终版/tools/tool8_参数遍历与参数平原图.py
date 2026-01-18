"""
邢不行™️选币框架
Python数字货币量化投资课程

版权所有 ©️ 邢不行
微信: xbx8662

未经授权，不得复制、修改、或使用本代码的全部或部分内容。仅限个人学习用途，禁止商业用途。

Author: 邢不行

使用方法：
        直接运行文件即可
"""
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import os
import sys
import time
import warnings
from zlib import Z_DEFAULT_COMPRESSION

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.model.backtest_config import create_factory
from core.utils.path_kit import get_folder_path
from program.step1_prepare_data import prepare_data
from program.step2_calculate_factors import calc_factors
from program.step3_select_coins import aggregate_select_results, select_coins
from program.step4_simulate_performance import simulate_performance
from config import backtest_name


def _get_traversal_root(backtest_name_str: str) -> Path:
    return get_folder_path('data', '遍历结果', backtest_name_str, path_type=True)


def _read_param_sheet(root: Path) -> pd.DataFrame:
    sheet_path = root / '策略回测参数总表.xlsx'
    if not sheet_path.exists():
        raise FileNotFoundError(f'未找到参数总表: {sheet_path}')
    df = pd.read_excel(sheet_path)
    df = df.reset_index(drop=False)
    df['iter_round'] = df['index'] + 1
    df.drop(columns=['index'], inplace=True)
    return df


def _parse_year_return_csv(csv_path: Path) -> Dict[str, float]:
    if not csv_path.exists():
        return {}
    df = pd.read_csv(csv_path)

    col = None
    for c in ['涨跌幅', 'rtn', 'return']:
        if c in df.columns:
            col = c
            break
    if col is None:
        return {}

    def to_float(x):
        if isinstance(x, str):
            x = x.strip().replace('%', '')
            try:
                return float(x) / 100.0
            except Exception:
                return None
        try:
            return float(x)
        except Exception:
            return None

    df[col] = df[col].apply(to_float)

    year_col = None
    for c in ['year', '年份']:
        if c in df.columns:
            year_col = c
            break
    if year_col is None:
        first_col = df.columns[0]
        if first_col != col:
            year_col = first_col
        else:
            return {}

    ret = {}
    for _, row in df.iterrows():
        y = str(row[year_col])
        v = row[col]
        if v is None:
            continue
        ret[y] = float(v)
    return ret


def _compute_year_return_from_equity(csv_path: Path) -> Dict[str, float]:
    if not csv_path.exists():
        return {}
    df = pd.read_csv(csv_path)
    if 'candle_begin_time' not in df.columns:
        return {}
    if '涨跌幅' not in df.columns:
        return {}
    df['candle_begin_time'] = pd.to_datetime(df['candle_begin_time'])
    df = df.set_index('candle_begin_time')
    year_df = df[['涨跌幅']].resample('A').apply(lambda x: (1 + x).prod() - 1)
    return {str(idx.year): float(val) for idx, val in zip(year_df.index, year_df['涨跌幅'])}


def _read_year_return(root: Path, iter_round: int) -> Dict[str, float]:
    combo_dir = root / f'参数组合_{iter_round}'
    ret = _parse_year_return_csv(combo_dir / '年度账户收益.csv')
    if ret:
        return ret
    return _compute_year_return_from_equity(combo_dir / '资金曲线.csv')


def collect_one_param_yearly_data(backtest_name_str: str, factor_column: str) -> Tuple[pd.DataFrame, List[str]]:
    root = _get_traversal_root(backtest_name_str)
    sheet = _read_param_sheet(root)
    if factor_column not in sheet.columns:
        raise KeyError(f'参数列不存在: {factor_column}，请检查策略回测参数总表.xlsx')

    rows = []
    all_years = set()
    for _, r in sheet.iterrows():
        iter_round = int(r['iter_round'])
        year_map = _read_year_return(root, iter_round)
        if not year_map:
            continue
        all_years |= set(year_map.keys())
        row = {
            'iter_round': iter_round,
            'param': r[factor_column],
        }
        for y, v in year_map.items():
            row[f'year_{y}'] = v
        rows.append(row)

    data = pd.DataFrame(rows)
    years = sorted(list(all_years))
    return data, years


def _normalize_axis_title(factor_column: str) -> str:
    return factor_column.replace('#FACTOR-', '') if factor_column.startswith('#FACTOR-') else factor_column


def build_one_param_line_html(
    data: pd.DataFrame,
    years: List[str],
    title: str,
    output_path: Path,
    x_title: Optional[str] = None,
) -> None:
    if data.empty:
        raise ValueError('没有可用数据用于绘图')

    agg = {}
    for y in years:
        col = f'year_{y}'
        series = data.groupby('param')[col].mean()
        agg[y] = series

    x_vals = sorted(set(data['param']))

    n_cols = 2
    n_rows = (len(years) + n_cols - 1) // n_cols
    specs = [[{}, {}] for _ in range(n_rows)]
    specs.append([{"colspan": 2}, None])

    titles = []
    for i in range(n_rows * n_cols):
        if i < len(years):
            titles.append(f'{years[i]}年 - {x_title or "参数值"}')
        else:
            titles.append('')
    titles.append('全部年份收益柱状图')
    titles.append('')

    fig = make_subplots(
        rows=n_rows + 1,
        cols=n_cols,
        shared_xaxes=True,
        subplot_titles=titles,
        specs=specs,
        vertical_spacing=0.08,
    )

    line_color = '#1f77b4'
    for i, y in enumerate(years):
        series = agg[y]
        y_vals = [float(series.get(x, float('nan'))) for x in x_vals]
        row = (i // n_cols) + 1
        col = (i % n_cols) + 1
        fig.add_trace(
            go.Scatter(
                x=x_vals,
                y=y_vals,
                mode='lines+markers',
                name=f'{y}',
                line=dict(color=line_color),
                marker=dict(color=line_color),
                showlegend=False,
            ),
            row=row,
            col=col,
        )
        fig.update_xaxes(
            tickmode='array',
            tickvals=x_vals,
            ticktext=[str(x) for x in x_vals],
            row=row,
            col=col,
        )
        fig.update_yaxes(title_text='年度收益', row=row, col=col)

    overall_vals = [
        float(pd.to_numeric(data.get(f'year_{y}', pd.Series(dtype=float)), errors='coerce').mean()) for y in years
    ]
    fig.add_trace(
        go.Bar(
            x=years,
            y=overall_vals,
            marker_color=line_color,
            name='年度平均收益',
            showlegend=False,
        ),
        row=n_rows + 1,
        col=1,
    )
    fig.update_xaxes(title_text='年份', row=n_rows + 1, col=1)
    fig.update_yaxes(title_text='年度收益（平均）', row=n_rows + 1, col=1)

    fig_height = max(560, 260 * n_rows + 280)
    fig.update_layout(
        title=None,
        hovermode='x unified',
        height=fig_height,
        margin=dict(l=60, r=30, t=50, b=60),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    import plotly.offline as po

    po.plot(fig, filename=str(output_path.resolve()), auto_open=False)


def generate_one_param_plain_report(
    backtest_name_str: str,
    factor_column: str,
    output_filename: str = '参数平原_单参数_折线.html',
    title: Optional[str] = None,
) -> Path:
    data, years = collect_one_param_yearly_data(backtest_name_str, factor_column)
    x_title = _normalize_axis_title(factor_column)
    root = _get_traversal_root(backtest_name_str)
    output_path = Path(root) / output_filename
    build_one_param_line_html(
        data=data,
        years=years,
        title=title or f'参数平原（单参数折线）：{x_title}',
        output_path=output_path,
        x_title=x_title,
    )
    return output_path


def main_one(
    backtest_name_str: str,
    factor_column: str,
    output_filename: Optional[str] = None,
    title: Optional[str] = None,
) -> Path:
    return generate_one_param_plain_report(
        backtest_name_str,
        factor_column,
        output_filename=output_filename or '参数平原_单参数_折线.html',
        title=title,
    )


def find_best_params(factory):
    print('参数遍历开始', '*' * 64)

    conf_list = factory.config_list
    for index, conf in enumerate(conf_list):
        print(f'参数组合{index + 1}｜共{len(conf_list)}')
        print(f'{conf.get_fullname()}')
        print()
    print('✅ 一共需要回测的参数组合数：{}'.format(len(conf_list)))
    print()

    dummy_conf_with_all_factors = factory.generate_all_factor_config()
    calc_factors(dummy_conf_with_all_factors)

    reports = []
    for backtest_config in factory.config_list:
        select_coins(backtest_config)
        if backtest_config.strategy_short is not None:
            select_coins(backtest_config, is_short=True)
        select_results = aggregate_select_results(backtest_config)
        report = simulate_performance(backtest_config, select_results, show_plot=False)
        reports.append(report)

    return reports


def _resolve_factor_column(backtest_name_str: str, factor_column: str, scope: str | None = None) -> str:
    root = get_folder_path('data', '遍历结果', backtest_name_str, path_type=True)
    sheet_path = root / '策略回测参数总表.xlsx'
    df = pd.read_excel(sheet_path)
    candidates = [factor_column]
    scope_map = {
        'long': ['#LONG-'],
        'short': ['#SHORT-'],
        'long_filter': ['#LONG-FILTER-'],
        'short_filter': ['#SHORT-FILTER-'],
        'long_post': ['#LONG-POST-'],
        'short_post': ['#SHORT-POST-'],
    }
    prefixes = scope_map.get(
        scope,
        [
            '#FACTOR-',
            '#FILTER-',
            '#LONG-',
            '#SHORT-',
            '#LONG-FILTER-',
            '#SHORT-FILTER-',
            '#LONG-POST-',
            '#SHORT-POST-',
        ],
    )
    for p in prefixes:
        if not factor_column.startswith(p):
            candidates.append(f'{p}{factor_column}')
    for c in candidates:
        if c in df.columns:
            return c
    raise KeyError(f'参数列不存在: {factor_column}')


def _to_sorted_params(values):
    try:
        nums = pd.to_numeric(values, errors='coerce')
        if nums.isnull().any():
            return sorted(list(set(values)))
        return sorted(list(set(nums)))
    except Exception:
        return sorted(list(set(values)))


def build_one_param_bars_html(data: pd.DataFrame, years, title: str, output_path, x_title=None):
    if data.empty:
        raise ValueError('没有可用数据用于绘图')
    agg = {}
    for y in years:
        col = f'year_{y}'
        series = data.groupby('param')[col].mean()
        agg[y] = series
    x_vals = _to_sorted_params(data['param'])
    n_cols = 2 if len(years) > 4 else 1
    n_rows = (len(years) + n_cols - 1) // n_cols
    specs = [[{}, {}] if n_cols == 2 else [{}] for _ in range(n_rows)]
    titles = []
    for i in range(n_rows * n_cols):
        if i < len(years):
            titles.append(f'{years[i]}年 - {x_title}')
        else:
            titles.append('')
    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        shared_xaxes=False,
        subplot_titles=titles,
        specs=specs,
        vertical_spacing=0.06,
    )
    palette_years = [
        '#636EFA',
        '#EF553B',
        '#00CC96',
        '#AB63FA',
        '#FFA15A',
        '#19D3F3',
        '#FF6692',
        '#B6E880',
        '#FF97FF',
        '#FECB52',
    ]
    ann_year_map = {}
    for i, y in enumerate(years):
        series = agg[y]
        y_vals = []
        ret_vals = []
        best_idx = None
        best_val = -1
        for idx, x in enumerate(x_vals):
            v = series.get(x, float('nan'))
            v2 = None if pd.isna(v) else float(1 + v)
            y_vals.append(v2)
            ret_vals.append(v)
            if v2 is not None and v2 > best_val:
                best_val = v2
                best_idx = idx
        row = (i // n_cols) + 1
        col = (i % n_cols) + 1
        custom = []
        for idx, rv in enumerate(ret_vals):
            if idx == best_idx and rv is not None and not pd.isna(rv):
                custom.append(f'<br>年化 {rv:.1%}')
            else:
                custom.append('')
        fig.add_trace(
            go.Bar(
                x=x_vals,
                y=y_vals,
                customdata=custom,
                marker_color=palette_years[i % len(palette_years)],
                marker_line_color=palette_years[i % len(palette_years)],
                marker_line_width=0.8,
                name=str(y),
                showlegend=False,
                hovertemplate='年份=%{legendgroup}<br>参数=%{x}<br>净值=%{y:.3f}%{customdata}<extra></extra>',
                legendgroup=str(y),
            ),
            row=row,
            col=col,
        )
        fig.update_xaxes(row=row, col=col)
        y_max = best_val if best_val is not None and best_val > 0 else None
        if y_max is None:
            valid_vals = [v for v in y_vals if v is not None]
            y_max = max(valid_vals) if valid_vals else 1.0
        padding = (y_max - 1.0) * 0.18 if y_max > 1.0 else 0.3
        upper = y_max + padding
        fig.update_yaxes(title_text='净值', row=row, col=col, range=[0, upper])
        fig.add_shape(
            type='line',
            x0=min(x_vals),
            x1=max(x_vals),
            y0=1.0,
            y1=1.0,
            line=dict(color='#555', width=1, dash='dash'),
            row=row,
            col=col,
        )
        if best_idx is not None and best_val is not None:
            bx = x_vals[best_idx]
            best_ret = series.get(bx, float('nan'))
            year_vals = series.dropna()
            if not year_vals.empty:
                ann_year_map[y] = float(year_vals.mean())
            label_y_top = best_val * 0.65 if best_val is not None else None
            label_y_bottom = best_val * 0.35 if best_val is not None else None
            fig.add_trace(
                go.Scatter(
                    x=[bx],
                    y=[best_val],
                    mode='markers',
                    marker=dict(color='#1f77b4', size=10, symbol='star'),
                    showlegend=False,
                    hoverinfo='skip',
                ),
                row=row,
                col=col,
            )
            if label_y_top is not None:
                fig.add_trace(
                    go.Scatter(
                        x=[bx],
                        y=[label_y_top],
                        mode='text',
                        text=[f'最佳 {bx}'],
                        textposition='middle center',
                        textfont=dict(color='white', size=11),
                        showlegend=False,
                        hoverinfo='skip',
                    ),
                    row=row,
                    col=col,
                )
    overall = []
    for x in x_vals:
        vals = []
        for y in years:
            v = agg[y].get(x, float('nan'))
            v2 = None if pd.isna(v) else float(1 + v)
            if v2 is not None:
                vals.append(v2)
        overall.append(float(pd.Series(vals).mean()) if vals else None)
    overall_map = {x: v for x, v in zip(x_vals, overall)}
    if overall and any(v is not None for v in overall):
        fig.add_trace(
            go.Bar(
                x=x_vals,
                y=overall,
                marker_color='#1f77b4',
                name='跨年均值',
                showlegend=True,
                hovertemplate='参数=%{x}<br>净值(均值)=%{y:.3f}<extra></extra>',
            ),
            row=n_rows,
            col=n_cols,
        )
        overall_series = pd.Series([v for v in overall if v is not None]).dropna()
        if not overall_series.empty:
            overall_mean = float(overall_series.mean())
            fig.add_annotation(
                x=min(x_vals),
                y=1.0,
                text=f'跨年均值 {overall_mean:.2f}',
                showarrow=False,
                xanchor='left',
                yanchor='bottom',
                font=dict(color='#333', size=11),
                row=n_rows,
                col=n_cols,
            )
    for i, y in enumerate(years):
        row = (i // n_cols) + 1
        col = (i % n_cols) + 1
        for x in x_vals:
            ov = overall_map.get(x)
            if ov is None:
                continue
            fig.add_trace(
                go.Scatter(
                    x=[x],
                    y=[1.02],
                    mode='text',
                    text=[f'{ov:.2f}'],
                    textposition='top center',
                    textfont=dict(color='#555', size=9),
                    showlegend=False,
                    hoverinfo='skip',
                ),
                row=row,
                col=col,
            )
    for i, y in enumerate(years):
        ann = ann_year_map.get(y)
        if ann is not None and i < len(fig.layout.annotations):
            base_title = f'{y}年 - {x_title} - 年收平均 {ann:.1%}'
            fig.layout.annotations[i].text = base_title
    fig_height = max(650, 270 * n_rows)
    fig.update_layout(
        title=title,
        height=fig_height,
        margin=dict(l=70, r=80, t=90, b=50),
        hovermode='x unified',
        template='plotly_white',
        dragmode='zoom',
        legend=dict(orientation='h', x=0.99, xanchor='right', y=1.02, yanchor='bottom'),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    import plotly.offline as po

    po.plot(fig, filename=str(output_path.resolve()), auto_open=False)


def _get_param_sheet(backtest_name_str: str) -> pd.DataFrame:
    root = get_folder_path('data', '遍历结果', backtest_name_str, path_type=True)
    return pd.read_excel(root / '策略回测参数总表.xlsx')


def _strip_prefix(col: str) -> str:
    for p in [
        '#FACTOR-',
        '#FILTER-',
        '#LONG-',
        '#SHORT-',
        '#LONG-FILTER-',
        '#SHORT-FILTER-',
        '#LONG-POST-',
        '#SHORT-POST-',
    ]:
        col = col.replace(p, '')
    return col


def _auto_pick_traversal_column(backtest_name_str: str, prefer_factor_name: str | None = None) -> str:
    df = _get_param_sheet(backtest_name_str)
    excluded = {'策略', 'fullname', 'hold_period'}
    varying = [c for c in df.columns if c not in excluded and pd.Series(df[c]).nunique(dropna=False) > 1]
    if prefer_factor_name is not None:
        for c in varying:
            if _strip_prefix(c) == prefer_factor_name:
                return c
    if len(varying) == 1:
        return varying[0]
    order = ['#LONG-', '#LONG-FILTER-', '#LONG-POST-', '#SHORT-', '#SHORT-FILTER-', '#SHORT-POST-']

    def rank(c):
        for i, p in enumerate(order):
            if c.startswith(p):
                return i
        return 999

    varying.sort(key=rank)
    return varying[0]


def generate_one_param_bars_report(
    backtest_name_str: str,
    factor_column: str | None = None,
    output_filename: str = '参数平原_单参数_柱状.html',
    title: str | None = None,
    scope: str | None = None,
):
    if factor_column is None:
        resolved = _auto_pick_traversal_column(backtest_name_str)
    else:
        resolved = _resolve_factor_column(backtest_name_str, factor_column, scope=scope)
    data, years = collect_one_param_yearly_data(backtest_name_str, resolved)
    x_title = (
        resolved.replace('#FACTOR-', '')
        .replace('#FILTER-', '')
        .replace('#LONG-', '')
        .replace('#SHORT-', '')
        .replace('#LONG-FILTER-', '')
        .replace('#SHORT-FILTER-', '')
        .replace('#LONG-POST-', '')
        .replace('#SHORT-POST-', '')
    )
    root = get_folder_path('data', '遍历结果', backtest_name_str, path_type=True)
    output_path = root / output_filename
    build_one_param_bars_html(
        data=data,
        years=years,
        title=title or f'参数平原（年度柱状）：{x_title}',
        output_path=output_path,
        x_title=x_title,
    )
    return output_path


if __name__ == '__main__':
    warnings.filterwarnings('ignore')

    pd.set_option('expand_frame_repr', False)
    pd.set_option('display.unicode.ambiguous_as_wide', True)
    pd.set_option('display.unicode.east_asian_width', True)

    print('🌀 系统启动中，稍等...')
    r_time = time.time()

    
   # 单参数示例：
    strategies = []
    param_range = range(100, 1001, 100)
    for param in param_range:
        strategy = {
            "hold_period": "8H",
            "market": "swap_swap",
            "offset_list": range(0, 8, 1), # range（起始参数，最后参数，每一次遍历的参数单位）
            "long_select_coin_num": 0.2,
            "short_select_coin_num": 0 ,
            "long_factor_list": [
                ('VWapBias', False, param, 1), # 想遍历哪个因子参数就直接把param放进去就行
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
        }
        strategies.append(strategy)


    # #多参数示例：想要遍历哪个参数就往后无限叠加即可（遍历参数越多，耗费时间越长！）
    # strategies = []
    # vwap_param_range = range(100, 1001, 100)
    # qvm_param_range = range(100, 1001, 100)
    # uptime_param_range = range(100, 1001, 100)
    # for vwap_param in vwap_param_range:
    #     for qvm_param in qvm_param_range:
    #         for uptime_param in uptime_param_range: 
    #             strategy = {
    #                 "hold_period": "8H",
    #                 "market": "swap_swap",
    #                 "offset_list": range(1),
    #                 "long_select_coin_num": 0.2,
    #                 "short_select_coin_num": 0,
    #                 "long_factor_list": [
    #                     ('VWapBias', False, vwap_param, 1),
    #                 ],
    #                     "long_filter_list": [
    #                     ('QuoteVolumeMean', qvm_param, 'pct:>=0.8'),
    #                 ],
    #                 "long_filter_list_post": [
    #                     ('UpTimeRatio', uptime_param, 'val:>=0.5'),
    #                 ],
    #                 "short_factor_list": [

    #                 ],
    #                 "short_filter_list": [

    #                 ],
    #                 "short_filter_list_post": [

    #                 ],
    #             }
    #             strategies.append(strategy)

 


    print('🌀 生成策略配置...')
    backtest_factory = create_factory(strategies)

    print('🌀 寻找最优参数...')
    report_list = find_best_params(backtest_factory)

    s_time = time.time()
    print('🌀 展示最优参数...')
    all_params_map = pd.concat(report_list, ignore_index=True)
    report_columns = all_params_map.columns

    sheet = backtest_factory.get_name_params_sheet()
    all_params_map = all_params_map.merge(sheet, left_on='param', right_on='fullname', how='left')

    all_params_map.sort_values(by='累积净值', ascending=False, inplace=True)
    all_params_map = all_params_map[[*sheet.columns, *report_columns]].drop(columns=['param'])
    all_params_map.to_excel(backtest_factory.result_folder / '最优参数.xlsx', index=False)
    print(all_params_map)
    print(f'✅ 完成展示最优参数，花费时间：{time.time() - s_time:.3f}秒，累计时间：{(time.time() - r_time):.3f}秒')
    print()

    print('🌀 生成年度参数平原柱状图...')
    param_sheet = _get_param_sheet(backtest_name)
    excluded = {'策略', 'fullname', 'hold_period'}
    varying_cols = [
        c for c in param_sheet.columns
        if c not in excluded and pd.Series(param_sheet[c]).nunique(dropna=False) > 1
    ]
    if not varying_cols:
        print('⚠️ 未检测到有变化的参数列，跳过参数平原柱状图生成')
    else:
        for col in varying_cols:
            base_name = _strip_prefix(col)
            output_filename = f'参数平原_{base_name}_柱状.html'
            chart_output = generate_one_param_bars_report(
                backtest_name,
                factor_column=col,
                output_filename=output_filename,
            )
            print(f'✅ 已生成报告（{base_name}）：{chart_output}')
