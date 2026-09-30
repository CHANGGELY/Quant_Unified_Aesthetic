# -*- coding: utf-8 -*-
"""
邢不行｜策略分享会
选币策略框架𝓟𝓻𝓸

版权所有 ©️ 邢不行
微信: xbx1717

本代码仅供个人学习使用，未经授权不得复制、修改或用于商业用途。

Author: 邢不行
"""

import math
import platform
import subprocess
import webbrowser
import os
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional, Union
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objs as go
from plotly import subplots
from plotly.offline import plot
from plotly.subplots import make_subplots


def float_num_process(num, return_type=float, keep=2, _max=5):
    """
    针对绝对值小于1的数字进行特殊处理，保留非0的N位（N默认为2，即keep参数）
    输入  0.231  输出  0.23
    输入  0.0231  输出  0.023
    输入  0.00231  输出  0.0023
    如果前面max个都是0，直接返回0.0
    :param num: 输入的数据
    :param return_type: 返回的数据类型，默认是float
    :param keep: 需要保留的非零位数
    :param _max: 最长保留多少位
    :return:
        返回一个float或str
    """

    # 如果输入的数据是0，直接返回0.0
    if num == 0.:
        return 0.0

    # 绝对值大于1的数直接保留对应的位数输出
    if abs(num) > 1:
        return round(num, keep)
    # 获取小数点后面有多少个0
    zero_count = -int(math.log10(abs(num)))
    # 实际需要保留的位数
    keep = min(zero_count + keep, _max)

    # 如果指定return_type是float，则返回float类型的数据
    if return_type == float:
        return round(num, keep)
    # 如果指定return_type是str，则返回str类型的数据
    else:
        return str(round(num, keep))


def show_without_plot_native_show(fig, save_path: str | Path):
    save_path = save_path.absolute()
    print('⚠️ 因为新版pycharm默认开启sci-view功能，导致部分同学会在.show()的时候假死')
    print(f'因此我们会先保存HTML到: {save_path}, 然后调用默认浏览器打开')
    fig.write_html(save_path)

    """
    跨平台在默认浏览器中打开 URL 或文件
    """
    system_name = platform.system()  # 检测操作系统
    if system_name == "Darwin":  # macOS
        subprocess.run(["open", str(save_path)])
    elif system_name == "Windows":  # Windows
        # start 是 cmd 内建命令，改用 os.startfile，不经 shell，避免路径注入
        os.startfile(str(save_path))
    elif system_name == "Linux":  # Linux
        subprocess.run(["xdg-open", str(save_path)])
    else:
        # 如果不确定操作系统，尝试使用 webbrowser 模块
        webbrowser.open(save_path)


def merge_html_flexible(
        fig_list: List[str],
        html_path: Union[str, Path],
        title: Optional[str] = None,
        link_url: Optional[str] = None,
        link_text: Optional[str] = None,
        show: bool = True,
):
    """
    将多个Plotly图表合并到一个HTML文件，并允许灵活配置标题、副标题和链接

    :param fig_list: 包含Plotly图表HTML代码的列表
    :param html_path: 输出的HTML文件路径
    :param title: 主标题内容（例如"因子分析报告"）
    :param link_url: 右侧链接的URL地址
    :param link_text: 右侧链接的显示文本
    :param show: 是否自动打开HTML文件
    :return: 生成的HTML文件路径
    :raises OSError: 文件操作失败时抛出
    """

    # 构建header部分
    header_html = []
    if title:
        header_html.append(
            f'<div class="report-title">{title}</div>'
        )

    if link_url and link_text:
        header_html.append(
            f'<a href="{link_url}" class="report-link" target="_blank">{link_text} →</a>'
        )

    # 组合header部分
    header_str = ""
    if header_html:
        header_str = f'<div class="header">{"".join(header_html)}</div>'

    # 构建完整HTML内容
    html_template = f"""<!DOCTYPE html>
    <html>
    <head>
        <style>
            .header {{
                display: flex;
                justify-content: space-between;  /* 自动分配两端对齐 */
                align-items: center;
                padding: 20px 40px;  /* 横向增加内边距 */
            }}

            .figure-container {{
                width: 90%;
                margin: 20px auto;
            }}

            .report-title {{
                font-size: 20px;
                color: #2c3e50;
                margin-right: 200px
            }}

            .report-link {{
                font-size: 20px;
                text-decoration: none;
                color: #3498db;
                font-weight: 500;
                 margin-right: 300px;  /* 可选：添加右侧边距 */
            }}

            body {{
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 0;
            }}
        </style>
    </head>
    <body>
        {header_str}
        <div class="charts-wrapper">
            {"".join(f'<div class="figure-container">{fig}</div>' for fig in fig_list)}
        </div>
    </body>
    </html>
    """

    # 自动打开HTML文件
    if show:
        # 定义局部的 write_html 函数，并包装为具有 write_html 属性的对象
        def write_html(file_path: Path):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(html_template)

        wrapped_html = SimpleNamespace(write_html=write_html)
        show_without_plot_native_show(wrapped_html, Path(html_path))


