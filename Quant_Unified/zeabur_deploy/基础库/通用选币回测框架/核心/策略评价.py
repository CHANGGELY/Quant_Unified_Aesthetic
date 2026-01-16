"""
Quant Unified 量化交易系统
策略评价.py

功能：
    计算策略回测的各项评价指标（年化、回撤、夏普等）。
"""
import itertools

import numpy as np
import pandas as pd


def 评估策略(equity, net_col='多空资金曲线', pct_col='本周期多空涨跌幅'):
    """
    回测评价函数
    :param equity: 资金曲线数据
    :param net_col: 资金曲线列名
    :param pct_col: 周期涨跌幅列名
    :return:
    """
    # ===新建一个dataframe保存回测指标
    results = pd.DataFrame()

    # 将数字转为百分数
    def num_to_pct(value):
        return '%.2f%%' % (value * 100)

    # ===计算累积净值
    results.loc[0, '累积净值'] = round(equity[net_col].iloc[-1], 2)

    # ===计算年化收益
    if len(equity) > 1:
        time_span_days = (equity['candle_begin_time'].iloc[-1] - equity['candle_begin_time'].iloc[0]).days
        time_span_seconds = (equity['candle_begin_time'].iloc[-1] - equity['candle_begin_time'].iloc[0]).seconds
        total_days = time_span_days + time_span_seconds / 86400
        if total_days > 0:
            annual_return = (equity[net_col].iloc[-1]) ** (365 / total_days) - 1
        else:
            annual_return = 0
    else:
        annual_return = 0
        
    results.loc[0, '年化收益'] = num_to_pct(annual_return)

    # ===计算最大回撤
    # 计算当日之前的资金曲线的最高点
    col_max2here = f'{net_col.split("资金曲线")[0]}max2here'
    col_dd2here = f'{net_col.split("资金曲线")[0]}dd2here'
    
    equity[col_max2here] = equity[net_col].expanding().max()
    # 计算到历史最高值到当日的跌幅
    equity[col_dd2here] = equity[net_col] / equity[col_max2here] - 1
    
    # 计算最大回撤，以及最大回撤结束时间
    sorted_dd = equity.sort_values(by=[col_dd2here])
    end_date, max_draw_down = sorted_dd.iloc[0][['candle_begin_time', col_dd2here]]
    
    # 计算最大回撤开始时间
    start_date = equity[equity['candle_begin_time'] <= end_date].sort_values(by=net_col, ascending=False).iloc[0]['candle_begin_time']
    
    results.loc[0, '最大回撤'] = num_to_pct(max_draw_down)
    results.loc[0, '最大回撤开始时间'] = str(start_date)
    results.loc[0, '最大回撤结束时间'] = str(end_date)
    
    # ===年化收益/回撤比
    if max_draw_down != 0:
        results.loc[0, '年化收益/回撤比'] = round(annual_return / abs(max_draw_down), 2)
    else:
        results.loc[0, '年化收益/回撤比'] = float('inf')

    # ===统计每个周期
    results.loc[0, '盈利周期数'] = len(equity.loc[equity[pct_col] > 0])  # 盈利笔数
    results.loc[0, '亏损周期数'] = len(equity.loc[equity[pct_col] <= 0])  # 亏损笔数
    results.loc[0, '胜率'] = num_to_pct(results.loc[0, '盈利周期数'] / len(equity))  # 胜率
    results.loc[0, '每周期平均收益'] = num_to_pct(equity[pct_col].mean())  # 每笔交易平均盈亏
    
    avg_win = equity.loc[equity[pct_col] > 0][pct_col].mean()
    avg_loss = equity.loc[equity[pct_col] <= 0][pct_col].mean()
    
    if avg_loss != 0 and not np.isnan(avg_loss):
        results.loc[0, '盈亏收益比'] = round(avg_win / avg_loss * (-1), 2)  # 盈亏比
    else:
        results.loc[0, '盈亏收益比'] = float('inf')

    if '是否爆仓' in equity.columns and 1 in equity['是否爆仓'].to_list():
        results.loc[0, '盈亏收益比'] = 0
        
    results.loc[0, '单周期最大盈利'] = num_to_pct(equity[pct_col].max())  # 单笔最大盈利
    results.loc[0, '单周期大亏损'] = num_to_pct(equity[pct_col].min())  # 单笔最大亏损

    # ===连续盈利亏损
    def get_max_consecutive(condition_series):
        if len(condition_series) == 0:
            return 0
        return max([len(list(v)) for k, v in itertools.groupby(np.where(condition_series, 1, np.nan))])

    results.loc[0, '最大连续盈利周期数'] = get_max_consecutive(equity[pct_col] > 0)
    results.loc[0, '最大连续亏损周期数'] = get_max_consecutive(equity[pct_col] <= 0)

    # ===其他评价指标
    results.loc[0, '收益率标准差'] = num_to_pct(equity[pct_col].std())

    # ===每年、每月收益率
    temp = equity.copy()
    temp.set_index('candle_begin_time', inplace=True)
    year_return = temp[[pct_col]].resample(rule='A').apply(lambda x: (1 + x).prod() - 1)
    month_return = temp[[pct_col]].resample(rule='M').apply(lambda x: (1 + x).prod() - 1)
    quarter_return = temp[[pct_col]].resample(rule='Q').apply(lambda x: (1 + x).prod() - 1)

    def num2pct(x):
        if str(x) != 'nan':
            return str(round(x * 100, 2)) + '%'
        else:
            return x

    year_return['涨跌幅'] = year_return[pct_col].apply(num2pct)
    month_return['涨跌幅'] = month_return[pct_col].apply(num2pct)
    quarter_return['涨跌幅'] = quarter_return[pct_col].apply(num2pct)

    return results.T, year_return, month_return, quarter_return

# Alias for compatibility if needed, or just use the Chinese one
strategy_evaluate = 评估策略
