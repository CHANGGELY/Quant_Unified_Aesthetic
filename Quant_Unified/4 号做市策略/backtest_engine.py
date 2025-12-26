"""
回测引擎模块，用于执行策略回测
"""
import logging
import pandas as pd
import numpy as np
import traceback
import time
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
import json
from ..models import Strategy, Backtest, BacktestTrade, TradingPair, KlineData
from .data_fetcher import data_fetcher

logger = logging.getLogger(__name__)

class Position:
    """持仓类，用于跟踪交易持仓状态"""
    
    def __init__(self, symbol, position_side='long'):
        """
        初始化持仓
        
        参数:
            symbol (str): 交易对符号
            position_side (str): 持仓方向，'long'或'short'
        """
        self.symbol = symbol
        self.position_side = position_side
        self.quantity = Decimal('0')  # 持仓数量
        self.entry_price = Decimal('0')  # 开仓均价
        self.realized_pnl = Decimal('0')  # 已实现盈亏
        
    def open_position(self, price, quantity, commission_rate=Decimal('0.0004')):
        """
        开仓
        
        参数:
            price (Decimal): 开仓价格
            quantity (Decimal): 开仓数量
            commission_rate (Decimal): 手续费率，默认0.04%
        
        返回:
            Decimal: 手续费
        """
        if self.position_side == 'long':
            side = 'buy'
        else:
            side = 'sell'
            
        # 如果已有持仓，计算加权平均价格
        if self.quantity > 0:
            total_cost = self.entry_price * self.quantity
            new_cost = price * quantity
            total_quantity = self.quantity + quantity
            self.entry_price = (total_cost + new_cost) / total_quantity
        else:
            self.entry_price = price
        
        self.quantity += quantity
        
        # 计算手续费
        commission = price * quantity * commission_rate
        
        return commission
    
    def close_position(self, price, quantity=None, commission_rate=Decimal('0.0004')):
        """
        平仓
        
        参数:
            price (Decimal): 平仓价格
            quantity (Decimal): 平仓数量，默认为None表示全部平仓
            commission_rate (Decimal): 手续费率，默认0.04%
        
        返回:
            tuple: (已实现盈亏, 手续费)
        """
        if self.quantity == 0:
            return Decimal('0'), Decimal('0')
        
        # 如果未指定数量或数量大于持仓，则全部平仓
        if quantity is None or quantity >= self.quantity:
            quantity = self.quantity
        
        # 计算盈亏和手续费
        if self.position_side == 'long':
            pnl = (price - self.entry_price) * quantity
        else:
            pnl = (self.entry_price - price) * quantity
        
        # 计算手续费
        commission = price * quantity * commission_rate
        
        # 更新持仓
        self.quantity -= quantity
        self.realized_pnl += pnl
        
        # 如果全部平仓，重置入场价格
        if self.quantity == 0:
            self.entry_price = Decimal('0')
        
        return pnl, commission
    
    def get_unrealized_pnl(self, current_price):
        """
        计算未实现盈亏
        
        参数:
            current_price (Decimal): 当前价格
        
        返回:
            Decimal: 未实现盈亏
        """
        if self.quantity == 0:
            return Decimal('0')
        
        if self.position_side == 'long':
            return (current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - current_price) * self.quantity
    
    def get_position_value(self, current_price):
        """
        计算持仓市值
        
        参数:
            current_price (Decimal): 当前价格
        
        返回:
            Decimal: 持仓市值
        """
        return self.quantity * current_price


