"""
Quant Unified 量化交易系统
资金曲线.py

功能：
    回测核心流程：读取数据 -> 模拟交易 -> 生成资金曲线 -> 计算评价指标 -> 绘图。
"""
import time
import numba as nb
import numpy as np
import pandas as pd

from .策略评价 import 评估策略
from .绘图 import 绘制资金曲线
from .模型.配置 import 回测配置
from .仓位管理 import 仓位计算
from .回测引擎 import 回测引擎
from .工具.基础函数 import 读取最小下单量
from .工具.路径 import 获取文件路径, MIN_QTY_PATH

pd.set_option('display.max_rows', 1000)
pd.set_option('expand_frame_repr', False)


def 对齐数据维度(market_pivot_dict, symbols, candle_begin_times):
    """
    对不同维度的数据进行对齐
    :param market_pivot_dict: 原始数据，是一个dict
    :param symbols: 币种（列）
    :param candle_begin_times: 时间（行）
    :return: 对齐后的数据字典
    """
    return {k: df.loc[candle_begin_times, symbols] for k, df in market_pivot_dict.items()}


def 读取合约面值(path, symbols):
    """
    读取每个币种的最小下单量 (合约面值)
    :param path: 文件路径
    :param symbols:  币种列表
    :return: pd.Series
    """
    default_min_qty, min_qty_dict = 读取最小下单量(path)
    lot_sizes = 0.1 ** pd.Series(min_qty_dict)
    lot_sizes = lot_sizes.reindex(symbols, fill_value=0.1 ** default_min_qty)
    return lot_sizes


@nb.jit(nopython=True, boundscheck=True)
def 开始模拟(init_capital, leverage, spot_lot_sizes, swap_lot_sizes, spot_c_rate, swap_c_rate,
             spot_min_order_limit, swap_min_order_limit, min_margin_rate, spot_ratio, swap_ratio,
             spot_open_p, spot_close_p, spot_vwap1m_p, swap_open_p, swap_close_p, swap_vwap1m_p,
             funding_rates, pos_calc):
    """
    模拟交易主循环 (Numba Accelerated)
    """
    # ====================================================================================================
    # 1. 初始化回测空间
    # ====================================================================================================
    n_bars = spot_ratio.shape[0]
    n_syms_spot = spot_ratio.shape[1]
    n_syms_swap = swap_ratio.shape[1]

    start_lots_spot = np.zeros(n_syms_spot, dtype=np.int64)
    start_lots_swap = np.zeros(n_syms_swap, dtype=np.int64)
    # 现货不设置资金费
    funding_rates_spot = np.zeros(n_syms_spot, dtype=np.float64)

    turnovers = np.zeros(n_bars, dtype=np.float64)
    fees = np.zeros(n_bars, dtype=np.float64)
    equities = np.zeros(n_bars, dtype=np.float64)
    funding_fees = np.zeros(n_bars, dtype=np.float64)
    margin_rates = np.zeros(n_bars, dtype=np.float64)
    long_pos_values = np.zeros(n_bars, dtype=np.float64)
    short_pos_values = np.zeros(n_bars, dtype=np.float64)

    # ====================================================================================================
    # 2. 初始化模拟对象
    # 注意：这里 slippage_rate 传入 0.0，因为配置中的 fee_rate 已经包含滑点
    # ====================================================================================================
    sim_spot = 回测引擎(init_capital, spot_lot_sizes, spot_c_rate, 0.0, start_lots_spot, spot_min_order_limit)
    sim_swap = 回测引擎(0, swap_lot_sizes, swap_c_rate, 0.0, start_lots_swap, swap_min_order_limit)

    # ====================================================================================================
    # 3. 开始回测
    # ====================================================================================================
    for i in range(n_bars):
        """1. 模拟开盘on_open"""
        equity_spot, _, pos_value_spot = sim_spot.处理开盘(spot_open_p[i], funding_rates_spot, spot_open_p[i])
        equity_swap, funding_fee, pos_value_swap = sim_swap.处理开盘(swap_open_p[i], funding_rates[i], swap_open_p[i])

        # 当前持仓的名义价值
        position_val = np.sum(np.abs(pos_value_spot)) + np.sum(np.abs(pos_value_swap))
        if position_val < 1e-8:
            # 没有持仓
            margin_rate = 10000.0
        else:
            margin_rate = (equity_spot + equity_swap) / float(position_val)

        # 当前保证金率小于维持保证金率，爆仓 💀
        if margin_rate < min_margin_rate:
            margin_rates[i] = margin_rate
            break

        """2. 模拟开仓on_execution"""
        equity_spot, turnover_spot, fee_spot = sim_spot.处理调仓(spot_vwap1m_p[i])
        equity_swap, turnover_swap, fee_swap = sim_swap.处理调仓(swap_vwap1m_p[i])

        """3. 模拟K线结束on_close"""
        equity_spot_close, pos_value_spot_close = sim_spot.处理收盘(spot_close_p[i])
        equity_swap_close, pos_value_swap_close = sim_swap.处理收盘(swap_close_p[i])

        long_pos_value = (np.sum(pos_value_spot_close[pos_value_spot_close > 0]) +
                          np.sum(pos_value_swap_close[pos_value_swap_close > 0]))

        short_pos_value = -(np.sum(pos_value_spot_close[pos_value_spot_close < 0]) +
                            np.sum(pos_value_swap_close[pos_value_swap_close < 0]))

        # 记录数据
        funding_fees[i] = funding_fee
        equities[i] = equity_spot + equity_swap
        turnovers[i] = turnover_spot + turnover_swap
        fees[i] = fee_spot + fee_swap
        margin_rates[i] = margin_rate
        long_pos_values[i] = long_pos_value
        short_pos_values[i] = short_pos_value

        # 考虑杠杆
        equity_leveraged = (equity_spot_close + equity_swap_close) * leverage

        """4. 计算目标持仓"""
        target_lots_spot, target_lots_swap = pos_calc.计算目标持仓(equity_leveraged,
                                                                spot_close_p[i], sim_spot.当前持仓, spot_ratio[i],
                                                                swap_close_p[i], sim_swap.当前持仓, swap_ratio[i])
        # 更新目标持仓
        sim_spot.设置目标持仓(target_lots_spot)
        sim_swap.设置目标持仓(target_lots_swap)

    return equities, turnovers, fees, funding_fees, margin_rates, long_pos_values, short_pos_values