def draw_params_bar_plotly(df: pd.DataFrame, title: str):
    draw_df = df.copy()
    rows = len(draw_df.columns)
    s = (1 / (rows - 1)) * 0.5
    fig = subplots.make_subplots(rows=rows, cols=1, shared_xaxes=True, shared_yaxes=True, vertical_spacing=s)

    for i, col_name in enumerate(draw_df.columns):
        trace = go.Bar(x=draw_df.index, y=draw_df[col_name], name=f"{col_name}")
        fig.add_trace(trace, i + 1, 1)
        # 更新每个子图的x轴属性
        fig.update_xaxes(showticklabels=True, row=i + 1, col=1)  # 旋转x轴标签以避免重叠

    # 更新每个子图的y轴标题
    for i, col_name in enumerate(draw_df.columns):
        fig.update_xaxes(title_text=col_name, row=i + 1, col=1)

    fig.update_layout(height=200 * rows, showlegend=True, title={
        'text': f'{title}',  # 标题文本
        'y': 0.95,
        'x': 0.5,
        'xanchor': 'center',
        'yanchor': 'top',
        'font': {'color': 'green', 'size': 20}  # 标题的颜色和大小
    }, )

    return_fig = plot(fig, include_plotlyjs=True, output_type='div')
    return return_fig


def draw_params_heatmap_plotly(df, title=''):
    """
    生成热力图
    """
    draw_df = df.copy()

    draw_df.replace(np.nan, '', inplace=True)
    # 修改temp的index和columns为str
    draw_df.index = draw_df.index.astype(str)
    draw_df.columns = draw_df.columns.astype(str)
    fig = px.imshow(
        draw_df,
        title=title,
        text_auto=True,
        color_continuous_scale='Viridis',
    )

    fig.update_layout(
        paper_bgcolor='rgba(255,255,255,1)',
        plot_bgcolor='rgba(255,255,255,1)',
        title={
            'text': f'{title}',  # 标题文本
            'y': 0.95,
            'x': 0.5,
            'xanchor': 'center',
            'yanchor': 'top',
            'font': {'color': 'green', 'size': 20}  # 标题的颜色和大小
        },
    )

    return plot(fig, include_plotlyjs=True, output_type='div')