class Account:
    """账户类，用于跟踪资金状态"""
    
    def __init__(self, initial_capital=Decimal('10000')):
        """
        初始化账户
        
        参数:
            initial_capital (Decimal): 初始资金
        """
        self.initial_capital = initial_capital
        self.balance = initial_capital  # 可用余额
        self.positions = {}  # 持仓，格式：{symbol: Position}
        self.trades = []  # 交易记录
    
    def get_position(self, symbol, position_side='long'):
        """
        获取持仓
        
        参数:
            symbol (str): 交易对符号
            position_side (str): 持仓方向，'long'或'short'
        
        返回:
            Position: 持仓对象
        """
        position_key = f"{symbol}_{position_side}"
        if position_key not in self.positions:
            self.positions[position_key] = Position(symbol, position_side)
        return self.positions[position_key]
    
    def open_position(self, symbol, price, quantity, position_side='long', time=None):
        """
        开仓
        
        参数:
            symbol (str): 交易对符号
            price (Decimal): 开仓价格
            quantity (Decimal): 开仓数量
            position_side (str): 持仓方向，'long'或'short'
            time (datetime): 开仓时间
        
        返回:
            bool: 是否开仓成功
        """
        # 验证资金是否足够
        required_capital = price * quantity
        if required_capital > self.balance:
            logger.warning(f"资金不足，需要 {required_capital}，可用 {self.balance}")
            return False
        
        # 获取持仓
        position = self.get_position(symbol, position_side)
        
        # 开仓
        commission = position.open_position(price, quantity)
        
        # 更新余额
        self.balance -= required_capital + commission
        
        # 记录交易
        side = 'buy' if position_side == 'long' else 'sell'
        self.trades.append({
            'symbol': symbol,
            'time': time or timezone.now(),
            'side': side,
            'position_side': position_side,
            'price': price,
            'quantity': quantity,
            'commission': commission,
            'realized_pnl': Decimal('0')
        })
        
        return True
    
    def close_position(self, symbol, price, quantity=None, position_side='long', time=None):
        """
        平仓
        
        参数:
            symbol (str): 交易对符号
            price (Decimal): 平仓价格
            quantity (Decimal): 平仓数量，默认为None表示全部平仓
            position_side (str): 持仓方向，'long'或'short'
            time (datetime): 平仓时间
        
        返回:
            tuple: (已实现盈亏, 手续费)
        """
        # 获取持仓
        position = self.get_position(symbol, position_side)
        
        # 如果没有持仓，则返回
        if position.quantity == 0:
            return Decimal('0'), Decimal('0')
        
        # 如果未指定数量，则全部平仓
        if quantity is None:
            quantity = position.quantity
        
        # 平仓
        pnl, commission = position.close_position(price, quantity)
        
        # 更新余额
        position_value = price * quantity
        self.balance += position_value + pnl - commission
        
        # 记录交易
        side = 'sell' if position_side == 'long' else 'buy'
        self.trades.append({
            'symbol': symbol,
            'time': time or timezone.now(),
            'side': side,
            'position_side': position_side,
            'price': price,
            'quantity': quantity,
            'commission': commission,
            'realized_pnl': pnl
        })
        
        return pnl, commission
    
    def get_total_value(self, current_prices):
        """
        计算账户总价值
        
        参数:
            current_prices (dict): 当前价格，格式：{symbol: price}
        
        返回:
            Decimal: 账户总价值
        """
        total = self.balance
        
        for position_key, position in self.positions.items():
            symbol = position.symbol
            if symbol in current_prices and position.quantity > 0:
                price = current_prices[symbol]
                position_value = position.get_position_value(price)
                total += position_value
        
        return total
    
    def get_position_summary(self):
        """
        获取持仓摘要
        
        返回:
            list: 持仓摘要列表
        """
        summary = []
        for position_key, position in self.positions.items():
            if position.quantity > 0:
                summary.append({
                    'symbol': position.symbol,
                    'position_side': position.position_side,
                    'quantity': position.quantity,
                    'entry_price': position.entry_price,
                    'realized_pnl': position.realized_pnl
                })
        return summary