def 计算资金曲线(conf: 回测配置,
                pivot_dict_spot: dict,
                pivot_dict_swap: dict,
                df_spot_ratio: pd.DataFrame,
                df_swap_ratio: pd.DataFrame,
                show_plot: bool = True):
    """
    计算回测结果的主入口函数
    :param conf: 回测配置对象
    :param pivot_dict_spot: 现货行情数据字典
    :param pivot_dict_swap: 永续合约行情数据字典
    :param df_spot_ratio: 现货目标资金占比
    :param df_swap_ratio: 永续合约目标资金占比
    :param show_plot: 是否显示回测图
    """
    # ====================================================================================================
    # 1. 数据预检和准备数据
    # ====================================================================================================
    if len(df_spot_ratio) != len(df_swap_ratio) or np.any(df_swap_ratio.index != df_spot_ratio.index):
        raise RuntimeError(f'数据长度不一致，现货数据长度：{len(df_spot_ratio)}, 永续合约数据长度：{len(df_swap_ratio)}')

    # 开始时间列
    candle_begin_times = df_spot_ratio.index.to_series().reset_index(drop=True)

    # 获取现货和永续合约的币种，并且排序
    spot_symbols = sorted(df_spot_ratio.columns)
    swap_symbols = sorted(df_swap_ratio.columns)

    # 裁切数据
    pivot_dict_spot = 对齐数据维度(pivot_dict_spot, spot_symbols, candle_begin_times)
    pivot_dict_swap = 对齐数据维度(pivot_dict_swap, swap_symbols, candle_begin_times)

    # 读入最小下单量数据
    spot_lot_sizes = 读取合约面值(MIN_QTY_PATH / '最小下单量_spot.csv', spot_symbols)
    swap_lot_sizes = 读取合约面值(MIN_QTY_PATH / '最小下单量_swap.csv', swap_symbols)

    pos_calc = 仓位计算(spot_lot_sizes.to_numpy(), swap_lot_sizes.to_numpy())

    # ====================================================================================================
    # 2. 开始模拟交易
    # ====================================================================================================
    print('🚀 开始模拟交易...')
    s_time = time.perf_counter()
    equities, turnovers, fees, funding_fees, margin_rates, long_pos_values, short_pos_values = 开始模拟(
        init_capital=conf.initial_usdt,
        leverage=conf.leverage,
        spot_lot_sizes=spot_lot_sizes.to_numpy(),
        swap_lot_sizes=swap_lot_sizes.to_numpy(),
        spot_c_rate=conf.spot_c_rate,
        swap_c_rate=conf.swap_c_rate,
        spot_min_order_limit=float(conf.spot_min_order_limit),
        swap_min_order_limit=float(conf.swap_min_order_limit),
        min_margin_rate=conf.margin_rate,
        # 资金占比
        spot_ratio=df_spot_ratio[spot_symbols].to_numpy(),
        swap_ratio=df_swap_ratio[swap_symbols].to_numpy(),
        # 现货行情
        spot_open_p=pivot_dict_spot['open'].to_numpy(),
        spot_close_p=pivot_dict_spot['close'].to_numpy(),
        spot_vwap1m_p=pivot_dict_spot['vwap1m'].to_numpy(),
        # 合约行情
        swap_open_p=pivot_dict_swap['open'].to_numpy(),
        swap_close_p=pivot_dict_swap['close'].to_numpy(),
        swap_vwap1m_p=pivot_dict_swap['vwap1m'].to_numpy(),
        funding_rates=pivot_dict_swap['funding_rate'].to_numpy(),
        pos_calc=pos_calc,
    )
    print(f'✅ 完成模拟交易，耗时: {time.perf_counter() - s_time:.3f}秒')
    print()

    # ====================================================================================================
    # 3. 回测结果汇总，并输出相关文件
    # ====================================================================================================
    print('🌀 开始生成回测统计结果...')
    account_df = pd.DataFrame({
        'candle_begin_time': candle_begin_times,
        'equity': equities,
        'turnover': turnovers,
        'fee': fees,
        'funding_fee': funding_fees,
        'marginRatio': margin_rates,
        'long_pos_value': long_pos_values,
        'short_pos_value': short_pos_values
    })

    account_df['净值'] = account_df['equity'] / conf.initial_usdt
    account_df['涨跌幅'] = account_df['净值'].pct_change()
    account_df.loc[account_df['marginRatio'] < conf.margin_rate, '是否爆仓'] = 1
    account_df['是否爆仓'].fillna(method='ffill', inplace=True)
    account_df['是否爆仓'].fillna(value=0, inplace=True)

    # 保存结果
    result_folder = conf.获取结果文件夹()
    account_df.to_csv(result_folder / '资金曲线.csv', encoding='utf-8-sig')

    # 策略评价
    rtn, year_return, month_return, quarter_return = 评估策略(account_df, net_col='净值', pct_col='涨跌幅')
    conf.设置回测报告(rtn.T)
    rtn.to_csv(result_folder / '策略评价.csv', encoding='utf-8-sig')
    year_return.to_csv(result_folder / '年度账户收益.csv', encoding='utf-8-sig')
    quarter_return.to_csv(result_folder / '季度账户收益.csv', encoding='utf-8-sig')
    month_return.to_csv(result_folder / '月度账户收益.csv', encoding='utf-8-sig')

    if show_plot:
        # 尝试读取 BTC/ETH 数据用于绘制基准
        # 注意：这里需要确保 data/candle_data_dict.pkl 存在，或者修改获取逻辑
        candle_data_path = 获取文件路径('data', 'candle_data_dict.pkl')
        
        try:
            all_swap = pd.read_pickle(candle_data_path)
            
            # BTC 基准
            if 'BTC-USDT' in all_swap:
                btc_df = all_swap['BTC-USDT']
                account_df = pd.merge(left=account_df, right=btc_df[['candle_begin_time', 'close']], on=['candle_begin_time'], how='left')
                account_df['close'].fillna(method='ffill', inplace=True)
                account_df['BTC涨跌幅'] = account_df['close'].pct_change()
                account_df['BTC涨跌幅'].fillna(value=0, inplace=True)
                account_df['BTC资金曲线'] = (account_df['BTC涨跌幅'] + 1).cumprod()
                del account_df['close'], account_df['BTC涨跌幅']
            
            # ETH 基准
            if 'ETH-USDT' in all_swap:
                eth_df = all_swap['ETH-USDT']
                account_df = pd.merge(left=account_df, right=eth_df[['candle_begin_time', 'close']], on=['candle_begin_time'], how='left')
                account_df['close'].fillna(method='ffill', inplace=True)
                account_df['ETH涨跌幅'] = account_df['close'].pct_change()
                account_df['ETH涨跌幅'].fillna(value=0, inplace=True)
                account_df['ETH资金曲线'] = (account_df['ETH涨跌幅'] + 1).cumprod()
                del account_df['close'], account_df['ETH涨跌幅']
                
        except Exception as e:
            print(f'⚠️ 无法读取基准数据，跳过绘制 BTC/ETH 曲线: {e}')

        print(f"🎯 策略评价================\n{rtn}")
        print(f"🗓️ 分年收益率================\n{year_return}")
        print(f'💰 总手续费: {account_df["fee"].sum():,.2f}USDT')
        print()

        print('🌀 开始绘制资金曲线...')
        
        # 准备绘图数据
        account_df['long_pos_ratio'] = account_df['long_pos_value'] / account_df['equity']
        account_df['short_pos_ratio'] = account_df['short_pos_value'] / account_df['equity']
        account_df['empty_ratio'] = (conf.leverage - account_df['long_pos_ratio'] - account_df['short_pos_ratio']).clip(lower=0)
        
        account_df['long_cum'] = account_df['long_pos_ratio']
        account_df['short_cum'] = account_df['long_pos_ratio'] + account_df['short_pos_ratio']
        account_df['empty_cum'] = conf.leverage  # 空仓占比始终为 1（顶部） - 实际是堆叠图的顶部

        # 选币数量
        df_swap_ratio = df_swap_ratio * conf.leverage
        df_spot_ratio = df_spot_ratio * conf.leverage

        symbol_long_num = df_spot_ratio[df_spot_ratio > 0].count(axis=1) + df_swap_ratio[df_swap_ratio > 0].count(axis=1)
        account_df['symbol_long_num'] = symbol_long_num.values
        symbol_short_num = df_spot_ratio[df_spot_ratio < 0].count(axis=1) + df_swap_ratio[df_swap_ratio < 0].count(axis=1)
        account_df['symbol_short_num'] = symbol_short_num.values

        # 生成画图数据字典
        data_dict = {'多空资金曲线': '净值'}
        if 'BTC资金曲线' in account_df.columns:
            data_dict['BTC资金曲线'] = 'BTC资金曲线'
        if 'ETH资金曲线' in account_df.columns:
            data_dict['ETH资金曲线'] = 'ETH资金曲线'
            
        right_axis = {'多空最大回撤': '净值dd2here'}

        pic_title = f"CumNetVal:{rtn.at['累积净值', 0]}, Annual:{rtn.at['年化收益', 0]}, MaxDrawdown:{rtn.at['最大回撤', 0]}"
        pic_desc = conf.获取全名()
        
        # 调用画图函数
        绘制资金曲线(account_df, data_dict=data_dict, date_col='candle_begin_time', right_axis=right_axis,
                     title=pic_title, desc=pic_desc, path=result_folder / '资金曲线.html',
                     show_subplots=True)

# Alias
calc_equity = 计算资金曲线
