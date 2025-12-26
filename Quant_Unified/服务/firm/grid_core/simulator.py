import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import time
import sys
from pytz import timezone
from firm.backtest_core.evaluate import strategy_evaluate
from firm.backtest_core.figure import draw_equity_curve_plotly

"""
二号网格策略 - 单品种回测模拟器
这个文件负责模拟交易过程：它像放电影一样，把历史的 K 线行情一根根喂给策略，
看策略在当时会做出什么买卖操作，并统计最终赚了多少钱。
"""
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import time
import sys
from pytz import timezone
from firm.backtest_core.evaluate import strategy_evaluate
from firm.backtest_core.figure import draw_equity_curve_plotly

class 网格回测模拟器:
    def __init__(self, 配置=None):
        self.配置 = 配置
        self.策略 = None
        self.数据表 = pd.DataFrame()
        self._时间轴 = []
        self._权益曲线 = []
        self._价格轴 = []

    def 设置策略(self, 策略对象):
        """设置要运行的策略实例"""
        self.策略 = 策略对象

    def 加载数据(self, 数据表):
        """加载准备好的 K 线数据"""
        self.数据表 = 数据表

    def 运行(self):
        """开始回测主循环"""
        if self.策略 is None:
            raise ValueError("尚未设置策略，请先调用 '设置策略'。")
        
        if self.数据表.empty:
            print("未获取到数据，无法回测")
            return

        # 使用第一根 K 线的开盘价初始化策略
        self.策略.on_tick(self.数据表['candle_begin_time'].iloc[0], self.数据表['open'].iloc[0])
        self.策略.init() # 执行策略自定义的初始化逻辑

        try:
            # 打印策略预期的每格利润，方便用户直观感受参数设置是否合理
            盈利率 = self.策略.get_expected_profit_rate()
            盈利金额 = self.策略.get_expected_profit_amount()
            print(f"预计每格利润率: {盈利率:.4%} | 金额: {盈利金额:.4f}")
        except Exception:
            pass

        # 初始化爆仓追踪
        self.爆仓事件 = None

        # 核心循环：模拟时间流动
        for 索引, 行 in self.数据表.iterrows():
            当前时间 = 行['candle_begin_time']
            
            # OHLC 模拟逻辑：由于我们只有分钟 K 线，需要模拟分钟内的价格走势
            # 模拟顺序：开盘价 -> 最高/最低价 -> 收盘价
            
            # 1. 开盘价触发
            self.策略.on_tick(当前时间, 行['open'])
            if getattr(self.策略, 'is_liquidated', False) and not self.爆仓事件:
                self._记录爆仓(当前时间, 行['open'])
                break
            
            # 2. 根据阴阳线模拟最高价和最低价的到达顺序
            if 行['close'] < 行['open']:
                # 阴线：通常认为先到最高，再到最低
                self.策略.on_tick(当前时间, 行['high'])
                if getattr(self.策略, 'is_liquidated', False) and not self.爆仓事件:
                    self._记录爆仓(当前时间, 行['high'])
                    break

                self.策略.on_tick(当前时间, 行['low'])
                if getattr(self.策略, 'is_liquidated', False) and not self.爆仓事件:
                    self._记录爆仓(当前时间, 行['low'])
                    break
            else:
                # 阳线：通常认为先到最低，再到最高
                self.策略.on_tick(当前时间, 行['low'])
                if getattr(self.策略, 'is_liquidated', False) and not self.爆仓事件:
                    self._记录爆仓(当前时间, 行['low'])
                    break

                self.策略.on_tick(当前时间, 行['high'])
                if getattr(self.策略, 'is_liquidated', False) and not self.爆仓事件:
                    self._记录爆仓(当前时间, 行['high'])
                    break
                
            # 3. 收盘价触发
            self.策略.on_tick(当前时间, 行['close'])
            if getattr(self.策略, 'is_liquidated', False) and not self.爆仓事件:
                self._记录爆仓(当前时间, 行['close'])
                break
            
            # 4. K 线结束事件（如计算一些指标）
            self.策略.on_bar(行)

            # 记录当前的总资产（本金 + 已实现利润 + 浮动盈亏）
            当前权益 = self.策略.money + self.策略.account_dict.get("pair_profit", 0) + self.策略.account_dict.get("positions_profit", 0)
            self._时间轴.append(当前时间)
            self._权益曲线.append(当前权益)
            self._价格轴.append(行['close'])

        self.打印指标()
        self.生成报告()

    def _记录爆仓(self, 时间, 价格):
        self.爆仓事件 = {'time': 时间, 'price': 价格}
        self._时间轴.append(时间)
        self._权益曲线.append(0)
        self._价格轴.append(价格)

    def 打印指标(self):
        """在控制台输出回测的统计结果"""
        if not hasattr(self.策略, 'account_dict') or not hasattr(self.策略, 'money'):
            return
            
        账户 = self.策略.account_dict
        初始本金 = self.策略.money
        
        配对利润 = 账户.get("pair_profit", 0)
        持仓盈亏 = 账户.get("positions_profit", 0)
        总收益 = 配对利润 + 持仓盈亏
        
        print("-" * 30)
        print(f"回测结果摘要")
        print(f"初始资金: {初始本金}")
        print(f"最大盈利: {getattr(self.策略, 'max_profit', 0)}")
        print(f"最大净亏损(持仓+配对): {getattr(self.策略, 'max_loss', 0)}")
        print(f"配对次数: {账户.get('pairing_count', 0)}")
        print(f"已配对利润: {配对利润:+.2f} ({配对利润/初始本金*100:+.1f}%)")
        print(f"持仓盈亏: {持仓盈亏:+.2f} ({持仓盈亏/初始本金*100:+.1f}%)")
        print(f"总收益: {总收益:+.2f} ({总收益/初始本金*100:+.1f}%)")
        
        # 年化收益率 (APR) 计算
        起始时间 = pd.to_datetime(self.数据表['candle_begin_time'].iloc[0])
        结束时间 = pd.to_datetime(self.数据表['candle_begin_time'].iloc[-1])
        回测时长小时 = max(0.001, (结束时间 - 起始时间).total_seconds() / 3600)
        回测时长天 = 回测时长小时 / 24
        
        收益率 = 总收益 / 初始本金
        单利年化 = 收益率 * (365 * 24 / 回测时长小时)
        复利年化 = ((1 + 收益率) ** (365 * 24 / 回测时长小时)) - 1
        
        日均配对 = 账户.get("pairing_count", 0) / max(回测时长天, 0.001)
        
        print(f"回测时长: {回测时长小时:.2f} 小时")
        print(f"日均配对: {日均配对:.2f}")
        print(f"线性年化: {单利年化*100:.1f}%")
        print(f"复利年化: {复利年化*100:.1f}%")
        
        上移次数 = getattr(self.策略, 'upward_shift_count', 0)
        下移次数 = getattr(self.策略, 'downward_shift_count', 0)
        print(f"移动统计: 上移 {上移次数} / 下移 {下移次数} (总计 {上移次数+下移次数})")
        
        # 打印期末持仓详情
        持仓格数 = 账户.get("positions_grids", 0)
        持仓成本 = 账户.get("positions_cost", 0)
        当前价格 = self.数据表['close'].iloc[-1]
        
        print("-" * 30)
        print(f"期末持仓状态:")
        if 持仓格数 == 0:
            print("  空仓 (No Positions)")
        else:
            方向 = "多头 (LONG)" if 持仓格数 > 0 else "空头 (SHORT)"
            数量 = 账户.get("positions_qty", abs(持仓格数) * self.策略.grid_dict.get("one_grid_quantity", 0))
            数量 = abs(数量)
            
            print(f"  方向: {方向}")
            print(f"  数量: {数量:.4f} ({持仓格数} 格)")
            print(f"  均价: {持仓成本:.4f}")
            print(f"  现价: {当前价格:.4f}")
            
            盈亏标签 = "浮盈" if 持仓盈亏 >= 0 else "浮亏"
            print(f"  {盈亏标签}: {持仓盈亏:+.2f} ({持仓盈亏/初始本金*100:+.1f}%)")
        print("-" * 30)

        if self._权益曲线:
            账户数据表 = pd.DataFrame({
                'candle_begin_time': pd.to_datetime(self._时间轴),
                'equity': self._权益曲线,
                'close': self._价格轴,
            })
            账户数据表['净值'] = 账户数据表['equity'] / 初始本金
            账户数据表['涨跌幅'] = 账户数据表['净值'].pct_change()
            账户数据表['是否爆仓'] = 0
            评价结果, _, _, _ = strategy_evaluate(账户数据表, net_col='净值', pct_col='涨跌幅')
            print(f"最大回撤: {评价结果.at['最大回撤', 0]}")
            print(f"策略评价================\n{评价结果}")

    def 生成报告(self):
        """生成回测结果的 CSV 文件和交互式 HTML 资金曲线图"""
        if not self._权益曲线:
            return
        初始本金 = self.策略.money
        输出目录 = Path(self.配置.result_dir)
        输出目录.mkdir(parents=True, exist_ok=True)
        账户数据表 = pd.DataFrame({
            'candle_begin_time': pd.to_datetime(self._时间轴),
            'equity': self._权益曲线,
            'close': self._价格轴,
        })
        账户数据表['净值'] = 账户数据表['equity'] / 初始本金
        账户数据表['涨跌幅'] = 账户数据表['净值'].pct_change()
        账户数据表['是否爆仓'] = 0
        if self.爆仓事件:
            账户数据表.iloc[-1, 账户数据表.columns.get_loc('是否爆仓')] = 1
        
        # 计算最大回撤序列
        账户数据表['max_equity'] = 账户数据表['equity'].cummax()
        账户数据表['drawdown'] = (账户数据表['equity'] - 账户数据表['max_equity']) / 账户数据表['max_equity']
        
        账户数据表.to_csv(输出目录 / '资金曲线.csv', encoding='utf-8-sig', index=False)
        评价结果, 年度收益, 月度收益, 季度收益 = strategy_evaluate(账户数据表, net_col='净值', pct_col='涨跌幅')
        评价结果.to_csv(输出目录 / '策略评价.csv', encoding='utf-8-sig')
        年度收益.to_csv(输出目录 / '年度账户收益.csv', encoding='utf-8-sig')
        季度收益.to_csv(输出目录 / '季度账户收益.csv', encoding='utf-8-sig')
        月度收益.to_csv(输出目录 / '月度账户收益.csv', encoding='utf-8-sig')
        
        图表标题 = f"累积净值:{评价结果.at['累积净值', 0]}, 年化收益:{评价结果.at['年化收益', 0]}, 最大回撤:{评价结果.at['最大回撤', 0]}"

        c = self.配置
        raw_方向 = str(getattr(c, 'direction_mode', 'neutral')).lower()
        方向 = '做多' if 'long' in raw_方向 else ('做空' if 'short' in raw_方向 else '中性')

        资金信息 = f"资金:{getattr(c, 'money', 0)} | 杠杆:{getattr(c, 'leverage', 1)}倍"
        if getattr(c, 'enable_compound', False):
            资金信息 += " | 复利:开启"

        网格信息 = f"网格数:{getattr(c, 'num_steps', 0)} | 区间:{getattr(c, 'min_price', 0)}-{getattr(c, 'max_price', 0)}"
        if getattr(c, 'price_range', 0) != 0:
            网格信息 += f" (动态区间 {getattr(c, 'price_range', 0)})"

        raw_间隔模式 = str(getattr(c, 'interval_mode', 'geometric'))
        间隔模式 = '等差' if 'arithmetic' in raw_间隔模式 else '等比'
        
        平移说明 = []
        if getattr(c, 'enable_upward_shift', False): 平移说明.append('上移')
        if getattr(c, 'enable_downward_shift', False): 平移说明.append('下移')
        平移文字 = '、'.join(平移说明) if 平移说明 else '无'
        模式信息 = f"模式:{间隔模式} | 网格平移:{平移文字}"

        详情描述 = (
            f"2号网格策略 {self.策略.symbol}（{方向}）<br>"
            f"{资金信息}<br>"
            f"{网格信息}<br>"
            f"{模式信息}"
        )
        
        标注点 = []
        if self.爆仓事件:
            标注点.append({
                'time': self.爆仓事件['time'],
                'price': self.爆仓事件['price'],
                'text': '爆仓',
                'color': 'red',
                'symbol': 'x',
                'size': 20,
                'on_right_axis': True
            })

        draw_equity_curve_plotly(
            账户数据表,
            data_dict={'资金曲线': 'equity'},
            date_col='candle_begin_time',
            right_axis={'标的价格': 'close', '最大回撤': 'drawdown'},
            title=图表标题,
            desc=详情描述,
            path=输出目录 / '资金曲线.html',
            show_subplots=False,
            markers=标注点
        )

