"""
Quant Unified 量化交易系统
account_config.py
"""

import time
from typing import Optional, Set

import numpy as np
import pandas as pd

from core.binance.base_client import BinanceClient
from core.binance.standard_client import StandardClient
from core.model.strategy_config import StrategyConfig
from core.utils.commons import bool_str
from core.utils.dingding import send_wechat_work_msg


class AccountConfig:
    def __init__(self, name: str, **config):
        """
        初始化AccountConfig类

        参数:
        config (dict): 包含账户配置信息的字典
        """
        self.name: str = name  # 账户名称，建议用英文，不要带有特殊符号

        # 交易所API
        self.api_key: str = config.get("apiKey", "")
        self.secret: str = config.get("secret", "")

        # 策略
        self.strategy_raw: dict = config.get("strategy", {})
        self.strategy: Optional[StrategyConfig] = None
        self.strategy_short_raw: dict = config.get("strategy", {})
        self.strategy_short: Optional[StrategyConfig] = None
        self.hold_period: str = ''
        # 纯多设置
        # self.is_pure_long: bool = config.get("is_pure_long", False)
        self.select_scope_set: Set[str] = set()
        self.order_first_set: Set[str] = set()
        # 是否使用offset
        self.use_offset: bool = config.get("use_offset", False)

        # 黑名单，不参与交易的币种
        self.black_list: list = config.get("black_list", [])

        # 白名单，只参与交易的币种
        self.white_list: list = config.get("white_list", [])

        # 交易杠杆
        self.leverage: int = config.get("leverage", 1)

        # 获取多少根K线，这里跟策略日频和小时频影响。日线策略，代表999根日线k。小时策略，代表999根小时k
        self.get_kline_num: int = config.get("get_kline_num", 999)

        # 最低要求b中有多少小时的K线，需要过滤掉少于这个k线数量的比重，用于排除新币。168=7x24h
        self.min_kline_num: int = config.get("min_kline_num", 168)

        # 企业微信机器人Webhook URL
        self.wechat_webhook_url: str = config.get("wechat_webhook_url", '')

        # 现货下单最小金额限制，适当增加可以减少部分reb。默认10，不建议小于10，这会让你的下单报错，10是交易所的限制
        self.order_spot_money_limit: int = config.get("order_spot_money_limit", 10)

        # 合约下单最小金额限制，适当增加可以减少部分reb。默认5，不建议小于5，这会让你的下单报错，5是交易所的限制
        self.order_swap_money_limit: int = config.get("order_swap_money_limit", 5)

        if not all((self.api_key, self.secret)):
            print(f'⚠️配置中apiKey和secret为空')

        # 配置之外的一些变量，后续会从strategy中初始化
        self.period: str = ''
        self.is_day_period: bool = False  # 是否是天周期
        self.is_hour_period: bool = False  # 是否是小时周期

        # 初始化变量
        self.bn: Optional[BinanceClient] = None

        self.factor_col_name_list: list = []  # 因子列列名的列表
        self.factor_params_dict: dict = {}  # 因子参数字典

        self.swap_position: Optional[pd.DataFrame] = pd.DataFrame(columns=['symbol', 'symbol_type', '当前持仓量'])
        self.swap_equity: float = 0
        self.spot_position: Optional[pd.DataFrame] = pd.DataFrame(columns=['symbol', 'symbol_type', '当前持仓量'])
        self.spot_equity: float = 0
        self.spot_usdt: float = 0

        self.is_usable: bool = False  # 会在update account 的时候，判断当前账户是否可用

    def __repr__(self):
        return f"""# {self.name} 配置如下：
+ API是否设置: {bool_str(self.is_api_ok())}
+ 是否纯多: {bool_str(self.is_pure_long)}
+ 是否使用offset: {bool_str(self.use_offset)}
+ 黑名单设置: {self.black_list}
+ 白名单设置: {self.white_list}
+ 杠杆设置: {self.leverage}
+ 获取行情k线数量: {self.get_kline_num}
+ 产生信号最小K线数量: {self.min_kline_num}
+ 微信推送URL: {self.wechat_webhook_url}
+ 策略配置 ++++++++++++++++++++++++++++++++
{self.strategy}
{self.strategy_short if self.strategy_short is not None else ''}
"""

    @property
    def is_pure_long(self):
        return self.select_scope_set == {'spot'} and self.order_first_set == {'spot'}

    @property
    def use_spot(self):
        return not {'spot', 'mix'}.isdisjoint(self.select_scope_set)

    @classmethod
    def init_from_config(cls) -> 'AccountConfig':
        try:
            from config import account_config, exchange_basic_config
        except ImportError:
            raise ImportError("Could not import 'config.py'. Please ensure it exists in the python path.")
            
        cfg = cls(**account_config)
        cfg.load_strategy_config(account_config['strategy'])
        if strategy_short := account_config.get("strategy_short"):
            cfg.load_strategy_config(strategy_short, is_short=True)
        cfg.init_exchange(exchange_basic_config)

        return cfg

    def load_strategy_config(self, strategy_dict: dict, is_short=False):
        if is_short:
            self.strategy_short_raw = strategy_dict
        else:
            self.strategy_raw = strategy_dict
        strategy_dict["is_short"] = "short" if is_short else "long"
        strategy = StrategyConfig.init(**strategy_dict)

        if strategy.is_day_period:
            self.is_day_period = True
        else:
            self.is_hour_period = True

        # 缓存持仓周期的事情
        self.hold_period = strategy.hold_period.lower()

        self.select_scope_set.add(strategy.select_scope)
        self.order_first_set.add(strategy.order_first)
        if self.use_spot and self.leverage >= 2:
            print(f'现货策略不支持杠杆大于等于2的情况，请重新配置')
            exit(1)

        if strategy.long_select_coin_num == 0 and (strategy.short_select_coin_num == 0 or
                                                   strategy.short_select_coin_num == 'long_nums'):
            print('❌ 策略中的选股数量都为0，忽略此策略配置')
            exit(1)

        # 根据配置更新offset的覆盖
        if self.use_offset:
            strategy.offset_list = list(range(0, strategy.period_num, 1))

        if is_short:
            self.strategy_short = strategy
        else:
            self.strategy = strategy
        self.factor_col_name_list += strategy.factor_columns

        # 针对当前策略的因子信息，整理之后的列名信息，并且缓存到全局
        for factor_config in strategy.all_factors:
            # 添加到并行计算的缓存中
            if factor_config.name not in self.factor_params_dict:
                self.factor_params_dict[factor_config.name] = set()
            self.factor_params_dict[factor_config.name].add(factor_config.param)

        self.factor_col_name_list = list(set(self.factor_col_name_list))

    def init_exchange(self, exchange_basic_config):
        exchange_basic_config['apiKey'] = self.api_key
        exchange_basic_config['secret'] = self.secret
        # 在Exchange增加纯多标记(https://bbs.quantclass.cn/thread/36230)
        exchange_basic_config['is_pure_long'] = self.is_pure_long

        config_params = dict(
            exchange_config=exchange_basic_config,
            spot_order_money_limit=self.order_spot_money_limit,
            swap_order_money_limit=self.order_swap_money_limit,
            is_pure_long=self.is_pure_long,
            wechat_webhook_url=self.wechat_webhook_url,
        )
        self.bn = StandardClient(**config_params)

        if not self.is_api_ok():
            print("⚠️没有配置账号API信息，当前模式下无法下单！！！暂停5秒让你确认一下...")
            time.sleep(5)

    def update_account_info(self, is_only_spot_account: bool = False, is_operate: bool = False):
        self.is_usable = False
        is_simulation = False
        
        # Try to import is_debug from config, default to False if not found
        try:
            from config import is_debug
        except ImportError:
            is_debug = False
            
        if is_debug:
            print(f'🐞[DEBUG] - 不更新账户信息')
            is_simulation = True
        elif not self.is_api_ok():
            print('🚨没有配置账号API信息，不更新账户信息')
            is_simulation = True

        if is_simulation:
            print('🎲模拟下单持仓，账户余额模拟为：现货1000USDT，合约1000USDT')
            self.spot_equity = 1000
            self.swap_equity = 1000
            return

        # 是否只保留现货账户
        if is_only_spot_account and not self.use_spot:  # 如果只保留有现货交易的账户，非现货交易账户被删除
            return False

        # ===加载合约和现货的数据
        account_overview = self.bn.get_account_overview()
        # =获取U本位合约持仓
        swap_position = account_overview.get('swap_assets', {}).get('swap_position_df', pd.DataFrame())
        # =获取U本位合约账户净值(不包含未实现盈亏)
        swap_equity = account_overview.get('swap_assets', {}).get('equity', 0)

        # ===加载现货交易对的信息
        # =获取现货持仓净值(包含实现盈亏，这是现货自带的)
        spot_usdt = account_overview.get('spot_assets', {}).get('usdt', 0)
        spot_equity = account_overview.get('spot_assets', {}).get('equity', 0)
        spot_position = pd.DataFrame()
        # 判断是否使用现货实盘
        if self.use_spot:  # 如果使用现货实盘，需要读取现货交易对信息和持仓信息
            spot_position = account_overview.get('spot_assets', {}).get('spot_position_df', pd.DataFrame())
            # =小额资产转换
        else:  # 不使用现货实盘，设置现货价值为默认值0
            spot_equity = 0
            spot_usdt = 0

        print(f'合约净值(不含浮动盈亏): {swap_equity}\t现货净值: {spot_equity}\t现货的USDT:{spot_usdt}')

        # 判断当前账号是否有资金
        if swap_equity + spot_equity <= 0:
            return None

        # 判断是否需要进行账户的调整（划转，买BNB，调整页面杠杆）
        if is_operate:
            # ===设置一下页面最大杠杆
            self.bn.reset_max_leverage(max_leverage=5)

            # ===将现货中的U转到合约账户（仅普通账户的时候需要）
            if not self.is_pure_long:
                spot_equity -= round(spot_usdt - 1, 1)
                swap_equity += round(spot_usdt - 1, 1)

        self.swap_position = swap_position
        self.swap_equity = swap_equity
        self.spot_position = spot_position
        self.spot_equity = spot_equity
        self.spot_usdt = spot_usdt

        self.is_usable = True
        return dict(
            swap_position=swap_position,
            swap_equity=swap_equity,
            spot_position=spot_position,
            spot_equity=self.spot_equity,
        )

    def calc_order_amount(self, select_coin) -> pd.DataFrame:
        """
        计算实际下单量

        :param select_coin:             选币结果
        :return:

                   当前持仓量   目标持仓量  目标下单份数   实际下单量 交易模式
        AUDIOUSDT         0.0 -2891.524948          -3.0 -2891.524948     建仓
        BANDUSDT        241.1     0.000000           NaN  -241.100000     清仓
        C98USDT        -583.0     0.000000           NaN   583.000000     清仓
        ENJUSDT           0.0  1335.871133           3.0  1335.871133     建仓
        WAVESUSDT        68.4     0.000000           NaN   -68.400000     清仓
        KAVAUSDT       -181.8     0.000000           NaN   181.800000     清仓

        """
        # 更新合约持仓数据
        swap_position = self.swap_position
        swap_position.reset_index(inplace=True)
        swap_position['symbol_type'] = 'swap'

        # 更新现货持仓数据
        if self.use_spot:
            spot_position = self.spot_position
            spot_position.reset_index(inplace=True)
            spot_position['symbol_type'] = 'spot'
            current_position = pd.concat([swap_position, spot_position], ignore_index=True)
        else:
            current_position = swap_position

        # ===创建symbol_order，用来记录要下单的币种的信息
        # =创建一个空的symbol_order，里面有select_coin（选中的币）、all_position（当前持仓）中的币种
        order_df = pd.concat([
            select_coin[['symbol', 'symbol_type']],
            current_position[['symbol', 'symbol_type']]
        ], ignore_index=True)
        order_df.drop_duplicates(subset=['symbol', 'symbol_type'], inplace=True)

        order_df.set_index(['symbol', 'symbol_type'], inplace=True)
        current_position.set_index(['symbol', 'symbol_type'], inplace=True)

        # =symbol_order中更新当前持仓量
        order_df['当前持仓量'] = current_position['当前持仓量']
        order_df['当前持仓量'].fillna(value=0, inplace=True)

        # =目前持仓量当中，可能可以多空合并
        if select_coin.empty:
            order_df['目标持仓量'] = 0
        else:
            order_df['目标持仓量'] = select_coin.groupby(['symbol', 'symbol_type'])[['目标持仓量']].sum()
            order_df['目标持仓量'].fillna(value=0, inplace=True)

        # ===计算实际下单量和实际下单资金
        order_df['实际下单量'] = order_df['目标持仓量'] - order_df['当前持仓量']

        # ===计算下单的模式，清仓、建仓、调仓等
        order_df = order_df[order_df['实际下单量'] != 0]  # 过滤掉实际下当量为0的数据
        if order_df.empty:
            return order_df
        order_df.loc[order_df['目标持仓量'] == 0, '交易模式'] = '清仓'
        order_df.loc[order_df['当前持仓量'] == 0, '交易模式'] = '建仓'
        order_df['交易模式'].fillna(value='调仓', inplace=True)  # 增加或者减少原有的持仓，不会降为0

        if select_coin.empty:
            order_df['实际下单资金'] = np.nan
        else:
            select_coin.sort_values('candle_begin_time', inplace=True)
            order_df['close'] = select_coin.groupby(['symbol', 'symbol_type'])[['close']].last()
            order_df['实际下单资金'] = order_df['实际下单量'] * order_df['close']
            del order_df['close']
        order_df.reset_index(inplace=True)

        # 补全历史持仓的最新价格信息
        if order_df['实际下单资金'].isnull().any():
            symbol_swap_price = self.bn.get_swap_ticker_price_series()  # 获取合约的最新价格
            symbol_spot_price = self.bn.get_spot_ticker_price_series()  # 获取现货的最新价格

            # 获取合约中实际下单资金为nan的数据
            swap_nan = order_df.loc[(order_df['实际下单资金'].isnull()) & (order_df['symbol_type'] == 'swap')]
            if not swap_nan.empty:
                # 补充一下合约中实际下单资金为nan的币种数据，方便后续进行拆单
                for _index in swap_nan.index:
                    order_df.loc[_index, '实际下单资金'] = (
                            order_df.loc[_index, '实际下单量'] * symbol_swap_price[swap_nan.loc[_index, 'symbol']]
                    )

            # 获取现货中实际下单资金为nan的数据
            # 有些spot不存在价格，无法直接乘，eg：ethw
            spot_nan = order_df.loc[(order_df['实际下单资金'].isnull()) & (order_df['symbol_type'] == 'spot')]
            if not spot_nan.empty:
                has_price_spot = list(set(spot_nan['symbol'].to_list()) & set(symbol_spot_price.index))  # 筛选有USDT报价的现货
                spot_nan = spot_nan[spot_nan['symbol'].isin(has_price_spot)]  # 过滤掉没有USDT报价的现货，没有报价也表示卖不出去
                if not spot_nan.empty:  # 对含有报价的现货，补充 实际下单资金 数据
                    # 补充一下现货中实际下单资金为nan的币种数据，方便后续进行拆单
                    for _index in spot_nan.index:
                        order_df.loc[_index, '实际下单资金'] = (
                                order_df.loc[_index, '实际下单量'] * symbol_spot_price[spot_nan.loc[_index, 'symbol']]
                        )
                else:  # 对没有报价的现货，设置 实际下单资金 为1，进行容错
                    order_df.loc[spot_nan.index, '实际下单资金'] = 1

        return order_df

    def calc_spot_need_usdt_amount(self, select_coin, spot_order):
        """
        计算现货账号需要划转多少usdt过去
        """
        # 现货下单总资金
        spot_strategy_equity = 0 if select_coin.empty else spot_order[spot_order['实际下单资金'] > 0][
            '实际下单资金'].sum()

        # 计算现货下单总资金 与 当前现货的资金差值，需要补充（这里是多加2%的滑点）
        diff_equity = spot_strategy_equity * 1.02

        # 获取合约账户中可以划转的USDT数量
        swap_assets = self.bn.get_swap_account()  # 获取账户净值
        swap_assets = pd.DataFrame(swap_assets['assets'])
        swap_max_withdraw_amount = float(
            swap_assets[swap_assets['asset'] == 'USDT']['maxWithdrawAmount'])  # 获取可划转USDT数量
        swap_max_withdraw_amount = swap_max_withdraw_amount * 0.99  # 出于安全考虑，给合约账户预留1%的保证金

        # 计算可以划转的USDT数量
        transfer_amount = min(diff_equity, swap_max_withdraw_amount)
        # 现货需要的USDT比可划转金额要大，这里发送信息警告(前提：非纯多现货模式下)
        if not self.is_pure_long and diff_equity > swap_max_withdraw_amount:
            msg = '======警告======\n\n'
            msg += f'现货所需金额:{diff_equity:.2f}\n'
            msg += f'合约可划转金额:{swap_max_withdraw_amount:.2f}\n'
            msg += '划转资金不足，可能会造成现货下单失败！！！'
            # 重复发送五次
            for i in range(0, 5, 1):
                send_wechat_work_msg(msg, self.wechat_webhook_url)
                time.sleep(3)

        return transfer_amount

    def proceed_swap_order(self, orders_df: pd.DataFrame):
        """
        处理合约下单
        :param orders_df:    下单数据
        """
        swap_order = orders_df[orders_df['symbol_type'] == 'swap']
        # 逐批下单
        self.bn.place_swap_orders_bulk(swap_order)

    def proceed_spot_order(self, orders_df, is_only_sell=False):
        """
        处理现货下单
        :param orders_df:    下单数据
        :param is_only_sell:    是否仅仅进行卖单交易
        """
        # ===现货处理
        spot_order_df = orders_df[orders_df['symbol_type'] == 'spot']

        # 判断是否需要现货下单
        if spot_order_df.empty:  # 如果使用了现货数据实盘，则进行现货下单
            return

        # =使用twap算法拆分订单
        short_order = spot_order_df[spot_order_df['实际下单资金'] <= 0]
        long_order = spot_order_df[spot_order_df['实际下单资金'] > 0]
        # 判断是否只卖现货
        if is_only_sell:  # 如果是仅仅交易卖单
            real_order_df = short_order
        else:  # 如果是仅仅交易买单
            real_order_df = long_order

        # =现货遍历下单
        self.bn.place_spot_orders_bulk(real_order_df)

    def is_api_ok(self):
        # 判断是否配置了api
        return self.api_key and self.secret


def load_config() -> AccountConfig:
    """
    config.py中的配置信息加载到系统中
    :return: 初始化之后的配置信息
    """
    # 从配置文件中读取并初始化回测配置
    conf = AccountConfig.init_from_config()

    return conf