# 绘制柱状图
def draw_bar_plotly(x, y, text_data=None, title='', pic_size=[1800, 600]):
    """
    柱状图画图函数
    :param x: 放到X轴上的数据
    :param y: 放到Y轴上的数据
    :param text_data: text说明数据
    :param title: 图标题
    :param pic_size: 图大小
    :return:
        返回柱状图
    """

    # 创建子图
    fig = make_subplots()

    y_ = y.map(float_num_process, na_action='ignore')

    if text_data is not None:
        text_values = [
            f"{x_val}<br>{text_val}"  # <br>实现换行显示
            for x_val, text_val in zip(x, text_data)
        ]
    else:
        # 仅显示数值（带千分位格式）
        text_values = [f"{x_val}" for x_val in x]

    # 添加柱状图轨迹
    fig.add_trace(go.Bar(
        x=x,  # X轴数据
        y=y,  # Y轴数据
        text=y_,  # Y轴文本
        name=x.name  # 图里名字
    ), row=1, col=1)

    # 更新X轴的tick
    fig.update_xaxes(
        tickmode='array',
        tickvals=x,
        ticktext=text_values,
    )

    # 更新布局
    fig.update_layout(
        plot_bgcolor='rgb(255, 255, 255)',  # 设置绘图区背景色
        width=pic_size[0],  # 宽度
        height=pic_size[1],  # 高度
        title={
            'text': title,  # 标题文本
            'x': 0.377,  # 标题相对于绘图区的水平位置
            'y': 0.9,  # 标题相对于绘图区的垂直位置
            'xanchor': 'center',  # 标题的水平对齐方式
            'font': {'color': 'green', 'size': 20}  # 标题的颜色和大小
        },
        xaxis=dict(domain=[0.0, 0.73]),  # 设置 X 轴的显示范围
        showlegend=True,  # 是否显示图例
        legend=dict(
            x=0.8,  # 图例相对于绘图区的水平位置
            y=1.0,  # 图例相对于绘图区的垂直位置
            bgcolor='white',  # 图例背景色
            bordercolor='gray',  # 图例边框颜色
            borderwidth=1  # 图例边框宽度
        )
    )

    # 将图表转换为 HTML 格式
    return_fig = plot(fig, include_plotlyjs=True, output_type='div')
    return return_fig


# 绘制折线图
def draw_line_plotly(x, y1, y2=pd.DataFrame(), update_xticks=False, if_log='False', title='', pic_size=[1800, 600]):
    """
    折线画图函数
    :param x: X轴数据
    :param y1: 左轴数据
    :param y2: 右轴数据
    :param update_xticks: 是否更新x轴刻度
    :param if_log: 是否需要log轴
    :param title: 图标题
    :param pic_size: 图片大小
    :return:
        返回折线图
    """

    # 创建子图
    fig = make_subplots(rows=1, cols=1, specs=[[{"secondary_y": True}]])

    # 添加折线图轨迹
    for col in y1.columns:
        fig.add_trace(
            go.Scatter(
                x=x,  # X轴数据
                y=y1[col],  # Y轴数据
                name=col,  # 图例名字
                line={'width': 2}  # 调整线宽
            ),
            row=1, col=1, secondary_y=False
        )

    if not y2.empty:
        for col in y2.columns:
            fig.add_trace(
                go.Scatter(
                    x=x,  # X轴数据
                    y=y2[col],  # 第二个Y轴的数据
                    name=col,  # 图例名字
                    line={'dash': 'dot', 'width': 2}  # 调整折现的样式，红色、点图、线宽
                ),
                row=1, col=1, secondary_y=True
            )

    # 如果是画分组持仓走势图的话，更新xticks
    if update_xticks:
        fig.update_xaxes(
            tickmode='array',
            tickvals=x
        )

    # 更新布局
    fig.update_layout(
        plot_bgcolor='rgb(255, 255, 255)',  # 设置绘图区背景色
        width=pic_size[0],
        height=pic_size[1],
        title={
            'text': f'{title}',  # 标题文本
            'y': 0.95,
            'x': 0.5,
            'xanchor': 'center',
            'yanchor': 'top',
            'font': {'color': 'green', 'size': 20}  # 标题的颜色和大小
        },
        xaxis=dict(domain=[0.0, 0.73]),  # 设置 X 轴的显示范围
        legend=dict(
            x=0.8,  # 图例相对于绘图区的水平位置
            y=1.0,  # 图例相对于绘图区的垂直位置
            bgcolor='white',  # 图例背景色
            bordercolor='gray',  # 图例边框颜色
            borderwidth=1  # 图例边框宽度
        ),
        hovermode="x unified",
        hoverlabel=dict(bgcolor='rgba(255,255,255,0.5)', )
    )
    # 添加log轴
    if if_log:
        fig.update_layout(
            updatemenus=[
                dict(
                    buttons=[
                        dict(label="线性 y轴",
                             method="relayout",
                             args=[{"yaxis.type": "linear"}]),
                        dict(label="Log y轴",
                             method="relayout",
                             args=[{"yaxis.type": "log"}]),
                    ])], )

    # 将图表转换为 HTML 格式
    return_fig = plot(fig, include_plotlyjs=True, output_type='div')

    return return_fig