class BacktestEngine:
    """回测引擎，用于执行策略回测"""
    
    def __init__(self):
        """初始化回测引擎"""
        self.is_running = False
    
    def prepare_data(self, symbol, interval, start_time, end_time):
        """
        准备回测数据
        
        参数:
            symbol (str): 交易对符号，如BTCUSDT
            interval (str): K线间隔，如1m, 5m, 1h, 1d
            start_time (datetime): 开始时间
            end_time (datetime): 结束时间
        
        返回:
            pandas.DataFrame: K线数据DataFrame
        """
        # 首先尝试从数据库获取数据
        try:
            trading_pair = TradingPair.objects.get(symbol=symbol)
            klines = KlineData.objects.filter(
                trading_pair=trading_pair,
                interval=interval,
                open_time__gte=start_time,
                open_time__lte=end_time
            ).order_by('open_time')
            
            if klines.exists():
                # 转换为DataFrame
                data = []
                for kline in klines:
                    data.append({
                        'open_time': kline.open_time,
                        'open': kline.open_price,
                        'high': kline.high_price,
                        'low': kline.low_price,
                        'close': kline.close_price,
                        'volume': kline.volume,
                        'close_time': kline.close_time,
                        'quote_asset_volume': kline.quote_asset_volume,
                        'number_of_trades': kline.number_of_trades
                    })
                
                df = pd.DataFrame(data)
                logger.info(f"从数据库获取到 {symbol} {interval} 的K线数据，共 {len(df)} 条")
                
                # 如果数据量少于预期，则尝试从交易所获取数据
                if len(df) < 100:
                    logger.info(f"数据库中的数据量不足，尝试从交易所获取数据")
                    df = self._fetch_data_from_exchange(symbol, interval, start_time, end_time)
                
                return df
            else:
                logger.info(f"数据库中没有 {symbol} {interval} 的K线数据，尝试从交易所获取数据")
                return self._fetch_data_from_exchange(symbol, interval, start_time, end_time)
        
        except TradingPair.DoesNotExist:
            logger.error(f"交易对 {symbol} 不存在，尝试从交易所获取数据")
            return self._fetch_data_from_exchange(symbol, interval, start_time, end_time)
        except Exception as e:
            logger.error(f"从数据库获取数据时发生错误: {e}")
            return self._fetch_data_from_exchange(symbol, interval, start_time, end_time)
    
    def _fetch_data_from_exchange(self, symbol, interval, start_time, end_time):
        """
        从交易所获取数据
        
        参数:
            symbol (str): 交易对符号，如BTCUSDT
            interval (str): K线间隔，如1m, 5m, 1h, 1d
            start_time (datetime): 开始时间
            end_time (datetime): 结束时间
        
        返回:
            pandas.DataFrame: K线数据DataFrame
        """
        df = data_fetcher.fetch_and_save_klines(symbol, interval, start_time, end_time, save_to_db=True)
        if df is None:
            logger.error(f"从交易所获取数据失败")
            return pd.DataFrame()  # 返回空DataFrame
        return df
    
    def preprocess_data(self, df):
        """
        预处理数据，添加常用技术指标
        
        参数:
            df (pandas.DataFrame): K线数据DataFrame
        
        返回:
            pandas.DataFrame: 添加指标后的DataFrame
        """
        if df.empty:
            return df
        
        # 确保按时间排序
        df = df.sort_values('open_time')
        
        # 转换价格列为浮点数
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 计算常用技术指标
        
        # 1. 移动平均线 (MA)
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma10'] = df['close'].rolling(window=10).mean()
        df['ma20'] = df['close'].rolling(window=20).mean()
        df['ma60'] = df['close'].rolling(window=60).mean()
        
        # 2. 相对强弱指数 (RSI)
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        
        rs = avg_gain / avg_loss
        df['rsi14'] = 100 - (100 / (1 + rs))
        
        # 3. 布林带 (Bollinger Bands)
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        df['bb_std'] = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_middle'] - 2 * df['bb_std']
        
        # 4. MACD
        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = df['ema12'] - df['ema26']
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['histogram'] = df['macd'] - df['signal']
        
        # 5. 成交量指标
        df['volume_ma5'] = df['volume'].rolling(window=5).mean()
        df['volume_ma20'] = df['volume'].rolling(window=20).mean()
        
        return df
    
    def run_backtest(self, backtest_id):
        """
        运行回测
        
        参数:
            backtest_id (int): 回测记录ID
        
        返回:
            bool: 是否回测成功
        """
        self.is_running = True
        start_time = time.time()
        
        try:
            # 获取回测记录
            backtest = Backtest.objects.get(id=backtest_id)
            
            # 更新回测状态为运行中
            backtest.status = 'running'
            backtest.save()
            
            # 获取策略
            strategy = backtest.strategy
            
            # 准备回测数据
            df = self.prepare_data(
                strategy.trading_pair.symbol, 
                backtest.interval, 
                backtest.start_time, 
                backtest.end_time
            )
            
            if df.empty:
                logger.error(f"回测数据为空")
                backtest.status = 'failed'
                backtest.save()
                return False
            
            # 预处理数据
            df = self.preprocess_data(df)
            
            # 初始化账户
            account = Account(initial_capital=backtest.initial_capital)
            
            # 获取策略参数
            strategy_params = strategy.get_parameters_dict()
            backtest_params = backtest.get_parameters_dict()
            
            # 合并参数
            params = {**strategy_params, **backtest_params}
            
            # 准备全局命名空间，用于执行策略代码
            globals_dict = {
                'df': df,
                'account': account,
                'params': params,
                'numpy': np,
                'pandas': pd,
                'Decimal': Decimal,
                'Position': Position,
                'trading_pair': strategy.trading_pair.symbol,
                'backtest_id': backtest_id
            }
            
            # 执行策略代码
            exec(strategy.code, globals_dict)
            
            # 获取交易记录
            trades = account.trades
            
            # 计算回测结果
            result_summary = self._calculate_backtest_results(
                account, 
                df, 
                strategy.trading_pair.symbol,
                backtest.start_time,
                backtest.end_time
            )
            
            # 保存交易记录
            with transaction.atomic():
                # 清除之前的交易记录
                BacktestTrade.objects.filter(backtest=backtest).delete()
                
                # 创建新的交易记录
                for trade in trades:
                    BacktestTrade.objects.create(
                        backtest=backtest,
                        trading_pair=strategy.trading_pair,
                        time=trade['time'],
                        side=trade['side'],
                        position_side=trade['position_side'],
                        price=trade['price'],
                        quantity=trade['quantity'],
                        commission=trade['commission'],
                        realized_pnl=trade['realized_pnl']
                    )
                
                # 更新回测状态和结果
                backtest.status = 'completed'
                backtest.result_summary = result_summary
                backtest.save()
            
            elapsed_time = time.time() - start_time
            logger.info(f"回测完成，耗时 {elapsed_time:.2f} 秒")
            self.is_running = False
            return True
        
        except Backtest.DoesNotExist:
            logger.error(f"回测记录 {backtest_id} 不存在")
            self.is_running = False
            return False
        except Exception as e:
            logger.error(f"运行回测时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
            
            try:
                # 更新回测状态为失败
                backtest = Backtest.objects.get(id=backtest_id)
                backtest.status = 'failed'
                backtest.result_summary = {'error': str(e)}
                backtest.save()
            except Exception:
                pass
            
            self.is_running = False
            return False
    
    def _calculate_backtest_results(self, account, df, symbol, start_time, end_time):
        """
        计算回测结果
        
        参数:
            account (Account): 账户对象
            df (pandas.DataFrame): K线数据DataFrame
            symbol (str): 交易对符号
            start_time (datetime): 开始时间
            end_time (datetime): 结束时间
        
        返回:
            dict: 回测结果摘要
        """
        trades = account.trades
        
        if not trades:
            return {
                'initial_capital': float(account.initial_capital),
                'final_balance': float(account.balance),
                'total_return': 0,
                'total_return_percent': 0,
                'win_rate': 0,
                'total_trades': 0,
                'profitable_trades': 0,
                'losing_trades': 0,
                'max_drawdown': 0,
                'max_drawdown_percent': 0,
                'trade_count': 0
            }
        
        # 计算基本指标
        initial_capital = account.initial_capital
        final_balance = account.balance
        
        # 处理持仓
        for position_key, position in account.positions.items():
            if position.quantity > 0:
                # 如果有未平仓的持仓，使用最后一个价格进行平仓
                last_price = df['close'].iloc[-1]
                account.close_position(
                    position.symbol, 
                    Decimal(str(last_price)), 
                    position_side=position.position_side,
                    time=df['close_time'].iloc[-1]
                )
        
        # 更新最终余额
        final_balance = account.balance
        
        # 计算交易的盈亏
        profits = [float(trade['realized_pnl']) for trade in trades if trade['realized_pnl'] > 0]
        losses = [float(trade['realized_pnl']) for trade in trades if trade['realized_pnl'] < 0]
        
        profitable_trades = len(profits)
        losing_trades = len(losses)
        total_trades = profitable_trades + losing_trades
        
        win_rate = profitable_trades / total_trades if total_trades > 0 else 0
        total_return = float(final_balance - initial_capital)
        total_return_percent = (total_return / float(initial_capital)) * 100
        
        # 计算最大回撤
        balance_curve = self._calculate_balance_curve(account, df, symbol)
        max_drawdown, max_drawdown_percent = self._calculate_max_drawdown(balance_curve)
        
        # 返回结果摘要
        return {
            'initial_capital': float(initial_capital),
            'final_balance': float(final_balance),
            'total_return': total_return,
            'total_return_percent': total_return_percent,
            'win_rate': win_rate,
            'total_trades': total_trades,
            'profitable_trades': profitable_trades,
            'losing_trades': losing_trades,
            'max_drawdown': max_drawdown,
            'max_drawdown_percent': max_drawdown_percent,
            'trade_count': len(trades)
        }
    
    def _calculate_balance_curve(self, account, df, symbol):
        """计算余额曲线"""
        trades = account.trades
        if not trades:
            return pd.Series(account.initial_capital, index=df.index)
        
        # 创建余额曲线
        balance_curve = pd.Series(account.initial_capital, index=df['open_time'])
        
        # 遍历交易记录
        for i, trade in enumerate(trades):
            trade_time = trade['time']
            idx = df['open_time'].searchsorted(trade_time)
            if idx < len(df):
                balance_curve.iloc[idx:] += float(trade['realized_pnl'] - trade['commission'])
        
        return balance_curve
    
    def _calculate_max_drawdown(self, balance_curve):
        """计算最大回撤"""
        if len(balance_curve) <= 1:
            return 0, 0
        
        # 计算每个点的历史最高值
        peak = balance_curve.cummax()
        
        # 计算相对于峰值的回撤
        drawdown = (balance_curve - peak) / peak * 100
        
        # 最大回撤
        max_drawdown_percent = drawdown.min()
        max_drawdown = (balance_curve - peak).min()
        
        return float(max_drawdown), float(max_drawdown_percent)
    
    def stop(self):
        """停止回测"""
        self.is_running = False
        logger.info("回测引擎正在停止...")


# 单例模式
backtest_engine = BacktestEngine() 