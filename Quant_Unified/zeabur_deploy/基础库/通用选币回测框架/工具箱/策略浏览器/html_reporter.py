"""
邢不行™️选币框架 - HTML报告生成器
Python数字货币量化投资课程

版权所有 ©️ 邢不行
微信: xbx8662

生成策略查看器HTML报告
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict
from tqdm import tqdm
from .viewer_config import StrategyViewerConfig


class HTMLReporter:
    """HTML报告生成器"""
    
    def generate(self, periods_df: pd.DataFrame, selected_periods: pd.DataFrame,
                 kline_data_dict: dict, config: StrategyViewerConfig,
                 strategy_name: str, kline_period: str = '1h') -> str:
        """
        生成HTML报告
        
        Args:
            periods_df: 所有交易期间
            selected_periods: 筛选后的交易期间
            kline_data_dict: K线数据字典
            config: 配置对象
            strategy_name: 策略名称
            kline_period: K线周期，如'1h', '1d'
            
        Returns:
            HTML字符串
        """
        # 保存kline_period供其他方法使用
        self.kline_period = kline_period
        
        html_parts = []
        
        # 1. HTML头部
        html_parts.append(self._generate_header(strategy_name))
        
        # 2. 配置信息
        html_parts.append(self._generate_config_info(config))
        
        # 3. 汇总统计
        html_parts.append(self._generate_summary(selected_periods))
        
        # 4. 每个交易期间的详情
        for idx, row in tqdm(selected_periods.iterrows(), total=len(selected_periods), 
                             desc="生成HTML报告", ncols=80):
            chart_html = self._generate_period_detail(
                row, kline_data_dict.get(row['symbol']), config, idx
            )
            html_parts.append(chart_html)
        
        # 5. HTML尾部
        html_parts.append(self._generate_footer())
        
        return '\n'.join(html_parts)
    
    def _generate_header(self, strategy_name: str) -> str:
        """生成HTML头部"""
        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>策略查看器报告 - {strategy_name}</title>
    <script src="https://cdn.plot.ly/plotly-2.18.0.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        /* 全局样式 */
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Inter', 'Microsoft YaHei', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        
        /* 容器样式 */
        .container {{
            max-width: 1600px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
            overflow: hidden;
        }}
        
        /* 头部样式 */
        .header {{
            background: linear-gradient(135deg, #007acc 0%, #0056b3 100%);
            color: white;
            padding: 40px 30px;
            text-align: center;
            position: relative;
            overflow: hidden;
        }}
        
        .header::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            opacity: 0.3;
        }}
        
        h1 {{
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 10px;
            position: relative;
            z-index: 1;
        }}
        
        h4 {{
            font-size: 1.1rem;
            opacity: 0.9;
            font-weight: 300;
            position: relative;
            z-index: 1;
        }}
        
        /* 配置信息样式 */
        .config-info {{
            background: linear-gradient(135deg, #fff3cd 0%, #ffeeba 100%);
            border-left: 5px solid #ffc107;
            padding: 20px 25px;
            margin: 30px;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(255, 193, 7, 0.2);
        }}
        
        .config-info h5 {{
            color: #856404;
            margin-bottom: 15px;
            font-size: 1.3rem;
            font-weight: 600;
        }}
        
        .config-info .row {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }}
        
        .config-info .col-md-3 {{
            background: rgba(255, 255, 255, 0.6);
            padding: 10px 15px;
            border-radius: 8px;
            border: 1px solid rgba(133, 100, 4, 0.2);
        }}
        
        /* 汇总统计样式 */
        .summary-card {{
            background: white;
            border-radius: 15px;
            padding: 25px 30px;
            margin: 30px;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.08);
        }}
        
        .summary-card h4 {{
            color: #495057;
            margin-bottom: 20px;
            font-size: 1.5rem;
            font-weight: 600;
        }}
        
        .table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }}
        
        .table-bordered {{
            border: 1px solid #dee2e6;
        }}
        
        .table-hover tbody tr:hover {{
            background-color: #f8f9fa;
        }}
        
        .table th {{
            background-color: #f1f3f5;
            color: #495057;
            font-weight: 600;
            padding: 12px;
            text-align: left;
            border: 1px solid #dee2e6;
        }}
        
        .table td {{
            padding: 12px;
            border: 1px solid #dee2e6;
        }}
        
        /* 交易期间卡片样式 */
        .period-card {{
            background: white;
            margin: 30px;
            padding: 0;
            border-radius: 15px;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.08);
            overflow: hidden;
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }}
        
        .period-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.12);
        }}
        
        .period-header {{
            background: linear-gradient(135deg, #495057 0%, #343a40 100%);
            color: white;
            padding: 15px 30px;
            margin: 0;
        }}
        
        .period-header h4 {{
            margin: 0;
            font-size: 1.3rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        
        .period-number {{
            display: inline-block;
            background: #007acc;
            color: white;
            padding: 2px 10px;
            border-radius: 15px;
            font-size: 1rem;
            margin-right: 8px;
            font-weight: 700;
        }}
        
        .period-number-original {{
            display: inline-block;
            background: #28a745;
            color: white;
            padding: 2px 10px;
            border-radius: 15px;
            font-size: 0.85rem;
            margin-right: 15px;
            font-weight: 500;
        }}
        
        /* 标的名称居中容器 */
        .period-title {{
            flex: 1;
            text-align: center;
            padding: 0 20px;
        }}
        
        /* 交易期间信息网格 */
        .period-info-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 0;
            background: linear-gradient(135deg, #e3f2fd 0%, #f3e5f5 100%);
            padding: 20px 30px;
            border-bottom: 1px solid #e0e0e0;
        }}
        
        .info-item {{
            display: flex;
            flex-direction: column;
            padding: 0 10px;
        }}
        
        .info-label {{
            font-size: 0.85rem;
            color: #666;
            margin-bottom: 5px;
        }}
        
        .info-value {{
            font-size: 1rem;
            font-weight: 500;
            color: #333;
        }}
        
        .info-value div {{
            margin: 2px 0;
        }}
        
        /* 指标表格样式 */
        .metric-table {{
            margin: 20px 30px 30px 30px;
        }}
        
        .metric-table th {{
            background-color: #f1f3f5;
            font-weight: 600;
        }}
        
        /* 颜色样式 - 中国习惯：上涨绿色，下跌红色 */
        .positive {{
            color: #26a69a;
            font-weight: bold;
        }}
        
        .negative {{
            color: #ef5350;
            font-weight: bold;
        }}
        
        .neutral {{
            color: #6c757d;
        }}
        
        /* 徽章样式 */
        .badge {{
            display: inline-block;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.9rem;
            font-weight: 500;
        }}
        
        .badge-long {{
            background-color: #26a69a;
            color: white;
        }}
        
        .badge-short {{
            background-color: #ef5350;
            color: white;
        }}
        
        /* K线图容器样式 */
        .chart-wrapper {{
            padding: 20px 30px;
            background: #fafafa;
            position: relative;  /* 为自定义竖线提供定位参照 */
        }}
        
        /* 自定义透明悬停竖线（无背景，不遮挡K线） */
        .cursor-line {{
            position: absolute;
            top: 10px;
            bottom: 10px;
            width: 0;
            border-left: 1px dashed #000;
            pointer-events: none;
            z-index: 9;
        }}
        
        /* 响应式设计 */
        @media (max-width: 768px) {{
            body {{
                padding: 10px;
            }}
            
            .header {{
                padding: 30px 20px;
            }}
            
            h1 {{
                font-size: 2rem;
            }}
            
            .config-info .row {{
                grid-template-columns: 1fr;
            }}
        }}
        
        /* 滚动条样式 */
        ::-webkit-scrollbar {{
            width: 8px;
        }}
        
        ::-webkit-scrollbar-track {{
            background: #f1f1f1;
            border-radius: 4px;
        }}
        
        ::-webkit-scrollbar-thumb {{
            background: #007acc;
            border-radius: 4px;
        }}
        
        ::-webkit-scrollbar-thumb:hover {{
            background: #0056b3;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 策略查看器报告</h1>
            <h4>{strategy_name}</h4>
        </div>
'''
    
    def _get_chart_display_text(self, config: StrategyViewerConfig) -> str:
        """
        获取K线显示范围的文案
        
        Args:
            config: 策略查看器配置
            
        Returns:
            格式化的显示文案
        """
        kline_period_td = pd.to_timedelta(self.kline_period)
        
        if kline_period_td >= pd.Timedelta(hours=1):
            # K线周期 >= 1H：天数模式
            # ⭐ 处理chart_days为字符串的情况
            if isinstance(config.chart_days, str):
                days = 7  # 默认值
            else:
                days = config.chart_days
            return f"前后各扩展{days}天"
        
        # K线周期 < 1H：分钟级模式
        if config.chart_days == 'auto':
            return "智能模式(自适应百分比，最少50根K线)"
        
        if isinstance(config.chart_days, str) and config.chart_days.endswith('k'):
            klines_num = config.chart_days[:-1]
            return f"左右各{klines_num}根K线(固定数量模式)"
        
        # 数字：百分比模式
        percentage = int(config.chart_days)
        left_right_each = (100 - percentage) // 2
        return f"交易期占{percentage}%，左右各{left_right_each}%(百分比模式，最少50根)"
    
    def _generate_config_info(self, config: StrategyViewerConfig) -> str:
        """生成配置信息"""
        mode_map = {
            'rank': '排名模式',
            'pct': '百分比模式',
            'val': '数值范围模式',
            'symbol': '指定币种模式'
        }
        
        metric_map = {
            'return': '收益率',
            'max_drawdown': '最大回撤',
            'volatility': '波动率',
            'return_drawdown_ratio': '收益回撤比'
        }
        
        # 获取K线显示范围文案
        chart_display = self._get_chart_display_text(config)
        
        return f'''
        <div class="config-info">
            <h5>📌 筛选配置</h5>
            <div class="row">
                <div class="col-md-3"><strong>选择模式:</strong> {mode_map.get(config.selection_mode.value, config.selection_mode.value)}</div>
                <div class="col-md-3"><strong>排序指标:</strong> {metric_map.get(config.metric_type.value, config.metric_type.value)}</div>
                <div class="col-md-3"><strong>筛选参数:</strong> {config.selection_value}</div>
                <div class="col-md-3"><strong>K线显示:</strong> {chart_display}</div>
            </div>
        </div>
'''
    
    def _generate_summary(self, selected_periods: pd.DataFrame) -> str:
        """生成汇总统计"""
        if selected_periods.empty:
            return '<div class="alert alert-warning">⚠️ 无数据</div>'
        
        total_count = len(selected_periods)
        avg_return = selected_periods['return'].mean()
        win_count = (selected_periods['return'] > 0).sum()
        win_rate = win_count / total_count if total_count > 0 else 0
        avg_holding_hours = selected_periods['holding_hours'].mean()
        avg_max_dd = selected_periods['max_drawdown'].mean()
        avg_volatility = selected_periods['volatility'].mean()
        
        # 多空统计
        long_count = (selected_periods['direction'] == 'long').sum()
        short_count = (selected_periods['direction'] == 'short').sum()
        
        return_class = 'positive' if avg_return > 0 else 'negative'
        
        # ✅ 格式化平均持仓时间
        avg_holding_time_str = self._format_holding_time(avg_holding_hours)
        
        return f'''
        <div class="summary-card">
            <h4>📈 汇总统计</h4>
            <table class="table table-bordered table-hover mt-3">
                <thead>
                    <tr>
                        <th>总交易期间数</th>
                        <th>多头期间数</th>
                        <th>空头期间数</th>
                        <th>胜率</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><strong>{total_count}</strong></td>
                        <td><strong>{long_count}</strong></td>
                        <td><strong>{short_count}</strong></td>
                        <td><strong class="{return_class}">{win_rate*100:.1f}%</strong> ({win_count}胜/{total_count-win_count}负)</td>
                    </tr>
                </tbody>
            </table>
            <table class="table table-bordered table-hover mt-3">
                <thead>
                    <tr>
                        <th>平均收益率</th>
                        <th>平均最大回撤</th>
                        <th>平均波动率</th>
                        <th>平均持仓时间</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td class="{return_class}"><strong>{avg_return*100:.2f}%</strong></td>
                        <td class="negative"><strong>{avg_max_dd*100:.2f}%</strong></td>
                        <td><strong>{avg_volatility*100:.2f}%</strong></td>
                        <td><strong>{avg_holding_time_str}</strong></td>
                    </tr>
                </tbody>
            </table>
        </div>
'''
    
    def _generate_period_detail(self, period_row: pd.Series, kline_df: pd.DataFrame,
                                 config: StrategyViewerConfig, index: int) -> str:
        """生成单个交易期间的详情"""
        if kline_df is None or kline_df.empty:
            return f'<div class="alert alert-warning">⚠️ {period_row["symbol"]} 缺少K线数据</div>'
        
        # 生成K线图
        chart_div = self._generate_kline_chart(period_row, kline_df, config, index)
        
        # 生成指标表格
        metrics_table = self._generate_metrics_table(period_row)
        
        # 方向徽章
        direction_badge = f'<span class="badge badge-long">做多</span>' if period_row['direction'] == 'long' else '<span class="badge badge-short">做空</span>'
        
        # 策略收益的颜色（做多收益/做空收益）
        strategy_return_class = 'positive' if period_row['return'] > 0 else 'negative'
        
        # 实际标的收益的颜色
        if period_row['direction'] == 'long':
            actual_return_class = strategy_return_class  # 做多时，两者相同
            actual_return_value = period_row['return']
        else:
            # 做空时，实际标的收益与策略收益相反
            actual_return_value = -period_row['return']
            actual_return_class = 'positive' if actual_return_value > 0 else 'negative'
        
        return f'''
        <div class="period-card">
            <div class="period-header">
                <h4>
                    <span class="period-number">#{period_row['current_rank']}</span>
                    <span class="period-number-original">[收益榜 #{period_row['original_rank']}]</span>
                    <span class="period-title">{period_row['symbol']} ({period_row['entry_time']} - {period_row['exit_time']})</span>
                    {direction_badge}
                </h4>
            </div>
            
            <div class="period-info-grid">
                <div class="info-item">
                    <div class="info-label">进入时间:</div>
                    <div class="info-value">{period_row['entry_time']}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">退出时间:</div>
                    <div class="info-value">{period_row['exit_time']}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">持仓时长:</div>
                    <div class="info-value">{self._format_holding_time(period_row['holding_hours'])}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">收益情况:</div>
                    <div class="info-value">
                        <div class="{strategy_return_class}">{'做多收益' if period_row['direction'] == 'long' else '做空收益'}: {period_row['return']*100:.2f}%</div>
                        <div class="{actual_return_class}">实际标的收益: {actual_return_value*100:.2f}%</div>
                    </div>
                </div>
            </div>
            
            <div class="chart-wrapper" id="wrap_{index}">
                <div id="cursor_{index}" class="cursor-line" style="display:none;"></div>
                {chart_div}
            </div>
            {metrics_table}
        </div>
        
        <script>
            // 自定义悬停竖线（贯穿K线和成交量，锁定到K线中心）
            (function() {{
                var chartId = 'chart_{index}';
                var cursorId = 'cursor_{index}';
                var wrapId = 'wrap_{index}';
                var gd = document.getElementById(chartId);
                var cursorLine = document.getElementById(cursorId);
                var wrap = document.getElementById(wrapId);
                
                if (!gd) return;
                
                gd.on('plotly_hover', function(evt) {{
                    try {{
                        if (cursorLine && wrap && evt.event && typeof evt.event.clientX === 'number') {{
                            // 获取当前鼠标悬停的点信息
                            if (evt.points && evt.points.length > 0) {{
                                var point = evt.points[0];
                                if (point && point.x !== undefined) {{
                                    // 使用更可靠的方式获取x轴范围
                                    var xaxis = gd._fullLayout.xaxis;
                                    if (!xaxis || !xaxis.range || xaxis.range.length < 2) {{
                                        // 降级方案：使用鼠标位置
                                        var rect = wrap.getBoundingClientRect();
                                        var left = Math.min(Math.max(evt.event.clientX - rect.left, 0), rect.width);
                                        cursorLine.style.left = left + 'px';
                                        cursorLine.style.display = 'block';
                                        return;
                                    }}
                                    
                                    var xMin = new Date(xaxis.range[0]);
                                    var xMax = new Date(xaxis.range[1]);
                                    var xDate = new Date(point.x);
                                    
                                    // 检查时间是否在有效范围内
                                    if (xDate < xMin || xDate > xMax) {{
                                        // 使用鼠标位置
                                        var rect = wrap.getBoundingClientRect();
                                        var left = Math.min(Math.max(evt.event.clientX - rect.left, 0), rect.width);
                                        cursorLine.style.left = left + 'px';
                                        cursorLine.style.display = 'block';
                                        return;
                                    }}
                                    
                                    // 获取绘图区域的偏移和长度
                                    var xOffset = xaxis._offset;
                                    var xLength = xaxis._length;
                                    
                                    if (typeof xOffset !== 'number' || typeof xLength !== 'number' || xLength <= 0) {{
                                        // 降级方案：使用鼠标位置
                                        var rect = wrap.getBoundingClientRect();
                                        var left = Math.min(Math.max(evt.event.clientX - rect.left, 0), rect.width);
                                        cursorLine.style.left = left + 'px';
                                        cursorLine.style.display = 'block';
                                        return;
                                    }}
                                    
                                    // 计算该时间点在图表中的相对位置（0-1）
                                    var xRatio = (xDate - xMin) / (xMax - xMin);
                                    
                                    // 限制范围在 [0, 1]
                                    xRatio = Math.max(0, Math.min(1, xRatio));
                                    
                                    // 转换为实际像素位置
                                    var xPixel = xOffset + xRatio * xLength;
                                    
                                    // 设置竖线位置（相对于wrap容器）
                                    var wrapRect = wrap.getBoundingClientRect();
                                    var gdRect = gd.getBoundingClientRect();
                                    var relativeX = xPixel + (gdRect.left - wrapRect.left);
                                    
                                    // 确保竖线在合理范围内
                                    if (relativeX >= 0 && relativeX <= wrapRect.width) {{
                                        cursorLine.style.left = relativeX + 'px';
                                        cursorLine.style.display = 'block';
                                    }} else {{
                                        // 如果计算结果异常，使用鼠标位置
                                        var left = Math.min(Math.max(evt.event.clientX - wrapRect.left, 0), wrapRect.width);
                                        cursorLine.style.left = left + 'px';
                                        cursorLine.style.display = 'block';
                                    }}
                                }} else {{
                                    // 没有点信息，使用鼠标位置
                                    var rect = wrap.getBoundingClientRect();
                                    var left = Math.min(Math.max(evt.event.clientX - rect.left, 0), rect.width);
                                    cursorLine.style.left = left + 'px';
                                    cursorLine.style.display = 'block';
                                }}
                            }} else {{
                                // 如果没有point信息，使用鼠标位置
                                var rect = wrap.getBoundingClientRect();
                                var left = Math.min(Math.max(evt.event.clientX - rect.left, 0), rect.width);
                                cursorLine.style.left = left + 'px';
                                cursorLine.style.display = 'block';
                            }}
                        }}
                    }} catch (e) {{
                        // 发生错误时，尝试使用鼠标位置作为最后的降级方案
                        try {{
                            if (cursorLine && wrap && evt.event && typeof evt.event.clientX === 'number') {{
                                var rect = wrap.getBoundingClientRect();
                                var left = Math.min(Math.max(evt.event.clientX - rect.left, 0), rect.width);
                                cursorLine.style.left = left + 'px';
                                cursorLine.style.display = 'block';
                            }}
                        }} catch (e2) {{
                            // 完全失败，静默忽略
                        }}
                    }}
                }});
                
                gd.on('plotly_unhover', function() {{
                    if (cursorLine) {{ cursorLine.style.display = 'none'; }}
                }});
            }})();
        </script>
'''
    
    def _format_holding_time(self, hours: float) -> str:
        """
        格式化持仓时长
        
        根据时长大小选择合适的显示格式：
        - < 1小时: 显示分钟 (如: 45M)
        - >= 1小时且 < 24小时: 显示小时+分钟 (如: 1H30M)
        - >= 24小时: 显示天+小时 (如: 1D2H)
        """
        total_minutes = int(hours * 60)  # 转换为总分钟数
        
        if hours < 1:
            # 小于1小时，只显示分钟
            return f"{total_minutes}分钟"
        elif hours < 24:
            # 1-24小时，显示小时+分钟
            total_hours = int(hours)
            remaining_minutes = total_minutes - (total_hours * 60)
            if remaining_minutes > 0:
                return f"{total_hours}H{remaining_minutes}M ({total_minutes}分钟)"
            else:
                return f"{total_hours}H ({total_minutes}分钟)"
        else:
            # >= 24小时，显示天+小时
            total_hours = int(hours)
            days = total_hours // 24
            remaining_hours = total_hours % 24
            if remaining_hours > 0:
                return f"{days}D{remaining_hours}H ({total_hours}H)"
            else:
                return f"{days}D ({total_hours}H)"
    
    def _generate_kline_chart(self, period_row: pd.Series, kline_df: pd.DataFrame,
                              config: StrategyViewerConfig, index: int) -> str:
        """生成K线图"""
        entry_time = period_row['entry_time']
        exit_time = period_row['exit_time']
        
        # ✅ 确定显示范围（根据K线周期自动适配）
        kline_period_td = pd.to_timedelta(self.kline_period)
        
        if kline_period_td >= pd.Timedelta(hours=1):
            # K线周期 >= 1小时：按天数显示（保持原有逻辑）
            # ⭐ 处理chart_days为字符串的情况（如'auto'）
            if isinstance(config.chart_days, str):
                # 如果是字符串，使用默认值7天
                days = 7
            else:
                days = int(config.chart_days)
            
            display_start = entry_time - pd.Timedelta(days=days)
            display_end = exit_time + pd.Timedelta(days=days)
        else:
            # K线周期 < 1小时：智能显示范围
            holding_duration = exit_time - entry_time
            holding_klines = holding_duration / kline_period_td  # 交易期间K线数量
            
            if config.chart_days == 'auto':
                # ✅ 智能模式：根据持仓K线数量动态调整百分比
                if holding_klines < 10:
                    percentage = 5   # 持仓少于10根K线：使用5%（显示更多背景）
                elif holding_klines < 20:
                    percentage = 15  # 持仓10-20根K线：使用15%
                else:
                    percentage = 20  # 持仓超过20根K线：使用20%
                
                # 计算按百分比的总K线数
                total_klines = holding_klines / (percentage / 100)
                
                # ✅ 最小50根K线保底
                if total_klines < 50:
                    # 总K线不足50根，改用固定数量模式
                    expand_klines = (50 - holding_klines) / 2  # 左右平分剩余数量
                    expand_duration = expand_klines * kline_period_td
                else:
                    # 总K线充足，使用百分比模式
                    expand_multiplier = (100 - percentage) / (2 * percentage)
                    expand_duration = holding_duration * expand_multiplier
            
            elif isinstance(config.chart_days, str) and config.chart_days.endswith('k'):
                # ✅ 'k'模式：固定K线数量（如'30k'表示左右各30根K线）
                expand_klines = int(config.chart_days[:-1])
                expand_duration = expand_klines * kline_period_td
            
            else:
                # 数字模式：百分比
                percentage = int(config.chart_days)
                total_klines = holding_klines / (percentage / 100)
                
                # ✅ 添加最小50根K线保底
                if total_klines < 50:
                    # 总K线不足50根，改用固定数量模式
                    expand_klines = (50 - holding_klines) / 2  # 左右平分剩余数量
                    expand_duration = expand_klines * kline_period_td
                else:
                    # 总K线充足，使用百分比模式
                    expand_multiplier = (100 - percentage) / (2 * percentage)
                    expand_duration = holding_duration * expand_multiplier
            
            display_start = entry_time - expand_duration
            display_end = exit_time + expand_duration
        
        # 确保时间列为datetime
        if 'candle_begin_time' in kline_df.columns:
            kline_df['candle_begin_time'] = pd.to_datetime(kline_df['candle_begin_time'])
        
        # 获取显示范围的K线
        display_kline = kline_df[
            (kline_df['candle_begin_time'] >= display_start) &
            (kline_df['candle_begin_time'] <= display_end)
        ].copy()
        
        if display_kline.empty:
            return '<div class="alert alert-warning">⚠️ K线数据不足</div>'
        
        # 计算涨跌幅
        display_kline['change_pct'] = ((display_kline['close'] - display_kline['open']) / display_kline['open'] * 100).round(2)
        
        # 计算MA7和MA14
        display_kline['MA7'] = display_kline['close'].rolling(window=7, min_periods=1).mean()
        display_kline['MA14'] = display_kline['close'].rolling(window=14, min_periods=1).mean()
        
        # 创建图表
        if config.show_volume:
            fig = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.03,
                row_heights=[0.75, 0.25],
                subplot_titles=('价格', '成交量')
            )
        else:
            fig = go.Figure()
        
        # 添加K线（中国习惯：上涨绿色，下跌红色）
        fig.add_trace(
            go.Candlestick(
                x=display_kline['candle_begin_time'],
                open=display_kline['open'],
                high=display_kline['high'],
                low=display_kline['low'],
                close=display_kline['close'],
                name='K线',
                increasing_line_color='#26a69a',  # 上涨绿色
                increasing_fillcolor='#26a69a',
                decreasing_line_color='#ef5350',  # 下跌红色
                decreasing_fillcolor='#ef5350',
                line=dict(width=1),
                whiskerwidth=0.8,
                hoverinfo='none'  # 禁用默认悬停信息
            ),
            row=1, col=1
        )
        
        # 添加自定义悬停信息
        fig.add_trace(
            go.Scatter(
                x=display_kline['candle_begin_time'],
                y=display_kline['close'],
                mode='markers',
                marker=dict(size=8, opacity=0),  # 透明标记
                hoverinfo='text',
                hovertext=[f'<b>{period_row["symbol"]}</b><br>' +
                          f'时间: {row.candle_begin_time}<br>' +
                          f'开盘: {row.open:.4f}<br>' +
                          f'最高: {row.high:.4f}<br>' +
                          f'最低: {row.low:.4f}<br>' +
                          f'收盘: {row.close:.4f}<br>' +
                          f'涨跌幅: <span style="color: {"green" if row.change_pct >= 0 else "red"}">{row.change_pct:+.2f}%</span><br>' +
                          f'成交量: {row.volume:.2f}'
                          for _, row in display_kline.iterrows()],
                name='',
                showlegend=False
            ),
            row=1, col=1
        )
        
        # 添加MA7均线
        fig.add_trace(
            go.Scatter(
                x=display_kline['candle_begin_time'],
                y=display_kline['MA7'],
                mode='lines',
                name='MA7',
                line=dict(width=2, color='#ff9800'),
                hoverinfo='y+name'  # 显示MA值和名称
            ),
            row=1, col=1
        )
        
        # 添加MA14均线
        fig.add_trace(
            go.Scatter(
                x=display_kline['candle_begin_time'],
                y=display_kline['MA14'],
                mode='lines',
                name='MA14',
                line=dict(width=2, color='#2196f3'),
                hoverinfo='y+name'  # 显示MA值和名称
            ),
            row=1, col=1
        )
        
        # 添加持仓期间高亮（淡黄色）
        fig.add_vrect(
            x0=entry_time,
            x1=exit_time,
            fillcolor='rgba(255, 193, 7, 0.3)',
            layer='below',
            line_width=0,
            annotation_text="交易期间",
            annotation_position="top left",
            annotation=dict(
                font_size=10,
                font_color="orange",
                bgcolor="rgba(255,255,255,0.8)",
                bordercolor="orange",
                borderwidth=1
            ),
            row=1, col=1
        )
        
        # 添加成交量（中国习惯：上涨绿色，下跌红色）
        if config.show_volume:
            colors = ['#26a69a' if close >= open_ else '#ef5350'
                      for close, open_ in zip(display_kline['close'], display_kline['open'])]
            
            fig.add_trace(
                go.Bar(
                    x=display_kline['candle_begin_time'],
                    y=display_kline['volume'],
                    name='成交量',
                    marker_color=colors,
                    opacity=0.7,
                    showlegend=False
                ),
                row=2, col=1
            )
        
        # 布局设置
        fig.update_layout(
            xaxis_rangeslider_visible=False,
            height=600,
            hovermode='x unified',  # 统一悬停模式，所有信息合并在一个框中
            template='plotly_white',
            margin=dict(l=60, r=60, t=50, b=60),
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="top",
                y=1.0,
                xanchor="right",
                x=1,
                bgcolor='rgba(255,255,255,0.9)',
                bordercolor='#ddd',
                borderwidth=1
            ),
            font=dict(
                family="Arial, sans-serif",
                size=11,
                color="#333"
            ),
            # 全局悬浮框设置 - 非常透明，避免遮挡
            hoverlabel=dict(
                bgcolor="rgba(255,255,255,0.35)",  # 非常透明（35%不透明度）
                bordercolor="rgba(0,0,0,0)",       # 完全透明的边框
                font_size=12,
                font_family="Arial, sans-serif",
                font_color="#333",
                align="left"  # 左对齐
            )
        )
        
        # 为所有子图设置x轴 - 禁用spike避免白色背景
        if config.show_volume:
            # 为第一个子图（K线图）设置
            fig.update_xaxes(
                showgrid=True,
                gridwidth=1,
                gridcolor='rgba(128,128,128,0.2)',
                showspikes=False,  # 禁用spike，避免白色背景遮挡
                row=1, 
                col=1
            )
            # 为第二个子图（成交量图）设置
            fig.update_xaxes(
                title_text="时间",
                showgrid=True,
                gridwidth=1,
                gridcolor='rgba(128,128,128,0.2)',
                showspikes=False,  # 禁用spike，避免白色背景遮挡
                row=2, 
                col=1
            )
        else:
            fig.update_xaxes(
                title_text="时间",
                showgrid=True,
                gridwidth=1,
                gridcolor='rgba(128,128,128,0.2)',
                showspikes=False,  # 禁用spike，避免白色背景遮挡
                row=1, 
                col=1
            )
        
        fig.update_yaxes(
            title_text="价格 (USDT)",
            showgrid=True,
            gridwidth=1,
            gridcolor='rgba(128,128,128,0.2)',
            row=1, 
            col=1
        )
        
        if config.show_volume:
            fig.update_yaxes(
                title_text="成交量",
                showgrid=True,
                gridwidth=1,
                gridcolor='rgba(128,128,128,0.2)',
                row=2, 
                col=1
            )
        
        # 转换为HTML（增强配置）
        return fig.to_html(
            include_plotlyjs=False,
            div_id=f"chart_{index}",
            config={
                'displayModeBar': True,
                'displaylogo': False,
                'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
                'scrollZoom': True,
                'doubleClick': 'autosize',
                'showTips': True,
                'responsive': True
            }
        )
    
    def _generate_metrics_table(self, period_row: pd.Series) -> str:
        """生成指标表格"""
        return_class = 'positive' if period_row['return'] > 0 else 'negative'
        
        return f'''
        <table class="table table-bordered metric-table">
            <thead>
                <tr>
                    <th>收益率</th>
                    <th>最大回撤</th>
                    <th>波动率</th>
                    <th>收益回撤比</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td class="{return_class}"><strong>{period_row['return']*100:.2f}%</strong></td>
                    <td class="negative"><strong>{period_row['max_drawdown']*100:.2f}%</strong></td>
                    <td><strong>{period_row['volatility']*100:.2f}%</strong></td>
                    <td><strong>{period_row['return_drawdown_ratio']:.2f}</strong></td>
                </tr>
            </tbody>
        </table>
'''
    
    def _generate_footer(self) -> str:
        """生成HTML尾部"""
        import datetime
        return f'''
    </div>
    
    <div style="text-align: center; padding: 30px; color: rgba(255,255,255,0.8); font-size: 0.9rem;">
        <p>邢不行™️选币框架 - 策略查看器</p>
        <p style="margin-top: 10px; font-size: 0.85rem;">生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
    
    <script>
        // 全局图表增强功能
        document.addEventListener('DOMContentLoaded', function() {{
            console.log('策略查看器报告加载完成');
            
            // 图表自适应
            window.addEventListener('resize', function() {{
                const charts = document.querySelectorAll('[id^="chart_"]');
                charts.forEach(chart => {{
                    if (chart && chart.layout) {{
                        Plotly.Plots.resize(chart);
                    }}
                }});
            }});
            
            // 添加键盘快捷键（Ctrl+R 重置所有图表缩放）
            document.addEventListener('keydown', function(e) {{
                if (e.ctrlKey && e.key === 'r') {{
                    e.preventDefault();
                    const charts = document.querySelectorAll('[id^="chart_"]');
                    charts.forEach(chart => {{
                        if (chart && chart.layout) {{
                            Plotly.relayout(chart, {{
                                'xaxis.autorange': true,
                                'yaxis.autorange': true
                            }});
                        }}
                    }});
                }}
            }});
        }});
    </script>
</body>
</html>
'''

