# -*- coding: utf-8 -*-
"""
Quant Unified 量化交易系统
[统一回测可视化模块]

功能：
    为所有策略提供统一的回测图表展示，避免每个策略重复写绘图代码。
    支持权益曲线、回撤曲线、收益分布、月度热力图等多种图表。

使用方法：
    ```python
    from 基础库.common_core.backtest.可视化 import 回测可视化

    # 创建可视化器
    可视化 = 回测可视化(
        权益曲线=equity_values,
        时间序列=timestamps,
        初始资金=10000,
        显示图表=True  # 单次回测设为 True，遍历时设为 False
    )

    # 生成并展示图表
    可视化.生成报告(策略名称="8号香农策略")
    ```

开关逻辑：
    - 单次回测：默认 显示图表=True，自动打开浏览器展示
    - 批量遍历：设置 显示图表=False，只保存 HTML 文件，不打开浏览器
"""

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional, Union, List, Dict, Any
from datetime import datetime
import webbrowser
import json
import html

# Plotly 导入
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    from plotly.offline import plot as plotly_save
    import plotly.io as pio
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False
    print("⚠️ 未安装 plotly，可视化功能将不可用。运行: pip install plotly")


class 回测可视化:
    """
    统一回测可视化器
    
    这个类就像一个"成绩单美化器"：
    输入你的考试成绩（权益曲线），它会帮你做成漂亮的成绩单：
    - 画出成绩变化曲线（权益曲线）
    - 标出最差的时期（最大回撤区间）
    - 显示每月的成绩（月度收益热力图）
    """
    
    def __init__(
        self,
        权益曲线: Union[np.ndarray, List[float], pd.Series],
        时间序列: Optional[Union[np.ndarray, List, pd.DatetimeIndex]] = None,
        初始资金: float = 10000.0,
        价格序列: Optional[Union[np.ndarray, List[float]]] = None,
        显示图表: bool = True,  # 核心开关：单次回测=True，批量遍历=False
        保存路径: Optional[str] = None,
        报告参数: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化可视化器
        
        参数：
            权益曲线: 账户总资产序列
            时间序列: 每个数据点的时间戳
            初始资金: 初始本金
            价格序列: 可选，标的价格序列（用于对比）
            显示图表: 是否在浏览器中打开图表
                - True: 单次回测时使用，自动打开浏览器
                - False: 批量遍历时使用，只保存文件
            保存路径: 图表保存路径，默认为当前目录
        """
        if not HAS_PLOTLY:
            raise ImportError("请先安装 plotly: pip install plotly")
        
        self.权益 = np.array(权益曲线, dtype=np.float64)
        self.初始资金 = float(初始资金)
        self.显示图表 = 显示图表
        self.保存路径 = Path(保存路径) if 保存路径 else Path.cwd()
        self.报告参数 = 报告参数 or {}
        
        # 时间序列
        if 时间序列 is not None:
            self.时间 = pd.to_datetime(时间序列)
        else:
            self.时间 = pd.date_range(start='2021-01-01', periods=len(self.权益), freq='min')
        
        # 价格序列 (用于对比)
        self.价格 = np.array(价格序列) if 价格序列 is not None else None
        
        # 预计算指标
        self._预处理数据()

    @staticmethod
    def _格式化参数值(value: Any) -> str:
        """把任意 Python 值格式化为适合展示在 HTML 表格里的字符串（并做转义）。"""
        if value is None:
            return "None"

        if isinstance(value, float):
            # 既要好看，又要可对比：小数保留必要精度，避免科学计数法太难读
            text = f"{value:.10g}"
            return html.escape(text)

        if isinstance(value, (int, bool, str)):
            return html.escape(str(value))

        # Path / numpy / pandas / datetime 等：统一走字符串
        if isinstance(value, Path):
            return html.escape(str(value))

        if isinstance(value, (dict, list, tuple)):
            try:
                text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
            except TypeError:
                text = str(value)
            return f"<pre class='meta-pre'>{html.escape(text)}</pre>"

        return html.escape(str(value))

    def _渲染报告参数区块(self) -> str:
        """把 self.报告参数 渲染成页面顶部的参数卡片（可折叠）。"""
        if not self.报告参数:
            return ""

        rows: List[str] = []
        for k, v in self.报告参数.items():
            key = html.escape(str(k))
            val = self._格式化参数值(v)
            rows.append(f"<tr><td class='meta-k'>{key}</td><td class='meta-v'>{val}</td></tr>")

        rows_html = "\n".join(rows)
        return f"""
<section class="report-meta">
  <details open>
    <summary>⚙️ 回测配置参数</summary>
    <div class="meta-note">提示：这些参数会随每次回测一起写入本页面，方便你对比不同回测结果。</div>
    <table class="meta-table">
      <thead><tr><th>参数</th><th>值</th></tr></thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </details>
</section>
""".strip()
    
    def _预处理数据(self):
        """预处理数据，计算净值、回撤等"""
        # 净值曲线 (归一化到1)
        self.净值 = self.权益 / self.初始资金
        
        # 收益率序列
        self.收益率 = np.diff(self.权益) / self.权益[:-1]
        self.收益率 = np.concatenate([[0], self.收益率])
        
        # 累计最高净值
        self.累计最高 = np.maximum.accumulate(self.净值)
        
        # 回撤序列 (负数)
        self.回撤 = (self.净值 - self.累计最高) / self.累计最高
    
    def 生成报告(
        self,
        策略名称: str = "策略",
        显示价格: bool = True,
        **额外指标
    ) -> str:
        """
        生成完整的可视化报告
        
        参数：
            策略名称: 策略名称，显示在标题上
            显示价格: 是否在右轴显示价格曲线
            额外指标: 额外要显示的指标（如 卡玛比率=0.48）
        
        返回：
            HTML 文件路径
        """
        # 创建多子图布局
        # Row 1: 权益曲线 + 回撤 (主图，高度占比 60%)
        # Row 2: 月度收益热力图 (高度占比 40%)
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=False,
            vertical_spacing=0.12,
            row_heights=[0.65, 0.35],
            specs=[
                [{"secondary_y": True}],
                [{"type": "heatmap"}]
            ],
            subplot_titles=[
                f"📈 {策略名称} 权益曲线",
                "📅 月度收益率热力图"
            ]
        )
        
        # =============== Row 1: 权益曲线 + 回撤 ===============
        # 主线: 净值曲线
        fig.add_trace(
            go.Scatter(
                x=self.时间,
                y=self.净值,
                name="策略净值",
                mode='lines',
                line=dict(color='#2196F3', width=2),
                hovertemplate="时间: %{x}<br>净值: %{y:.4f}<extra></extra>"
            ),
            row=1, col=1, secondary_y=False
        )
        
        # 回撤填充区域
        fig.add_trace(
            go.Scatter(
                x=self.时间,
                y=self.回撤,
                name="回撤",
                mode='lines',
                line=dict(width=0),
                fill='tozeroy',
                fillcolor='rgba(255, 82, 82, 0.3)',
                hovertemplate="回撤: %{y:.2%}<extra></extra>"
            ),
            row=1, col=1, secondary_y=True
        )
        
        # 可选: 显示价格曲线
        if 显示价格 and self.价格 is not None:
            # 价格归一化
            价格归一 = self.价格 / self.价格[0]
            fig.add_trace(
                go.Scatter(
                    x=self.时间,
                    y=价格归一,
                    name="标的价格(归一)",
                    mode='lines',
                    line=dict(color='#9E9E9E', width=1, dash='dot'),
                    opacity=0.7,
                    hovertemplate="价格(归一): %{y:.4f}<extra></extra>"
                ),
                row=1, col=1, secondary_y=False
            )
        
        # =============== Row 2: 月度收益热力图 ===============
        月度数据 = self._计算月度收益()
        
        if not 月度数据.empty:
            # 转换为热力图数据
            热力图数据 = 月度数据.pivot_table(
                index='年份',
                columns='月份',
                values='收益率',
                aggfunc='sum'
            ).fillna(0)
            
            # 确保12个月都有
            for m in range(1, 13):
                if m not in 热力图数据.columns:
                    热力图数据[m] = 0
            热力图数据 = 热力图数据.reindex(columns=range(1, 13))
            
            月份名 = ['1月', '2月', '3月', '4月', '5月', '6月',
                    '7月', '8月', '9月', '10月', '11月', '12月']
            
            fig.add_trace(
                go.Heatmap(
                    z=热力图数据.values * 100,  # 转为百分比
                    x=月份名,
                    y=热力图数据.index.astype(str),
                    colorscale=[
                        [0, '#EF5350'],      # 红色 (亏损)
                        [0.5, '#FFFFFF'],    # 白色 (持平)
                        [1, '#4CAF50']       # 绿色 (盈利)
                    ],
                    zmid=0,
                    text=np.round(热力图数据.values * 100, 1),
                    texttemplate="%{text:.1f}%",
                    textfont={"size": 10},
                    hovertemplate="年: %{y}<br>月: %{x}<br>收益: %{z:.2f}%<extra></extra>",
                    colorbar=dict(
                        title="收益率(%)",
                        # titleside="right",  # 已废弃
                        y=0.15,
                        len=0.3
                    )
                ),
                row=2, col=1
            )
        
        # =============== 布局设置 ===============
        # 计算关键指标用于标题
        总收益 = (self.净值[-1] - 1) * 100
        最大回撤 = np.min(self.回撤) * 100
        
        fig.update_layout(
            title=dict(
                text=f"<b>{策略名称}</b> | 总收益: {总收益:.1f}% | 最大回撤: {最大回撤:.1f}%",
                x=0.5,
                font=dict(size=16)
            ),
            template="plotly_white",
            height=900,
            width=1400,
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            hovermode="x unified",
            font=dict(family="PingFang SC, Hiragino Sans GB, Arial", size=12),
        )
        
        # 更新 Y 轴
        fig.update_yaxes(title_text="净值", row=1, col=1, secondary_y=False)
        fig.update_yaxes(
            title_text="回撤",
            row=1, col=1,
            secondary_y=True,
            tickformat=".0%",
            range=[min(-0.6, np.min(self.回撤) * 1.2), 0.1]  # 回撤轴倒置显示更直观
        )
        
        # 更新 X 轴
        fig.update_xaxes(
            rangeslider_visible=False,
            row=1, col=1,
            showspikes=True,
            spikemode='across',
            spikesnap='cursor'
        )
        
        # =============== 保存文件 ===============
        时间戳 = datetime.now().strftime("%Y%m%d_%H%M%S")
        文件名 = f"回测报告_{策略名称}_{时间戳}.html"
        文件路径 = self.保存路径 / 文件名

        # 生成自定义 HTML：在图表上方插入「回测配置参数」
        参数区块 = self._渲染报告参数区块()
        图表HTML = pio.to_html(fig, full_html=False, include_plotlyjs=True)
        页面标题 = html.escape(f"{策略名称} 回测报告")

        页面HTML = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{页面标题}</title>
  <style>
    :root {{
      --bg: #ffffff;
      --card: #f7f8fa;
      --text: #111827;
      --muted: #6b7280;
      --border: rgba(17, 24, 39, 0.10);
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: PingFang SC, Hiragino Sans GB, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial;
    }}
    .page {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 12px 16px 24px;
    }}
    .report-meta {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 10px 12px;
      margin: 8px 0 14px;
    }}
    .report-meta summary {{
      cursor: pointer;
      font-weight: 600;
      font-size: 14px;
      user-select: none;
      outline: none;
    }}
    .meta-note {{
      margin: 8px 0 10px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }}
    .meta-table {{
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      border-radius: 10px;
      overflow: hidden;
    }}
    .meta-table th, .meta-table td {{
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
      font-size: 12px;
    }}
    .meta-table th {{
      background: rgba(17, 24, 39, 0.04);
      font-weight: 600;
      color: #374151;
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    .meta-k {{
      width: 28%;
      color: #111827;
      white-space: nowrap;
    }}
    .meta-v {{
      color: #111827;
      word-break: break-word;
    }}
    .meta-pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, Courier New, monospace;
      font-size: 11px;
      line-height: 1.45;
      color: #111827;
    }}
  </style>
</head>
<body>
  <div class="page">
    {参数区块}
    {图表HTML}
  </div>
</body>
</html>
"""

        文件路径.write_text(页面HTML, encoding="utf-8")
        
        print(f"📊 图表已保存: {文件路径}")
        
        # 根据开关决定是否打开
        if self.显示图表:
            print("🌐 正在打开浏览器...")
            webbrowser.open(f"file://{文件路径.resolve()}")
        
        return str(文件路径)
    
    def _计算月度收益(self) -> pd.DataFrame:
        """计算每月收益率"""
        df = pd.DataFrame({
            '时间': self.时间,
            '净值': self.净值
        })
        df.set_index('时间', inplace=True)
        
        # 按月重采样，取每月最后一个净值
        月度净值 = df['净值'].resample('ME').last()
        
        # 计算月度收益率
        月度收益 = 月度净值.pct_change().fillna(月度净值.iloc[0] - 1)
        
        结果 = pd.DataFrame({
            '年份': 月度收益.index.year,
            '月份': 月度收益.index.month,
            '收益率': 月度收益.values
        })
        
        return 结果


# ============== 便捷函数 ==============

def 快速生成图表(
    权益曲线: Union[np.ndarray, List[float]],
    时间序列=None,
    策略名称: str = "策略",
    显示图表: bool = True,
    初始资金: float = 10000.0,
) -> str:
    """
    快速生成回测图表的便捷函数
    
    使用方法：
        from 基础库.common_core.backtest.可视化 import 快速生成图表
        
        快速生成图表(equity_list, timestamps, "我的策略")
    """
    可视化器 = 回测可视化(
        权益曲线=权益曲线,
        时间序列=时间序列,
        初始资金=初始资金,
        显示图表=显示图表
    )
    return 可视化器.生成报告(策略名称=策略名称)


# ============== 测试代码 ==============

if __name__ == "__main__":
    print("🧪 测试统一可视化模块...")
    
    # 生成测试数据
    np.random.seed(42)
    天数 = 365 * 2
    每天周期数 = 24  # 小时级数据（减少数据量便于测试）
    总周期 = 天数 * 每天周期数
    
    # 模拟权益曲线
    收益率 = np.random.normal(0.0001, 0.005, 总周期)
    权益 = 10000 * np.cumprod(1 + 收益率)
    
    # 插入一个大回撤
    权益[int(总周期*0.3):int(总周期*0.4)] *= 0.7
    
    # 生成时间序列
    时间 = pd.date_range(start='2023-01-01', periods=总周期, freq='h')
    
    # 测试可视化
    可视化器 = 回测可视化(
        权益曲线=权益,
        时间序列=时间,
        初始资金=10000,
        显示图表=True  # 测试时打开
    )
    
    文件路径 = 可视化器.生成报告(策略名称="测试策略")
    print(f"✅ 测试完成! 文件: {文件路径}")
