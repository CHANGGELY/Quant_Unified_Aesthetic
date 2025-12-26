import pandas as pd
from core.utils.path_kit import get_file_path
from config import spot_path

# 缓存透视表以便快速查询
_PIVOT_SPOT = pd.read_pickle(get_file_path('data', 'market_pivot_spot.pkl'))
_PIVOT_SWAP = pd.read_pickle(get_file_path('data', 'market_pivot_swap.pkl'))
_SPOT_CLOSE = _PIVOT_SPOT['close'] if isinstance(_PIVOT_SPOT, dict) else _PIVOT_SPOT
_SWAP_CLOSE = _PIVOT_SWAP['close'] if isinstance(_PIVOT_SWAP, dict) else _PIVOT_SWAP
_PIVOT_SAME = False
try:
    _PIVOT_SAME = _SPOT_CLOSE.equals(_SWAP_CLOSE)
except Exception:
    _PIVOT_SAME = False


def _load_spot_close_from_csv(symbol: str, index: pd.Series) -> pd.Series:
    try:
        df = pd.read_csv(spot_path / f'{symbol}.csv', encoding='gbk', parse_dates=['candle_begin_time'], skiprows=1)
        df = df[['candle_begin_time', 'close']].drop_duplicates('candle_begin_time', keep='last').sort_values('candle_begin_time')
        df['close'] = df['close'].ffill()
        return df.set_index('candle_begin_time')['close'].reindex(index).ffill()
    except Exception:
        return pd.Series(index=index, dtype='float64')


def signal(candle_df, param, *args):
    factor_name = args[0]
    symbol = str(candle_df['symbol'].iloc[0])
    dt_index = candle_df['candle_begin_time']

    spot_series = None
    try:
        if (not _PIVOT_SAME) and (symbol in _SPOT_CLOSE.columns):
            spot_series = _SPOT_CLOSE[symbol].reindex(dt_index)
        else:
            spot_series = _load_spot_close_from_csv(symbol, dt_index)
    except Exception:
        spot_series = _load_spot_close_from_csv(symbol, dt_index)

    candle_df[factor_name] = candle_df['close'] / spot_series.values - 1
    return candle_df

