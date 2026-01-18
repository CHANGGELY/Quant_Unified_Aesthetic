# -*- coding: utf-8 -*-
"""
8号香农策略 - 策略查看器 (TradingView 引擎版)
左右分栏布局：左侧 K线图，右侧交易明细
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import streamlit as st
from dataclasses import dataclass
from typing import List, Tuple
from datetime import timedelta
import streamlit_lightweight_charts as slc

# ====== 自动计算项目根目录 ======
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 导入回测配置 + 回测核心（用于复用同口径的波动率递推）
try:
    import 策略仓库.八号香农策略.config_backtest as cfg
    from 策略仓库.八号香农策略 import backtest as 香农回测
except ImportError:
    # 兼容：直接在本目录运行
    sys.path.append(str(CURRENT_FILE.parent))
    import config_backtest as cfg
    import backtest as 香农回测


# ============================================================
# 数据结构
# ============================================================

@dataclass
class 交易记录:
    """单笔交易记录"""
    时间: pd.Timestamp
    价格: float
    方向: str
    数量: float
    交易前仓位比例: float
    交易后仓位比例: float
    交易前权益: float
    交易后权益: float


# ============================================================
# 缓存/辅助函数 (全部定义在 main() 之前)
# ============================================================

def 加载数据(path: str) -> pd.DataFrame:
    """
    读取真实 HDF5 分钟线数据（不是模拟数据）。

    说明：
        这里返回 DataFrame 是为了方便后续做“重采样”（把 1 分钟合成 5 分钟/1小时等）。
    """
    数据文件 = Path(str(path)).expanduser().resolve()
    if not 数据文件.exists():
        raise FileNotFoundError(f"❌ 找不到数据文件: {数据文件}")

    import h5py
    import hdf5plugin  # noqa: F401  # 注册压缩插件，否则可能读不出来

    with h5py.File(str(数据文件), "r") as f:
        dset = f["klines"]["table"]
        data = dset[:]

    df = pd.DataFrame(
        {
            "open": data["open"],
            "high": data["high"],
            "low": data["low"],
            "close": data["close"],
            "volume": data["volume"],
            "candle_begin_time": pd.to_datetime(data["candle_begin_time_GMT8"], unit="ns"),
        }
    )
    return df.sort_values("candle_begin_time").reset_index(drop=True)


@st.cache_data(show_spinner=False)
def 加载数据缓存(path: str) -> pd.DataFrame:
    return 加载数据(path)


K线周期配置 = {
    "1分钟": {"code": "1m", "rule": None, "step": timedelta(minutes=1)},
    "5分钟": {"code": "5m", "rule": "5T", "step": timedelta(minutes=5)},
    "15分钟": {"code": "15m", "rule": "15T", "step": timedelta(minutes=15)},
    "30分钟": {"code": "30m", "rule": "30T", "step": timedelta(minutes=30)},
    "1小时": {"code": "1h", "rule": "1h", "step": timedelta(hours=1)},
    "4小时": {"code": "4h", "rule": "4h", "step": timedelta(hours=4)},
    "1日": {"code": "1d", "rule": "1D", "step": timedelta(days=1)},
    "1周": {"code": "1w", "rule": "W-MON", "step": timedelta(weeks=1)},
}


def 获取合并文件路径(raw_path: str, period_code: str) -> Path:
    raw = Path(raw_path)
    return raw.with_name(f"{raw.stem}_resampled_{period_code}.pkl")


def 合并K线(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    df = df.sort_values('candle_begin_time').set_index('candle_begin_time')
    resampled = df.resample(rule, label='left', closed='left').agg(
        open=('open', 'first'),
        high=('high', 'max'),
        low=('low', 'min'),
        close=('close', 'last'),
        volume=('volume', 'sum'),
    )
    resampled = resampled.dropna(subset=['open', 'close']).reset_index()
    return resampled


@st.cache_data(show_spinner=False)
def 加载合并K线数据(raw_path: str, period_code: str, rule: str, raw_mtime: float) -> pd.DataFrame:
    if rule is None:
        return 加载数据缓存(raw_path)

    resampled_path = 获取合并文件路径(raw_path, period_code)
    if resampled_path.exists():
        try:
            if resampled_path.stat().st_mtime >= raw_mtime:
                return pd.read_pickle(resampled_path)
        except (OSError, ValueError):
            pass

    df_raw = 加载数据缓存(raw_path)
    df_resampled = 合并K线(df_raw, rule)
    try:
        df_resampled.to_pickle(resampled_path)
    except OSError:
        pass
    return df_resampled


def 智能周期推荐(开始时间: pd.Timestamp, 结束时间: pd.Timestamp) -> str:
    delta = 结束时间 - 开始时间
    if delta > timedelta(days=365):
        return "1日"
    elif delta > timedelta(days=90):
        return "4小时"
    elif delta > timedelta(days=30):
        return "1小时"
    elif delta > timedelta(days=7):
        return "15分钟"
    else:
        return "1分钟"


def 对齐权益曲线(df_equity: pd.DataFrame, rule: str) -> pd.DataFrame:
    """将权益曲线按照指定的 K 线周期进行重采样"""
    if rule is None:
        return df_equity[['candle_begin_time', 'equity']].copy()
    
    equity_series = df_equity.set_index('candle_begin_time')['equity']
    resampled = equity_series.resample(rule, label='left', closed='left').last().dropna()
    return resampled.reset_index()


# ============================================================
# 核心回测逻辑
# ============================================================

def 带日志回测(
    价格序列: np.ndarray,
    时间序列: np.ndarray,
    初始资金: float = 1000.0,
    目标持仓比例: float = 0.5,
    短期窗口: int = 60,
    长期窗口: int = 1440,
    ewma_alpha: float = 0.05,
    spike阈值: float = 1.5,
    crush阈值: float = 0.5,
    vol_k_factor: float = 1.0,
    min_grid_width_bps: float = 1.0,
    spike宽度倍数: float = 1.5,
    crush宽度倍数: float = 0.8,
) -> Tuple[np.ndarray, List[交易记录], np.ndarray]:
    """带交易日志的香农回测"""
    n = len(价格序列)

    if n < 3:
        raise ValueError("数据太少：至少需要 3 根K线才能回测")

    # 用“与实盘/执行级回测一致”的递推公式预计算波动率状态
    # 注意：这里只做“宽度/状态”的同口径对齐；本查看器的成交逻辑仍是教学版（非执行级撮合）。
    close_arr = np.ascontiguousarray(价格序列.astype(np.float64))
    start = 2  # 保证 start-1 有上一根 close
    ewma_vol_in, _, regime_in = 香农回测._预计算_波动率状态序列(
        close_arr,
        start,
        int(短期窗口),
        int(长期窗口),
        float(ewma_alpha),
        float(spike阈值),
        float(crush阈值),
    )

    min_width = float(min_grid_width_bps) / 10000.0
    if min_width <= 0:
        raise ValueError("min_grid_width_bps 必须 > 0")

    市场状态 = np.zeros(n, dtype=np.int8)
    网格宽度 = np.full(n, min_width, dtype=np.float64)

    mult = np.ones_like(regime_in, dtype=np.float64)
    mult[regime_in == 1] = float(spike宽度倍数)
    mult[regime_in == 2] = float(crush宽度倍数)

    width_in = ewma_vol_in * float(vol_k_factor) * mult
    width_in = np.maximum(width_in, min_width)

    市场状态[start:] = regime_in.astype(np.int8)
    网格宽度[start:] = width_in
    
    # 交易所精度设置 (ETHUSDT)
    ETH精度 = 3  # 交易所支持的 ETH 数量精度 (0.001)
    最小交易量 = 0.001  # 最小交易单位
    
    起始价格 = 价格序列[0]
    eth数量 = round((初始资金 * 目标持仓比例) / 起始价格, ETH精度)
    现金 = 初始资金 - eth数量 * 起始价格  # 根据实际买入量计算剩余现金
    
    权益曲线 = np.zeros(n)
    持仓比例序列 = np.zeros(n)
    交易日志: List[交易记录] = []
    
    for i in range(n):
        p = 价格序列[i]
        权益 = 现金 + eth数量 * p
        权益曲线[i] = 权益
        
        eth价值 = eth数量 * p
        当前持仓比例 = eth价值 / 权益 if 权益 > 0 else 0
        持仓比例序列[i] = 当前持仓比例
        
        if i >= n - 1:
            continue
        
        偏离 = 当前持仓比例 - 目标持仓比例
        当前网格宽度 = 网格宽度[i]
        
        if abs(偏离) > 当前网格宽度:
            目标eth价值 = 权益 * 目标持仓比例
            delta_eth价值 = 目标eth价值 - eth价值
            delta_eth_raw = delta_eth价值 / p
            
            # ★ 核心：按交易所精度四舍五入
            delta_eth = round(delta_eth_raw, ETH精度)
            
            # ★ 跳过低于最小交易量的订单
            if abs(delta_eth) < 最小交易量:
                continue
            
            下一价格 = 价格序列[i + 1]
            交易前权益 = 权益
            交易前比例 = 当前持仓比例
            
            if delta_eth > 0:
                买入成本 = delta_eth * 下一价格
                if 现金 >= 买入成本:
                    现金 -= 买入成本
                    eth数量 += delta_eth
                    新权益 = 现金 + eth数量 * 下一价格
                    新比例 = (eth数量 * 下一价格) / 新权益 if 新权益 > 0 else 0
                    交易日志.append(交易记录(
                        时间=pd.Timestamp(时间序列[i]), 价格=下一价格, 方向='BUY',
                        数量=delta_eth, 交易前仓位比例=交易前比例, 交易后仓位比例=新比例,
                        交易前权益=交易前权益, 交易后权益=新权益,
                    ))
            else:
                卖出数量 = abs(delta_eth)
                if eth数量 >= 卖出数量:
                    eth数量 -= 卖出数量
                    现金 += 卖出数量 * 下一价格
                    新权益 = 现金 + eth数量 * 下一价格
                    新比例 = (eth数量 * 下一价格) / 新权益 if 新权益 > 0 else 0
                    交易日志.append(交易记录(
                        时间=pd.Timestamp(时间序列[i]), 价格=下一价格, 方向='SELL',
                        数量=卖出数量, 交易前仓位比例=交易前比例, 交易后仓位比例=新比例,
                        交易前权益=交易前权益, 交易后权益=新权益,
                    ))
    
    return 权益曲线, 交易日志, 持仓比例序列


# ============================================================
# Streamlit 主界面 (左右分栏布局)
# ============================================================

def main():
    st.set_page_config(page_title="8号香农策略 | 深度复盘", page_icon="🌊", layout="wide")
    
    st.markdown("""
        <style>
        .block-container { padding-top: 1rem; padding-bottom: 0rem; }
        </style>
    """, unsafe_allow_html=True)
    
    st.title("🌊 8号香农策略 (Shannon's Demon) - 深度复盘")
    st.markdown("---")
    
    # ====== 侧边栏：核心参数 ======
    with st.sidebar:
        st.header("⚙️ 核心参数")
        with st.expander("基础配置", expanded=True):
            目标比例 = st.slider("目标持仓比例", 0.1, 0.9, float(getattr(cfg, "target_ratio", 0.5)), 0.05)
            初始资金 = st.number_input(
                "初始资金 (USDC)",
                1.0,
                1_000_000.0,
                float(getattr(cfg, "initial_capital", 1000.0)),
                10.0,
            )

        with st.expander("网格宽度（同口径）", expanded=False):
            vol_k_factor = st.number_input(
                "vol_k_factor（K系数）",
                0.1,
                5.0,
                float(getattr(cfg, "vol_k_factor", 1.0)),
                0.05,
                format="%.2f",
            )
            min_grid_width_bps = st.number_input(
                "min_grid_width_bps（最小宽度，bp=0.01%）",
                0.1,
                50.0,
                float(getattr(cfg, "min_grid_width_bps", 1.0)),
                0.1,
                format="%.1f",
            )
            spike_mult = st.number_input(
                "Spike 宽度倍数",
                0.5,
                5.0,
                float(getattr(cfg, "width_multiplier_spike", 1.5)),
                0.1,
                format="%.2f",
            )
            crush_mult = st.number_input(
                "Crush 宽度倍数",
                0.1,
                2.0,
                float(getattr(cfg, "width_multiplier_crush", 0.8)),
                0.1,
                format="%.2f",
            )

        with st.expander("波动率模型", expanded=False):
            短期窗口 = st.number_input("短期波动率 (分)", 10, 500, cfg.vol_short_window)
            长期窗口 = st.number_input("长期波动率 (分)", 500, 10000, cfg.vol_long_window)
            ewma_alpha = st.number_input(
                "EWMA alpha（指数加权平滑系数）",
                0.001,
                1.0,
                float(getattr(cfg, "vol_ewma_alpha", 0.05)),
                0.005,
                format="%.3f",
            )
            spike_th = st.number_input("Spike 阈值", 1.0, 3.0, cfg.regime_spike_threshold, 0.1)
            crush_th = st.number_input("Crush 阈值", 0.1, 1.0, cfg.regime_crush_threshold, 0.1)
            
        st.markdown("---")
        run_btn = st.button("🚀 运行回测", type="primary", use_container_width=True)

    # ====== 状态管理 ======
    if "回测结果" not in st.session_state:
        st.session_state["回测结果"] = None
    if "display_period" not in st.session_state:
        st.session_state["display_period"] = "1小时"
    if "chart_start" not in st.session_state:
        st.session_state["chart_start"] = pd.Timestamp("2024-01-01")
    if "chart_end" not in st.session_state:
        st.session_state["chart_end"] = pd.Timestamp.now()

    # ====== 运行回测 ======
    if run_btn:
        with st.spinner("正在加载完整数据与计算..."):
            try:
                df = 加载数据缓存(cfg.data_file)
                价格 = df['close'].values
                时间 = df['candle_begin_time'].values
                
                权益曲线, 交易日志, _ = 带日志回测(
                    价格序列=价格, 时间序列=时间, 初始资金=float(初始资金),
                    目标持仓比例=目标比例, 短期窗口=int(短期窗口), 长期窗口=int(长期窗口),
                    ewma_alpha=float(ewma_alpha),
                    spike阈值=float(spike_th),
                    crush阈值=float(crush_th),
                    vol_k_factor=float(vol_k_factor),
                    min_grid_width_bps=float(min_grid_width_bps),
                    spike宽度倍数=float(spike_mult),
                    crush宽度倍数=float(crush_mult),
                )
                
                df['equity'] = 权益曲线
                Running_Max = np.maximum.accumulate(权益曲线)
                Drawdown = (权益曲线 - Running_Max) / Running_Max
                
                st.session_state["回测结果"] = {
                    "df": df, "交易日志": 交易日志,
                    "计算结果": {
                        "最终权益": 权益曲线[-1],
                        "最大回撤": Drawdown.min(),
                        "交易次数": len(交易日志)
                    }
                }
                
                data_end = df['candle_begin_time'].iloc[-1]
                data_start = df['candle_begin_time'].iloc[0]
                st.session_state["chart_end"] = data_end
                st.session_state["chart_start"] = max(data_start, data_end - timedelta(days=30))
                st.session_state["display_period"] = 智能周期推荐(st.session_state["chart_start"], st.session_state["chart_end"])

            except Exception as e:
                st.error(f"❌ 运行出错: {str(e)}")
                return

    结果 = st.session_state.get("回测结果")
    if 结果 is None:
        st.info("👈 请在左侧点击【运行回测】开始")
        return

    df_full = 结果["df"]
    交易日志 = 结果["交易日志"]
    Calc = 结果["计算结果"]

    # ====== 顶部工具栏 ======
    toolbar_cols = st.columns([0.3, 0.5, 0.2])
    with toolbar_cols[0]:
        st.caption("📅 时间范围")
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            new_start = st.date_input("开始", value=st.session_state["chart_start"], label_visibility="collapsed")
        with col_t2:
            new_end = st.date_input("结束", value=st.session_state["chart_end"], label_visibility="collapsed")
        st.session_state["chart_start"] = pd.Timestamp(new_start)
        st.session_state["chart_end"] = pd.Timestamp(new_end) + timedelta(days=1) - timedelta(seconds=1)

    with toolbar_cols[1]:
        st.caption("⏱ K线周期")
        periods = list(K线周期配置.keys())
        current_idx = periods.index(st.session_state["display_period"]) if st.session_state["display_period"] in periods else 4
        st.session_state["display_period"] = st.radio("周期", periods, horizontal=True, index=current_idx, label_visibility="collapsed")

    with toolbar_cols[2]:
        st.caption("💰 收益概览")
        color = "green" if Calc["最终权益"] >= 初始资金 else "red"
        st.markdown(f"### :{color}[${Calc['最终权益']:,.0f}]")
        st.caption(f"回撤: {Calc['最大回撤']:.2%}")

    # ====== 左右分栏布局 ======
    left_col, right_col = st.columns([0.65, 0.35])

    # === 左侧：K线图表 ===
    with left_col:
        current_period = st.session_state["display_period"]
        cfg_period = K线周期配置[current_period]
        
        try:
            raw_mtime = Path(cfg.data_file).stat().st_mtime
        except:
            raw_mtime = 0
        
        df_display = 加载合并K线数据(cfg.data_file, cfg_period["code"], cfg_period["rule"], raw_mtime)
        
        mask = (df_display['candle_begin_time'] >= st.session_state["chart_start"]) & \
               (df_display['candle_begin_time'] <= st.session_state["chart_end"])
        df_chart = df_display[mask].copy()
        
        if df_chart.empty:
            st.warning("当前时间范围内无数据")
        else:
            # 权益曲线对齐
            equity_resampled = 对齐权益曲线(df_full, cfg_period["rule"])
            df_chart = pd.merge(df_chart, equity_resampled, on='candle_begin_time', how='left')
            df_chart['equity'] = df_chart['equity'].ffill()
            
            df_chart['time'] = df_chart['candle_begin_time'].astype('int64') // 10**9
            candles = df_chart[['time', 'open', 'high', 'low', 'close']].to_dict('records')
            
            df_chart['color'] = np.where(df_chart['close'] >= df_chart['open'], '#26a69a', '#ef5350')
            volume_data = df_chart[['time', 'volume', 'color']].rename(columns={'volume': 'value'}).to_dict('records')
            equity_data = df_chart[['time', 'equity']].rename(columns={'equity': 'value'}).dropna().to_dict('records')
            
            # 交易标记
            markers = []
            tx_logs = [t for t in 交易日志 if st.session_state["chart_start"] <= t.时间 <= st.session_state["chart_end"]]
            if len(tx_logs) > 3000:
                tx_logs = tx_logs[::len(tx_logs)//3000+1]
            
            for tx in tx_logs:
                ts = int(tx.时间.timestamp())
                markers.append({
                    'time': ts,
                    'position': 'belowBar' if tx.方向 == 'BUY' else 'aboveBar',
                    'color': '#00E676' if tx.方向 == 'BUY' else '#FF1744',
                    'shape': 'arrowUp' if tx.方向 == 'BUY' else 'arrowDown',
                    'text': f"{'B' if tx.方向 == 'BUY' else 'S'} {tx.数量:.4f}"
                })
            
            # 图表配置
            chart_candlestick = {
                "height": 400,
                "layout": {"background": {"type": "solid", "color": "#131722"}, "textColor": "#d1d4dc"},
                "grid": {"vertLines": {"color": "rgba(42,46,57,0.5)"}, "horzLines": {"color": "rgba(42,46,57,0.5)"}},
                "timeScale": {"visible": True, "timeVisible": True, "secondsVisible": False, "borderColor": "#485c7b"},
                "localization": {"locale": "zh-CN"},
                "series": [{"type": "Candlestick", "data": candles, "options": {
                    "upColor": "#26a69a", "downColor": "#ef5350", "borderVisible": False,
                    "wickUpColor": "#26a69a", "wickDownColor": "#ef5350"
                }, "markers": markers}]
            }
            
            chart_volume = {
                "height": 80,
                "layout": {"background": {"type": "solid", "color": "#131722"}, "textColor": "#d1d4dc"},
                "timeScale": {"visible": False},
                "series": [{"type": "Histogram", "data": volume_data, "options": {"priceFormat": {"type": "volume"}}}]
            }
            
            chart_equity = {
                "height": 120,
                "layout": {"background": {"type": "solid", "color": "#131722"}, "textColor": "#d1d4dc"},
                "timeScale": {"visible": True, "borderColor": "#485c7b"},
                "series": [{"type": "Line", "data": equity_data, "options": {"color": "#2962FF", "lineWidth": 2}}]
            }
            
            slc.renderLightweightCharts([chart_candlestick, chart_volume, chart_equity], key="main_chart")

    # === 右侧：交易明细 ===
    with right_col:
        st.subheader("📋 交易明细")
        st.caption(f"共 {len(交易日志):,} 笔交易")
        
        每页 = st.selectbox("每页显示", [50, 100, 200], index=0)
        总页数 = max(1, (len(交易日志) - 1) // 每页 + 1)
        页码 = st.number_input("页码", 1, 总页数, 1)
        start_idx = (页码 - 1) * 每页
        
        log_df = pd.DataFrame([
            {"时间": t.时间.strftime("%m-%d %H:%M"), "方向": t.方向, "价格": f"${t.价格:.2f}",
             "数量": f"{t.数量:.4f}", "权益": f"${t.交易后权益:.0f}"}
            for t in 交易日志[start_idx : start_idx + 每页]
        ])
        
        st.dataframe(log_df, use_container_width=True, height=500)


# ============================================================
# 启动入口
# ============================================================

def 是否在Streamlit中运行() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except:
        return False

if 是否在Streamlit中运行():
    main()

if __name__ == "__main__":
    import subprocess
    subprocess.run([sys.executable, "-m", "streamlit", "run", __file__, "--server.headless=true"])