def draw_coins_difference(df, data_dict, date_col=None, right_axis=None, pic_size=[1500, 800], chg=False,
                          title=None):
    """
    绘制策略曲线
    :param df: 包含净值数据的df
    :param data_dict: 要展示的数据字典格式：｛图片上显示的名字:df中的列名｝
    :param date_col: 时间列的名字，如果为None将用索引作为时间列
    :param right_axis: 右轴数据 ｛图片上显示的名字:df中的列名｝
    :param pic_size: 图片的尺寸
    :param chg: datadict中的数据是否为涨跌幅，True表示涨跌幅，False表示净值
    :param title: 标题
    :return:
    """

    draw_df = df.copy()

    # 设置时间序列
    if date_col:
        time_data = draw_df[date_col]
    else:
        time_data = draw_df.index

    # 绘制左轴数据
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    for key in list(data_dict.keys()):
        if chg:
            draw_df[data_dict[key]] = (draw_df[data_dict[key]] + 1).fillna(1).cumprod()
        if '回撤曲线' in key:
            fig.add_trace(go.Scatter(x=time_data, y=draw_df[right_axis[key]], name=key + '(右轴)',
                                     #  marker=dict(color='rgba(220, 220, 220, 0.8)'),
                                     opacity=0.1, line=dict(width=0),
                                     fill='tozeroy',
                                     yaxis='y2'))  # 标明设置一个不同于trace1的一个坐标轴
        else:
            fig.add_trace(go.Scatter(x=time_data, y=draw_df[data_dict[key]], name=key, ))
    # 绘制右轴数据
    if right_axis:
        for key in list(right_axis.keys()):
            if '回撤曲线' in key:
                fig.add_trace(go.Scatter(x=time_data, y=draw_df[right_axis[key]], name=key + '(右轴)',
                                         #  marker=dict(color='rgba(220, 220, 220, 0.8)'),
                                         opacity=0.1, line=dict(width=0),
                                         fill='tozeroy',
                                         yaxis='y2'))  # 标明设置一个不同于trace1的一个坐标轴
            else:
                fig.add_trace(go.Scatter(x=time_data, y=draw_df[right_axis[key]], name=key + '(右轴)',
                                         #  marker=dict(color='rgba(220, 220, 220, 0.8)'),
                                         yaxis='y2'))  # 标明设置一个不同于trace1的一个坐标轴

    fig.update_layout(template="none", width=pic_size[0], height=pic_size[1], title_text=title,
                      hovermode="x unified", hoverlabel=dict(bgcolor='rgba(255,255,255,0.5)', ),
                      legend=dict(x=0, y=1.2, xanchor='left', yanchor='top'),
                      title={
                          'text': f'{title}',  # 标题文本
                          'y': 0.95,
                          'x': 0.5,
                          'xanchor': 'center',
                          'yanchor': 'top',
                          'font': {'color': 'green', 'size': 20}  # 标题的颜色和大小
                      },
                      )
    fig.update_layout(
        updatemenus=[
            dict(
                buttons=[
                    dict(label="线性 y轴",
                         method="relayout",
                         args=[{"yaxis.type": "linear"}]),
                    dict(label="Log y轴",
                         method="relayout",
                         args=[{"yaxis.type": "log"}]),
                ])],
    )

    fig.update_yaxes(
        showspikes=True, spikemode='across', spikesnap='cursor', spikedash='solid', spikethickness=1,  # 峰线
    )
    fig.update_xaxes(
        showspikes=True, spikemode='across+marker', spikesnap='cursor', spikedash='solid', spikethickness=1,  # 峰线
    )

    return plot(fig, include_plotlyjs=True, output_type='div')


