import pandas as pd
from pathlib import Path
from datetime import datetime
import re
from common_core.risk_ctrl.liquidation import LiquidationChecker
from firm.backtest_core.figure import draw_equity_curve_plotly
from firm.backtest_core.evaluate import strategy_evaluate

class PortfolioBacktestSimulator:
    def __init__(self, configs):
        self.configs = configs
        self.strategies = []
        self.unified_df = pd.DataFrame()
        
        # Global Account State
        self.total_initial_capital = 0
        self.liquidation_event = None
        self.is_liquidated = False
        self.risk_ctrl = LiquidationChecker(min_margin_rate=0.005) # Unified account maintenance margin rate

        # Metrics history
        self._times = []
        self._equities = [] # Total Equity
        self._prices_map = {} # { strategy_id: [prices] } for plotting
        
    def set_strategies(self, strategies):
        self.strategies = strategies
        self.total_initial_capital = sum(s.money for s in strategies)
        
        # Check if global compounding should be enabled
        # If any strategy has enable_compound=True, we treat it as a signal to use global compounding
        # But we must disable local compounding to avoid conflict
        self.enable_global_compound = any(getattr(s, 'enable_compound', False) for s in strategies)
        
        for s in self.strategies:
            # Ensure external risk control is ON for all strategies
            s.external_risk_control = True
            # Disable local compounding, we will handle it globally
            if self.enable_global_compound:
                s.enable_compound = False

    def load_data(self, data_list):
        """
        data_list: list of dataframes corresponding to strategies (in same order as configs)
        """
        merged_df = None
        for i, df in enumerate(data_list):
            # Keep only necessary columns: candle_begin_time, open, high, low, close
            temp_df = df[['candle_begin_time', 'open', 'high', 'low', 'close']].copy()
            # Add suffix to avoid collision
            temp_df.columns = ['candle_begin_time', f'open_{i}', f'high_{i}', f'low_{i}', f'close_{i}']
            
            if merged_df is None:
                merged_df = temp_df
            else:
                # Merge on time
                merged_df = pd.merge(merged_df, temp_df, on='candle_begin_time', how='outer')
        
        if merged_df is not None:
            merged_df.sort_values('candle_begin_time', inplace=True)
            merged_df.fillna(method='ffill', inplace=True) # Forward fill prices
            merged_df.dropna(inplace=True) # Drop rows with NaN (start of data)
            self.unified_df = merged_df
            
            # Init price history lists
            for i in range(len(data_list)):
                self._prices_map[i] = []

    def run(self):
        if self.unified_df.empty or not self.strategies:
            print("No data or strategies to run.")
            return

        print(f"Starting Portfolio Backtest with {len(self.strategies)} strategies...")
        print(f"Total Initial Capital: {self.total_initial_capital}")

        # Init all strategies
        first_row = self.unified_df.iloc[0]
        ts = first_row['candle_begin_time']
        
        for i, strategy in enumerate(self.strategies):
            price = first_row[f'open_{i}']
            strategy.on_tick(ts, price)
            strategy.init()

        # Main Loop
        total_steps = len(self.unified_df)
        for index, row in self.unified_df.iterrows():
            ts = row['candle_begin_time']
            
            if self.is_liquidated:
                break

            # Simulate price movement within the bar: Open -> High -> Low -> Close
            # We assume correlation: all hit High together, then Low together.
            # This is a simplification but allows checking global equity at extremes.
            
            # 1. Open
            self._update_all(ts, row, 'open')
            if self._check_global_liquidation(ts, row, 'open'): break
            
            # 2. High
            self._update_all(ts, row, 'high')
            if self._check_global_liquidation(ts, row, 'high'): break
            
            # 3. Low
            self._update_all(ts, row, 'low')
            if self._check_global_liquidation(ts, row, 'low'): break
            
            # 4. Close
            self._update_all(ts, row, 'close')
            self._process_hedging_logic(ts, row, 'close')
            if self._check_global_liquidation(ts, row, 'close'): break
            
            
            # Record metrics at Close
            self._record_metrics(ts, row)

            # --- Global Compounding Sync ---
            if self.enable_global_compound and self.strategies:
                 # Calculate total equity using the LAST recorded metric
                 current_total_equity = self._equities[-1]
                 
                 if current_total_equity > 0:
                     num_strategies = len(self.strategies)
                     allocated = current_total_equity / num_strategies
                     
                     for i, strategy in enumerate(self.strategies):
                         # Get current close price for this strategy
                         price = row[f'close_{i}']
                         
                         # Update Money (for sizing)
                         strategy.money = allocated
                         
                         # Update Grid Quantity
                         if hasattr(strategy, 'get_one_grid_quantity'):
                             new_qty = strategy.get_one_grid_quantity()
                             strategy.grid_dict["one_grid_quantity"] = new_qty
                             
                         # Reset Profit Accumulators
                         strategy.account_dict['pair_profit'] = 0
                         
                         # Snapshot Unrealized for Accounting Offset
                         strategy._last_sync_unrealized = strategy.get_positions_profit(price)

        self.generate_reports()

    def _update_all(self, ts, row, price_type):
        for i, strategy in enumerate(self.strategies):
            col = f'{price_type}_{i}'
            price = row[col]
            strategy.on_tick(ts, price)

    def _process_hedging_logic(self, ts, row, price_type):
        """
        处理对冲与自动建仓/重置逻辑
        """
        # 1. 计算所有策略的当前持仓价值
        # 用个 map 存起来: {index: position_value}
        pv_map = {}
        prices = {}
        for i, strategy in enumerate(self.strategies):
            col = f'{price_type}_{i}'
            price = row[col]
            prices[i] = price
            
            pos = float(strategy.account_dict.get('positions_qty', 0) or 0)
            pv_map[i] = abs(pos * price)
            
        # 2. 遍历触发检查
        for i, strategy in enumerate(self.strategies):
            # 计算"对手盘"价值 (排除自己)
            other_pv = sum(v for k, v in pv_map.items() if k != i)
            
            current_price = prices[i]
            
            # 检查自动建仓
            if hasattr(strategy, 'check_auto_build'):
                strategy.check_auto_build(current_price, other_pv)
                
            # 检查趋势重置
            if hasattr(strategy, 'check_trend_reentry'):
                strategy.check_trend_reentry(current_price, other_pv)

    def _check_global_liquidation(self, ts, row, phase):
        total_equity = 0
        total_maintenance_margin = 0
        
        for i, strategy in enumerate(self.strategies):
            price = row[f'{phase}_{i}']
            
            # Equity = Money + Realized + Unrealized - Offset (for compounding)
            unrealized = strategy.get_positions_profit(price)
            realized = strategy.account_dict['pair_profit']
            offset = getattr(strategy, '_last_sync_unrealized', 0)
            equity = strategy.money + realized + unrealized - offset
            total_equity += equity
            
            # Maintenance Margin
            qty = abs(strategy.account_dict['positions_qty'])
            maint_margin = qty * price * 0.005 # 0.5% rate
            total_maintenance_margin += maint_margin
            
        if total_equity < total_maintenance_margin:
            print(f"💀 [Portfolio] 触发统一账户爆仓! 时间: {ts}, 阶段: {phase}")
            print(f"   总权益: {total_equity:.2f}, 总维持保证金: {total_maintenance_margin:.2f}")
            self.is_liquidated = True
            self.liquidation_event = {'time': ts, 'equity': total_equity}
            for i, strategy in enumerate(self.strategies):
                liq_price = row[f'{phase}_{i}']
                self._prices_map[i].append(liq_price)
            self._times.append(ts)
            self._equities.append(0)
            return True
        return False
        
    def _record_metrics(self, ts, row):
        total_equity = 0
        for i, strategy in enumerate(self.strategies):
            price = row[f'close_{i}']
            unrealized = strategy.get_positions_profit(price)
            realized = strategy.account_dict['pair_profit']
            offset = getattr(strategy, '_last_sync_unrealized', 0)
            equity = strategy.money + realized + unrealized - offset
            total_equity += equity
            
            self._prices_map[i].append(price)
            
        self._times.append(ts)
        self._equities.append(total_equity)

    def generate_reports(self):
        if not self._equities:
            return

        base_results_dir = Path(self.configs[0].result_dir).parent
        out_dir = base_results_dir / self._build_portfolio_folder_name() / "组合报告"
        out_dir.mkdir(parents=True, exist_ok=True)
        
        # Prepare DataFrame
        account_df = pd.DataFrame({
            'candle_begin_time': pd.to_datetime(self._times),
            'equity': self._equities,
        })
        
        account_df['close'] = self._prices_map[0] 
        
        initial_cap = self.total_initial_capital
        account_df['净值'] = account_df['equity'] / initial_cap
        account_df['涨跌幅'] = account_df['净值'].pct_change()
        account_df['max_equity'] = account_df['equity'].cummax()
        account_df['drawdown'] = (account_df['equity'] - account_df['max_equity']) / account_df['max_equity']
        
        
        account_df['是否爆仓'] = 0
        if self.is_liquidated:
            # Mark the last row as liquidated
            account_df.iloc[-1, account_df.columns.get_loc('是否爆仓')] = 1
        
        n = len(self.strategies)
        qty_list = []
        for i in range(n):
            cfg = self.configs[i]
            p0 = self.unified_df.iloc[0][f'open_{i}']
            money_i = getattr(cfg, 'money', 0)
            ratio_i = getattr(cfg, 'capital_ratio', 1.0)
            lev_i = getattr(cfg, 'leverage', 1)
            dir_i = getattr(cfg, 'direction_mode', 'long')
            sign = 1 if str(dir_i).lower() == 'long' else (-1 if str(dir_i).lower() == 'short' else 0)
            qty = 0 if p0 == 0 else sign * money_i * ratio_i * lev_i / p0
            qty_list.append(qty)
        benchmark_equity = []
        for j in range(len(self._times)):
            pnl_sum = 0
            for i in range(n):
                p0 = self.unified_df.iloc[0][f'open_{i}']
                p = self._prices_map[i][j] if j < len(self._prices_map[i]) else p0
                pnl_sum += qty_list[i] * (p - p0)
            benchmark_equity.append(initial_cap + pnl_sum)
        account_df['组合基准净值'] = [e / initial_cap if initial_cap != 0 else 0 for e in benchmark_equity]
        account_df.to_csv(out_dir / '资金曲线.csv', encoding='utf-8-sig', index=False)
        
        rtn, year_rtn, month_rtn, quarter_rtn = strategy_evaluate(account_df, net_col='净值', pct_col='涨跌幅')
        rtn.to_csv(out_dir / '策略评价.csv', encoding='utf-8-sig')
        year_rtn.to_csv(out_dir / '年度账户收益.csv', encoding='utf-8-sig')
        month_rtn.to_csv(out_dir / '月度账户收益.csv', encoding='utf-8-sig')
        quarter_rtn.to_csv(out_dir / '季度账户收益.csv', encoding='utf-8-sig')
        
        print("\n========================================")
        print("         组合策略回测结果 (Unified)       ")
        print("========================================")
        print(f"总本金: {initial_cap:.2f}")
        print(f"期末权益: {self._equities[-1]:.2f}")
        
        pl_total = self._equities[-1] - initial_cap
        roi = pl_total / initial_cap
        
        print(f"总收益: {pl_total:.2f} ({roi*100:+.2f}%)")
        print(f"最大回撤: {rtn.at['最大回撤', 0]}")
        print(f"年化收益: {rtn.at['年化收益', 0]}")
        
        # APR Calculation
        start_time = pd.to_datetime(self.unified_df['candle_begin_time'].iloc[0])
        end_time = pd.to_datetime(self.unified_df['candle_begin_time'].iloc[-1])
        duration_hours = max(0.001, (end_time - start_time).total_seconds() / 3600)
        duration_days = duration_hours / 24
        
        # Aggregate Strategy Metrics
        total_pairing_count = 0
        total_realized_pnl = 0
        total_unrealized_pnl = 0
        
        print("-" * 30)
        print("策略详细统计:")
        
        for i, strategy in enumerate(self.strategies):
            acc = strategy.account_dict
            pairing_count = acc.get('pairing_count', 0)
            realized = acc.get('pair_profit', 0)
            unrealized = strategy.get_positions_profit(self.unified_df.iloc[-1][f'close_{i}'])
            
            total_pairing_count += pairing_count
            total_realized_pnl += realized
            total_unrealized_pnl += unrealized
            
            direction_mode = getattr(strategy, 'direction_mode', 'Unknown')
            print(f"策略 #{i+1} ({direction_mode}):")
            print(f"  配对次数: {pairing_count}")
            print(f"  已实现利润: {realized:.2f}")
            print(f"  浮动盈亏: {unrealized:.2f}")
            print(f"  网格持仓: {acc.get('positions_grids', 0)} 格")
            
        print("-" * 30)
        
        daily_pairings = total_pairing_count / max(duration_days, 0.001)
        apr_linear = roi * (365 * 24 / duration_hours)
        apr_compound = ((1 + roi) ** (365 * 24 / duration_hours)) - 1
        
        print(f"回测时长: {duration_hours:.2f} 小时 ({duration_days:.1f} 天)")
        print(f"总配对次数: {total_pairing_count}")
        print(f"日均配对: {daily_pairings:.2f}")
        print(f"线性年化: {apr_linear*100:.1f}%")
        print(f"复利年化: {apr_compound*100:.1f}%")
        print(f"总已实现利润: {total_realized_pnl:.2f}")
        print(f"总浮动盈亏: {total_unrealized_pnl:.2f}")
        
        
        title = f"组合回测：统一账户 (初始本金: {initial_cap:.2f})"

        desc_lines = [f"<b>总本金:</b> {initial_cap:.2f} | <b>策略数量:</b> {len(self.strategies)}"]
        for i, cfg in enumerate(self.configs):
            dir_raw = str(getattr(cfg, 'direction_mode', '')).lower()
            if 'long' in dir_raw:
                s_type = '做多'
            elif 'short' in dir_raw:
                s_type = '做空'
            else:
                s_type = '中性'
            if getattr(cfg, 'price_range', 0) == 0:
                s_range = f"{cfg.min_price}-{cfg.max_price}"
            else:
                s_range = f"动态区间({cfg.price_range})"
            symbol = getattr(cfg, 'symbol', '')
            line = (f"<b>策略{i+1}（{symbol} {s_type}）:</b> 资金:{cfg.money:.0f}, 杠杆:{cfg.leverage}倍, "
                    f"区间:{s_range}, 网格数:{cfg.num_steps}, "
                    f"复利:{'开启' if cfg.enable_compound else '关闭'}")
            desc_lines.append(line)
            
        desc = "<br>".join(desc_lines)
        
        markers = []
        if self.liquidation_event:
            markers.append({
                'time': self.liquidation_event['time'],
                'price': self.liquidation_event['equity'],
                'text': '爆仓',
                'color': 'red',
                'symbol': 'x',
                'size': 20,
                'on_right_axis': False
            })
            
        draw_equity_curve_plotly(
            account_df,
            data_dict={'组合资金曲线': 'equity'},
            date_col='candle_begin_time',
            right_axis={'组合基准净值': '组合基准净值', '组合最大回撤': 'drawdown'},
            title=title,
            desc=desc,
            path=out_dir / '组合资金曲线.html',
            show_subplots=False,
            markers=markers
        )

    def _build_portfolio_folder_name(self) -> str:
        def _direction_cn(cfg) -> str:
            direction_raw = str(getattr(cfg, 'direction_mode', '')).lower()
            if 'long' in direction_raw:
                return '多'
            if 'short' in direction_raw:
                return '空'
            return '中'

        def _fmt_time(value: str) -> str:
            s = str(value).strip()
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
                try:
                    return datetime.strptime(s, fmt).strftime('%Y%m%d-%H%M%S')
                except Exception:
                    pass
            digits = re.sub(r'[^0-9]', '', s)
            return digits[:14] if len(digits) >= 14 else (digits or 'unknown')

        items = []
        periods = []
        starts = []
        ends = []
        run_ids = []
        for cfg in self.configs:
            symbol = str(getattr(cfg, 'symbol', '')).strip()
            items.append(f"{symbol}{_direction_cn(cfg)}" if symbol else _direction_cn(cfg))
            periods.append(str(getattr(cfg, 'candle_period', '')).strip())
            starts.append(_fmt_time(getattr(cfg, 'start_time', '')))
            ends.append(_fmt_time(getattr(cfg, 'end_time', '')))
            run_ids.append(str(getattr(cfg, 'run_id', '')).strip())

        symbols_part = '+'.join([x for x in items if x]) or '组合'
        period_part = periods[0] if periods and all(p == periods[0] for p in periods) else 'mixed'
        start_part = starts[0] if starts and all(s == starts[0] for s in starts) else (min(starts) if starts else 'unknown')
        end_part = ends[0] if ends and all(s == ends[0] for s in ends) else (max(ends) if ends else 'unknown')
        run_id = run_ids[0] if run_ids and all(r == run_ids[0] for r in run_ids) and run_ids[0] else datetime.now().strftime('%Y%m%d-%H%M%S-%f')

        raw = f"{symbols_part}_网格组合_{period_part}_{start_part}~{end_part}_{run_id}"
        safe = re.sub(r'[^0-9A-Za-z\u4e00-\u9fff._+\-~()]', '_', raw)
        return safe.strip('_')
