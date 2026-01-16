import time
from datetime import datetime, timedelta
import pandas as pd
from pytz import timezone
from enum import Enum

from 策略仓库.二号网格策略.core.strategy import Strategy
from 策略仓库.二号网格策略.core.engine import BacktestEngine

class Interval_mode(Enum):
    AS = "arithmetic_sequence"
    GS = "geometric_sequence"

class Direction_mode(Enum):
    NEUTRAL = "neutral"
    LONG = "long"
    SHORT = "short"

eps = 0.000001

class GridStrategy(Strategy):
    grid_dict = {}
    account_dict = {}

    def __init__(self, config):
        self.config = config
        self.symbol = config['symbol']
        self.money = config['money']
        self.leverage = config['leverage']
        
        # Parse Enums
        im_str = config['interval_mode']
        if im_str == "arithmetic_sequence":
            self.interval_mode = Interval_mode.AS
        else:
            self.interval_mode = Interval_mode.GS
            
        dm_str = config['direction_mode']
        if dm_str == "long":
            self.direction_mode = Direction_mode.LONG
        elif dm_str == "short":
            self.direction_mode = Direction_mode.SHORT
        else:
            self.direction_mode = Direction_mode.NEUTRAL
            
        self.capital_ratio = config['capital_ratio']
        self.enable_upward_shift = config['enable_upward_shift']
        self.enable_downward_shift = config['enable_downward_shift']
        self.stop_up_price = config['stop_up_price']
        self.stop_down_price = config['stop_down_price']
        
        self.num_steps = config['num_steps']
        self.min_price = config['min_price']
        self.max_price = config['max_price']
        self.price_range = config['price_range']
        
        self.curr_price = 0
        self.max_loss = 0
        self.max_profit = 0
        
        self.shift_logs = []
        self.upward_shift_count = 0
        self.downward_shift_count = 0

    def init(self):
        """Called after first tick is received to setup grid based on initial price."""
        self._init_strategy()

    def on_tick(self, timestamp, price):
        self.update_price(timestamp, price)

    def on_bar(self, bar):
        # We process price movements in on_tick, so on_bar is just for sync if needed
        pass

    '''------------------------------ Strategy Calculation Tools ------------------------------'''

    def get_down_price(self, price):
        if self.interval_mode == Interval_mode.GS:
            down_price = price / (1 + self.grid_dict["interval"])
        elif self.interval_mode == Interval_mode.AS:
            down_price = price - self.grid_dict["interval"]
        return down_price

    def get_up_price(self, price):
        if self.interval_mode == Interval_mode.GS:
            up_price = price * (1 + self.grid_dict["interval"])
        elif self.interval_mode == Interval_mode.AS:
            up_price = price + self.grid_dict["interval"]
        return up_price

    def get_positions_cost(self):
        total = 0
        p = self.account_dict["positions_grids"]
        c = self.grid_dict["price_central"]

        if p < 0:
            for i in range(-p):
                c = self.get_up_price(c)
                total += c
        elif p > 0:
            for i in range(p):
                c = self.get_down_price(c)
                total += c
        elif p == 0:
            return 0

        return abs(total / p)

    def get_positions_profit(self, price):
        positions_profit = (price - self.account_dict["positions_cost"]) * \
                           self.account_dict["positions_grids"] * \
                           self.grid_dict["one_grid_quantity"]
        return positions_profit

    def get_interval(self):
        max_value = self.max_price
        min_value = self.min_price
        num_elements = self.num_steps

        if self.interval_mode == Interval_mode.GS:
            interval = (max_value / min_value) ** (1 / num_elements) - 1
        elif self.interval_mode == Interval_mode.AS:
            interval = (max_value - min_value) / num_elements
        return interval

    def get_price_central(self, new_price):
        max_value = self.max_price
        min_value = self.min_price
        num_elements = self.num_steps

        if self.interval_mode == Interval_mode.GS:
            interval = (max_value / min_value) ** (1 / num_elements)
            price_list = [min_value * (interval ** i) for i in range(num_elements + 1)]
        elif self.interval_mode == Interval_mode.AS:
            interval = (max_value - min_value) / num_elements
            price_list = [min_value + (interval * i) for i in range(num_elements + 1)]

        price_central = min(price_list, key=lambda x: abs(x - new_price))
        return price_central

    def get_one_grid_quantity(self):
        max_value = self.max_price
        min_value = self.min_price
        num_elements = self.num_steps
        if self.interval_mode == Interval_mode.GS:
            interval = (max_value / min_value) ** (1 / num_elements)
            price_list = [min_value * (interval ** i) for i in range(num_elements + 1)]
        elif self.interval_mode == Interval_mode.AS:
            interval = (max_value - min_value) / num_elements
            price_list = [min_value + (interval * i) for i in range(num_elements + 1)]

        return self.money * self.leverage * self.capital_ratio / sum(price_list)

    def get_pair_profit(self, price, side):
        if self.interval_mode == Interval_mode.GS:
            if side == "SELL":
                pair_profit = (price / (1 + self.grid_dict["interval"])) * self.grid_dict["interval"] * self.grid_dict[
                    "one_grid_quantity"]
            elif side == "BUY":
                pair_profit = price * self.grid_dict["interval"] * self.grid_dict["one_grid_quantity"]
        elif self.interval_mode == Interval_mode.AS:
            pair_profit = self.grid_dict["interval"] * self.grid_dict["one_grid_quantity"]
        return pair_profit

    def _init_strategy(self):
        self.grid_dict = {
            "interval": 0,
            "price_central": 0,
            "one_grid_quantity": 0,
            "max_price": 0,
            "min_price": 0,
        }

        self.account_dict = {
            "positions_grids": 0,
            "pairing_count": 0,
            "pair_profit": 0,
            "positions_cost": 0,
            "positions_profit": 0,
            "pending_prders": [],
            "up_price": 0,
            "down_price": 0,
        }

        if self.price_range != 0:
            self.max_price = self.curr_price * (1 + self.price_range)
            self.min_price = self.curr_price * (1 - self.price_range)
        self.grid_dict["interval"] = self.get_interval()
        self.grid_dict["price_central"] = self.get_price_central(self.curr_price)
        self.grid_dict["one_grid_quantity"] = self.get_one_grid_quantity()
        self.grid_dict["max_price"] = self.max_price
        self.grid_dict["min_price"] = self.min_price
        self.account_dict["up_price"] = self.get_up_price(self.grid_dict["price_central"])
        self.account_dict["down_price"] = self.get_down_price(self.grid_dict["price_central"])

        print(self.grid_dict)
        print(self.account_dict)

    def update_order(self, ts, price, side):
        if price > self.grid_dict["max_price"] and self.enable_upward_shift:
            if self.stop_up_price and price >= self.stop_up_price:
                print(f'{ts} 达到停止上移价格，停止上移')
                self.shift_logs.append({"ts": ts, "type": "stop_up", "price": price})
                self.enable_upward_shift = False
            else:
                oc = self.grid_dict["price_central"]
                omin = self.grid_dict["min_price"]
                omax = self.grid_dict["max_price"]
                self.grid_dict["price_central"] = self.get_up_price(self.grid_dict["price_central"])
                self.grid_dict["min_price"] = self.get_up_price(self.grid_dict["min_price"])
                self.grid_dict["max_price"] = self.get_up_price(self.grid_dict["max_price"])
                nc = self.grid_dict["price_central"]
                nmin = self.grid_dict["min_price"]
                nmax = self.grid_dict["max_price"]
                self.upward_shift_count += 1
                self.shift_logs.append({"ts": ts, "type": "up", "price": price, "old_central": oc, "new_central": nc, "old_min": omin, "new_min": nmin, "old_max": omax, "new_max": nmax})
                print(f'{ts} 上移一格 中枢 {oc:.2f}->{nc:.2f} 上限 {omax:.2f}->{nmax:.2f} 下限 {omin:.2f}->{nmin:.2f}')

        if price < self.grid_dict["min_price"] and self.enable_downward_shift:
            if self.stop_down_price and price <= self.stop_down_price:
                print(f'{ts} 达到停止下移价格，停止下移')
                self.shift_logs.append({"ts": ts, "type": "stop_down", "price": price})
                self.enable_downward_shift = False
            else:
                oc = self.grid_dict["price_central"]
                omin = self.grid_dict["min_price"]
                omax = self.grid_dict["max_price"]
                self.grid_dict["price_central"] = self.get_down_price(self.grid_dict["price_central"])
                self.grid_dict["min_price"] = self.get_down_price(self.grid_dict["min_price"])
                self.grid_dict["max_price"] = self.get_down_price(self.grid_dict["max_price"])
                nc = self.grid_dict["price_central"]
                nmin = self.grid_dict["min_price"]
                nmax = self.grid_dict["max_price"]
                self.downward_shift_count += 1
                self.shift_logs.append({"ts": ts, "type": "down", "price": price, "old_central": oc, "new_central": nc, "old_min": omin, "new_min": nmin, "old_max": omax, "new_max": nmax})
                print(f'{ts} 下移一格 中枢 {oc:.2f}->{nc:.2f} 上限 {omax:.2f}->{nmax:.2f} 下限 {omin:.2f}->{nmin:.2f}')

        should_execute = True
        if self.direction_mode == Direction_mode.LONG:
            if side == "SELL" and self.account_dict["positions_grids"] <= 0:
                should_execute = False
        elif self.direction_mode == Direction_mode.SHORT:
            if side == "BUY" and self.account_dict["positions_grids"] >= 0:
                should_execute = False

        if not should_execute:
            self.account_dict["down_price"] = self.get_down_price(price)
            self.account_dict["up_price"] = self.get_up_price(price)
            return

        if side == "BUY":
            self.account_dict["positions_grids"] += 1
        elif side == "SELL":
            self.account_dict["positions_grids"] -= 1

        self.account_dict["positions_cost"] = self.get_positions_cost()
        self.account_dict["positions_profit"] = self.get_positions_profit(price)
        if side == "BUY" and self.account_dict["positions_grids"] <= 0:
            self.account_dict["pairing_count"] += 1
            self.account_dict["pair_profit"] += self.get_pair_profit(price, side)
            print(f'{ts} 配对成功利润 {self.account_dict["pair_profit"]:.4f}')
        elif side == "SELL" and self.account_dict["positions_grids"] >= 0:
            self.account_dict["pairing_count"] += 1
            self.account_dict["pair_profit"] += self.get_pair_profit(price, side)
            print(f'{ts} 配对成功利润 {self.account_dict["pair_profit"]:.4f}')

        pl = self.account_dict["positions_profit"] + self.account_dict["pair_profit"]
        self.max_loss = min(pl, self.max_loss)
        self.max_profit = max(pl, self.max_profit)

        self.account_dict["down_price"] = self.get_down_price(price)
        self.account_dict["up_price"] = self.get_up_price(price)

    def update_price(self, ts, new_price):
        if self.curr_price == 0:
             self.curr_price = new_price
             return

        while True:
            up_price = self.account_dict["up_price"]
            down_price = self.account_dict["down_price"]
            
            if abs(new_price - self.curr_price) < eps:
                return

            if new_price > self.curr_price and new_price < up_price - eps:
                self.curr_price = new_price
                return

            if new_price < self.curr_price and new_price > down_price + eps:
                self.curr_price = new_price
                return

            if new_price > self.curr_price:
                self.update_order(ts, up_price, 'SELL')
            else:
                self.update_order(ts, down_price, 'BUY')

if __name__ == "__main__":
    engine = BacktestEngine(config_path="config.yaml")
    strategy = GridStrategy(engine.config['backtest'])
    engine.set_strategy(strategy)
    engine.run()