def draw_equity_curve_plotly(df, data_dict, date_col=None, right_axis=None, pic_size=[1500, 800], chg=False,
                             title=None):
    """
    绘制策略曲线
    :param df: 包含净值数据的df
    :param data_dict: 要展示的数据字典格式：｛图片上显示的名字:df中的列名｝
    :param date_col: 时间列的名字，如果为None将用索引作为时间列
    :param right_axis: 右轴数据 ｛图片上显示的名字:df中的列名｝
    :param pic_size: 图片的尺寸
    :param chg: datadict中的数据是否为涨跌幅，True表示涨跌幅，False表示净值
    :param title: 标题
    :return:
    """
    draw_df = df.copy()

    # 设置时间序列
    if date_col:
        time_data = draw_df[date_col]
    else:
        time_data = draw_df.index

    # 绘制左轴数据
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    for key in list(data_dict.keys()):
        if chg:
            draw_df[data_dict[key]] = (draw_df[data_dict[key]] + 1).fillna(1).cumprod()
        if '回撤曲线' in key:
            fig.add_trace(go.Scatter(x=time_data, y=draw_df[right_axis[key]], name=key + '(右轴)',
                                     #  marker=dict(color='rgba(220, 220, 220, 0.8)'),
                                     opacity=0.1, line=dict(width=0),
                                     fill='tozeroy',
                                     yaxis='y2'))  # 标明设置一个不同于trace1的一个坐标轴
        else:
            fig.add_trace(go.Scatter(x=time_data, y=draw_df[data_dict[key]], name=key, ))
    # 绘制右轴数据
    if right_axis:
        for key in list(right_axis.keys()):
            if '回撤曲线' in key:
                fig.add_trace(go.Scatter(x=time_data, y=draw_df[right_axis[key]], name=key + '(右轴)',
                                         #  marker=dict(color='rgba(220, 220, 220, 0.8)'),
                                         opacity=0.1, line=dict(width=0),
                                         fill='tozeroy',
                                         yaxis='y2'))  # 标明设置一个不同于trace1的一个坐标轴
            else:
                fig.add_trace(go.Scatter(x=time_data, y=draw_df[right_axis[key]], name=key + '(右轴)',
                                         #  marker=dict(color='rgba(220, 220, 220, 0.8)'),
                                         yaxis='y2'))  # 标明设置一个不同于trace1的一个坐标轴

    fig.update_layout(template="none", width=pic_size[0], height=pic_size[1], title_text=title,
                      hovermode="x unified",
                      hoverlabel=dict(bgcolor='rgba(255,255,255,0.5)'),
                      title={
                          'text': f'{title}',  # 标题文本
                          'y': 0.95,
                          'x': 0.5,
                          'xanchor': 'center',
                          'yanchor': 'top',
                          'font': {'color': 'green', 'size': 20}  # 标题的颜色和大小
                      },
                      updatemenus=[
                          dict(
                              buttons=[
                                  dict(label="线性 y轴",
                                       method="relayout",
                                       args=[{"yaxis.type": "linear"}]),
                                  dict(label="Log y轴",
                                       method="relayout",
                                       args=[{"yaxis.type": "log"}]),
                              ])],
                      )

    fig.update_yaxes(
        showspikes=True, spikemode='across', spikesnap='cursor', spikedash='solid', spikethickness=1,  # 峰线
    )
    fig.update_xaxes(
        showspikes=True, spikemode='across+marker', spikesnap='cursor', spikedash='solid', spikethickness=1,  # 峰线
    )

    return plot(fig, include_plotlyjs=True, output_type='div')


def draw_coins_table(draw_df, columns, title='', pic_size=[1500, 800], ):
    # 创建Plotly表格轨迹
    table_trace = go.Table(
        header=dict(
            values=columns,
            font=dict(size=15, color='white'),
            fill_color='#4a4a4a',
            # 设置列宽（单位：像素）

        ),
        cells=dict(
            values=[
                draw_df[col] for col in columns
            ],
            align="left",
            font=dict(size=15),
            height=25
        ),
        columnwidth=[1 / 7, 3 / 7, 3 / 7]
    )

    # 创建Figure并添加表格轨迹
    fig = go.Figure(data=[table_trace])

    # 添加表格标题
    fig.update_layout(
        width=pic_size[0], height=pic_size[1],
        title={
            'text': f'{title}',  # 标题文本
            'y': 0.98,
            'x': 0.5,
            'xanchor': 'center',
            'yanchor': 'top',
            'font': {'color': 'green', 'size': 20}  # 标题的颜色和大小
        },
        margin=dict(t=40, b=20)
    )

    # 转换为HTML div
    return_fig = plot(fig, include_plotlyjs=True, output_type='div')
    return return_fig
