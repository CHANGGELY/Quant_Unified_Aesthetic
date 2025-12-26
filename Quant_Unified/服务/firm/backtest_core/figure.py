"""
Quant Unified 量化交易系统
figure.py
"""

import pandas as pd
import plotly.graph_objects as go
import seaborn as sns
from matplotlib import pyplot as plt
from plotly import subplots
from plotly.offline import plot
from plotly.subplots import make_subplots
from pathlib import Path


def draw_equity_curve_plotly(df, data_dict, date_col=None, right_axis=None, pic_size=None, chg=False,
                             title=None, path=Path('data') / 'pic.html', show=True, desc=None,
                             show_subplots=False, markers=None):
    """
    绘制策略曲线
    :param df: 包含净值数据的df
    :param data_dict: 要展示的数据字典格式：｛图片上显示的名字:df中的列名｝
    :param date_col: 时间列的名字，如果为None将用索引作为时间列
    :param right_axis: 右轴数据 ｛图片上显示的名字:df中的列名｝
    :param pic_size: 图片的尺寸
    :param chg: datadict中的数据是否为涨跌幅，True表示涨跌幅，False表示净值
    :param title: 标题
    :param path: 图片路径
    :param show: 是否打开图片
    :param markers: 标记点列表，格式: [{'time': '2023-01-01 12:00', 'price': 100, 'text': 'Mark', 'color': 'red', 'symbol': 'x'}]
    :return:
    """
    if pic_size is None:
        pic_size = [1500, 800]

    draw_df = df.copy()

    # 设置时间序列
    if date_col:
        time_data = draw_df[date_col]
    else:
        time_data = draw_df.index

    # 绘制左轴数据
    # 根据是否有回撤数据决定子图结构
    has_drawdown = False
    if right_axis:
        for key in right_axis:
            col_name = right_axis[key]
            if 'drawdown' in key.lower() or '回撤' in key or 'drawdown' in col_name.lower():
                has_drawdown = True
                break
    
    # 如果有回撤，使用 2 行布局：上图（净值+价格），下图（回撤）
    if has_drawdown:
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,  # 共享 x 轴
            vertical_spacing=0.03,
            row_heights=[0.75, 0.25],  # 调整比例
            specs=[[{"secondary_y": True}], [{"secondary_y": False}]]
        )
    else:
        # 兼容旧逻辑
        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.02,
            row_heights=[0.8, 0.1, 0.1],
            specs=[[{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]]
        )

    for key in data_dict:
        if chg:
            draw_df[data_dict[key]] = (draw_df[data_dict[key]] + 1).fillna(1).cumprod()
        fig.add_trace(go.Scatter(x=time_data, y=draw_df[data_dict[key]], name=key, ), row=1, col=1)

    # 绘制右轴数据
    if right_axis:
        for key in right_axis:
            col_name = right_axis[key]
            
            # 判断是否是回撤数据
            is_drawdown = 'drawdown' in key.lower() or '回撤' in key or 'drawdown' in col_name.lower()
            
            if is_drawdown:
                # 绘制最大回撤（区域图）在子图2
                # 橙色瀑布：使用 fill='tozeroy'，数值为负
                fig.add_trace(go.Scatter(
                    x=time_data, 
                    y=draw_df[col_name], 
                    name=key, # 放在子图不需要标记右轴
                    marker_color='rgba(255, 165, 0, 0.6)', # 橙色
                    opacity=0.6, 
                    line=dict(width=0),
                    fill='tozeroy',
                ), row=2, col=1)
                fig.update_yaxes(title_text="回撤", row=2, col=1)
            else:
                # 绘制标的价格（线图）在主图右轴
                fig.add_trace(go.Scatter(
                    x=time_data, 
                    y=draw_df[col_name], 
                    name=key + '(右轴)',
                    marker_color='gray',
                    opacity=0.5, 
                    line=dict(width=1), 
                    yaxis='y2'
                ), row=1, col=1, secondary_y=True)

    if markers:
        for m in markers:
            fig.add_trace(go.Scatter(
                x=[m['time']],
                y=[m['price']],
                mode='markers+text',
                name=m.get('text', 'Marker'),
                text=[m.get('text', '')],
                textposition="top center",
                marker=dict(
                    symbol=m.get('symbol', 'x'),
                    size=m.get('size', 15),
                    color=m.get('color', 'red'),
                    line=dict(width=2, color='white')
                ),
                yaxis='y2' if m.get('on_right_axis', False) else 'y1'
            ), row=1, col=1, secondary_y=m.get('on_right_axis', False))

    if show_subplots:
        # 子图：按照 matplotlib stackplot 风格实现堆叠图
        # 最下面是多头仓位占比
        fig.add_trace(go.Scatter(
            x=time_data,
            y=draw_df['long_cum'],
            mode='lines',
            line=dict(width=0),
            fill='tozeroy',
            fillcolor='rgba(30, 177, 0, 0.6)',
            name='多头仓位占比',
            hovertemplate="多头仓位占比: %{customdata:.4f}<extra></extra>",
            customdata=draw_df['long_pos_ratio']  # 使用原始比例值
        ), row=2, col=1)

        # 中间是空头仓位占比
        fig.add_trace(go.Scatter(
            x=time_data,
            y=draw_df['short_cum'],
            mode='lines',
            line=dict(width=0),
            fill='tonexty',
            fillcolor='rgba(255, 99, 77, 0.6)',
            name='空头仓位占比',
            hovertemplate="空头仓位占比: %{customdata:.4f}<extra></extra>",
            customdata=draw_df['short_pos_ratio']  # 使用原始比例值
        ), row=2, col=1)

        # 最上面是空仓占比
        fig.add_trace(go.Scatter(
            x=time_data,
            y=draw_df['empty_cum'],
            mode='lines',
            line=dict(width=0),
            fill='tonexty',
            fillcolor='rgba(0, 46, 77, 0.6)',
            name='空仓占比',
            hovertemplate="空仓占比: %{customdata:.4f}<extra></extra>",
            customdata=draw_df['empty_ratio']  # 使用原始比例值
        ), row=2, col=1)

        # 子图：右轴绘制 long_short_ratio 曲线
        fig.add_trace(go.Scatter(
            x=time_data,
            y=draw_df['symbol_long_num'],
            name='多头选币数量',
            mode='lines',
            line=dict(color='rgba(30, 177, 0, 0.6)', width=2)
        ), row=3, col=1)

        fig.add_trace(go.Scatter(
            x=time_data,
            y=draw_df['symbol_short_num'],
            name='空头选币数量',
            mode='lines',
            line=dict(color='rgba(255, 99, 77, 0.6)', width=2)
        ), row=3, col=1)

        # 更新子图标题
        fig.update_yaxes(title_text="仓位占比", row=2, col=1)
        fig.update_yaxes(title_text="选币数量", row=3, col=1)

    fig.update_layout(template="none", width=pic_size[0], height=pic_size[1], title_text=title,
                      hovermode="x unified", hoverlabel=dict(bgcolor='rgba(255,255,255,0.5)', ),
                      font=dict(family="PingFang SC, Hiragino Sans GB, Songti SC, Arial, sans-serif", size=12),
                      annotations=[
                          dict(
                              text=desc,
                              xref='paper',
                              yref='paper',
                              x=0.5,
                              y=1.05,
                              showarrow=False,
                              font=dict(size=12, color='black'),
                              align='center',
                              bgcolor='rgba(255,255,255,0.8)',
                          )
                      ]
                      )
    fig.update_layout(
        updatemenus=[
            dict(
                buttons=[
                    dict(label="线性 y轴",
                         method="relayout",
                         args=[{"yaxis.type": "linear"}]),
                    dict(label="对数 y轴",
                         method="relayout",
                         args=[{"yaxis.type": "log"}]),
                ])],
    )
    
    # 强制显示X轴日期（解决子图隐藏日期问题）
    # 使用统一的 tickformat
    fig.update_xaxes(
        tickformat="%Y-%m-%d\n%H:%M",
        showticklabels=True,
        showspikes=True, spikemode='across+marker', spikesnap='cursor', spikedash='solid', spikethickness=1,
    )
    
    # 单独设置峰线
    fig.update_yaxes(
        showspikes=True, spikemode='across', spikesnap='cursor', spikedash='solid', spikethickness=1,
    )

    plot(figure_or_data=fig, filename=str(path.resolve()), auto_open=False)

    # 打开图片的html文件，需要判断系统的类型
    if show:
        fig.show()


def plotly_plot(draw_df: pd.DataFrame, save_dir: str, name: str):
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

    fig.update_layout(height=200 * rows, showlegend=True, title_text=name)
    fig.write_html(str((Path(save_dir) / f"{name}.html").resolve()))
    fig.show()


def mat_heatmap(draw_df: pd.DataFrame, name: str):
    sns.set()  # 设置一下展示的主题和样式
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans', 'Font 119']
    plt.title(name)  # 设置标题
    sns.heatmap(draw_df, annot=True, xticklabels=draw_df.columns, yticklabels=draw_df.index, fmt='.2f')  # 画图
    plt.show()
