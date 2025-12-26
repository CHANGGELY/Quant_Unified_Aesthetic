from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd


def _discover_day_dirs(symbol_dir: Path) -> list[Path]:
    if not symbol_dir.exists():
        raise FileNotFoundError(f"数据目录不存在: {symbol_dir}")
    return sorted([p for p in symbol_dir.iterdir() if p.is_dir()])


def _parse_iso_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _depth_columns(depth_levels: int) -> list[str]:
    if depth_levels <= 0:
        raise ValueError("depth_levels must be > 0")
    cols = ["exchange_time"]
    for i in range(1, depth_levels + 1):
        cols += [f"bid{i}_p", f"bid{i}_q"]
    for i in range(1, depth_levels + 1):
        cols += [f"ask{i}_p", f"ask{i}_q"]
    return cols


def _trade_columns() -> list[str]:
    return ["exchange_time", "price", "qty", "is_buyer_maker"]


def _read_parquet_selected(path: Path, columns: list[str]) -> pd.DataFrame:
    """
    只读取需要的列（若某些列不存在则补 NaN），避免 bookTicker 转换出来的 200+ 列导致 OOM。
    """
    try:
        import pyarrow.parquet as pq  # type: ignore

        available = set(pq.ParquetFile(path).schema.names)
        use_cols = [c for c in columns if c in available]
        df = pd.read_parquet(path, columns=use_cols)
        return df.reindex(columns=columns)
    except Exception:
        df = pd.read_parquet(path)
        return df.reindex(columns=columns)


def _longest_contiguous_days(day_items: list[tuple[date, Path]]) -> list[Path]:
    """
    在存在“零散补录/缺口”的情况下，默认取最长连续日期段，避免训练集跨巨大空洞。
    """
    if not day_items:
        return []
    day_items = sorted(day_items, key=lambda x: x[0])
    best_start = 0
    best_len = 1
    cur_start = 0
    cur_len = 1
    for i in range(1, len(day_items)):
        if day_items[i][0] - day_items[i - 1][0] == timedelta(days=1):
            cur_len += 1
        else:
            if cur_len > best_len or (cur_len == best_len and day_items[i - 1][0] > day_items[best_start + best_len - 1][0]):
                best_start, best_len = cur_start, cur_len
            cur_start, cur_len = i, 1
    if cur_len > best_len or (cur_len == best_len and day_items[-1][0] > day_items[best_start + best_len - 1][0]):
        best_start, best_len = cur_start, cur_len
    return [p for _, p in day_items[best_start : best_start + best_len]]


def select_day_dirs(
    data_root: Path,
    symbol: str,
    *,
    require_files: tuple[str, ...] = ("depth.parquet",),  # 改为默认只要求 depth，兼容无 trade 场景
    start_date: str | None = None,
    end_date: str | None = None,
    max_days: int | None = None,
    prefer_longest_contiguous: bool = True,
) -> list[Path]:
    symbol_dir = data_root / symbol
    day_dirs = _discover_day_dirs(symbol_dir)
    if not day_dirs:
        raise FileNotFoundError(f"未找到任何日期子目录: {symbol_dir}")

    s = date.fromisoformat(start_date) if start_date else None
    e = date.fromisoformat(end_date) if end_date else None

    items: list[tuple[date, Path]] = []
    for d in day_dirs:
        dt = _parse_iso_date(d.name)
        if dt is None:
            continue
        if s is not None and dt < s:
            continue
        if e is not None and dt > e:
            continue
            
        # 检查是否所有需要的文件都存在
        if all((d / f).exists() for f in require_files):
            items.append((dt, d))

    if not items:
        # 如果是默认的 strict 模式 (trade+depth) 找不到，尝试只找 depth
        if "trade.parquet" in require_files:
            print(f"⚠️ 警告: 未找到同时包含 {require_files} 的目录，尝试仅查找 depth.parquet...")
            return select_day_dirs(
                data_root, symbol, 
                require_files=("depth.parquet",), 
                start_date=start_date, end_date=end_date, 
                max_days=max_days, prefer_longest_contiguous=prefer_longest_contiguous
            )
        raise FileNotFoundError(f"未找到包含 {require_files} 的日期目录: {symbol_dir}")

    if prefer_longest_contiguous:
        selected = _longest_contiguous_days(items)
    else:
        selected = [p for _, p in sorted(items, key=lambda x: x[0])]

    if max_days is not None:
        if max_days <= 0:
            raise ValueError("max_days must be > 0")
        selected = selected[-max_days:]
    return selected


def _process_one_day_depth_only(d_depth: pd.DataFrame, is_minute: bool = False) -> pd.DataFrame:
    """仅处理 Depth 数据 (无 Trade)"""
    df = d_depth.copy()
    
    # 确保有 exchange_time
    # 如果 exchange_time 不存在或者全是 NaN (reindex 产生的)，尝试从 timestamp 恢复
    if "exchange_time" not in df.columns or df["exchange_time"].isna().all():
        if "timestamp" in df.columns:
            # Kaggle 数据 timestamp 是秒级 float，需要转毫秒 int64
            df["exchange_time"] = (df["timestamp"] * 1000).astype("int64")
        
    df = df.dropna(subset=["exchange_time"])
    
    # 设置索引
    df.index = pd.to_datetime(df["exchange_time"], unit="ms", utc=True)
    df.index.name = "candle_begin_time"
    
    # 如果不是分钟级数据（即高频数据但无 Trade），可能需要重采样到 1s
    if not is_minute:
        # 这里简化处理，直接按 1s 重采样取最后一个
        df["sec"] = (df["exchange_time"] // 1000).astype("int64")
        df = df.groupby("sec", sort=True).last()
        df.index = pd.to_datetime(df.index, unit="s", utc=True)
    
    # 清理 Object 列
    obj_cols = [c for c in df.columns if df[c].dtype == "object"]
    for c in obj_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
        
    # 降内存
    float_cols = [c for c in df.columns if pd.api.types.is_float_dtype(df[c])]
    if float_cols:
        df[float_cols] = df[float_cols].astype("float32")
        
    return df


def load_resampled_1s(
    data_root: Path,
    symbol: str,
    *,
    depth_levels: int = 5,
    start_date: str | None = None,
    end_date: str | None = None,
    max_days: int | None = None,
    cache_1s: bool = True,
    prefer_longest_contiguous: bool = True,
) -> tuple[pd.DataFrame, list[Path]]:
    """
    按“日”流式加载数据。智能适配有无 Trade 数据的情况。
    """
    # 1. 尝试查找目录 (优先找 depth+trade, 找不到会自动回退到只找 depth)
    day_dirs = select_day_dirs(
        data_root,
        symbol,
        require_files=("depth.parquet", "trade.parquet"),
        start_date=start_date,
        end_date=end_date,
        max_days=max_days,
        prefer_longest_contiguous=prefer_longest_contiguous,
    )

    depth_cols = _depth_columns(depth_levels)
    # 确保读取 timestamp，以防 exchange_time 不存在
    depth_cols.append("timestamp")
    
    trade_cols = _trade_columns()

    parts: list[pd.DataFrame] = []
    
    # 检测是否为 Kaggle 分钟级数据模式 (通过 cache_1s=False 判断，或检查 trade 是否存在)
    # 如果 cache_1s=False，我们假设它是低频数据，不做 1s 重采样
    is_minute_mode = not cache_1s 

    for d in day_dirs:
        cache_pq = d / "bars_1s.parquet"
        
        # 只有在启用 cache 且存在时才读取
        if cache_1s and cache_pq.exists():
            part = pd.read_parquet(cache_pq)
            parts.append(part)
            continue

        # 读取原始数据
        depth_path = d / "depth.parquet"
        trade_path = d / "trade.parquet"
        
        if not depth_path.exists():
            continue
            
        depth_df = _read_parquet_selected(depth_path, depth_cols)
        
        if trade_path.exists():
            trade_df = _read_parquet_selected(trade_path, trade_cols)
            # 只有当真的需要 1s 重采样时才调用 _resample_one_day
            if not is_minute_mode:
                part = _resample_one_day(depth_df, trade_df)
            else:
                # 分钟模式下，有 Trade 也不合并了（逻辑太复杂），暂且只用 Depth
                # 或者如果有需求，可以以后加。现在先跑通 Kaggle Depth Only
                part = _process_one_day_depth_only(depth_df, is_minute=True)
        else:
            # 无 Trade 数据
            part = _process_one_day_depth_only(depth_df, is_minute=is_minute_mode)

        if part.empty:
            continue
            
        if cache_1s:
            part.to_parquet(cache_pq)
            
        parts.append(part)

    if not parts:
        raise ValueError("对齐结果为空（可能所有日期都无法对齐）")
    return pd.concat(parts).sort_index(), day_dirs


def load_depth_trade_all(data_root: Path, symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    symbol_dir = data_root / symbol
    day_dirs = _discover_day_dirs(symbol_dir)
    if not day_dirs:
        raise FileNotFoundError(f"未找到任何日期子目录: {symbol_dir}")

    depth_parts: list[pd.DataFrame] = []
    trade_parts: list[pd.DataFrame] = []

    for d in day_dirs:
        depth_pq = d / "depth.parquet"
        trade_pq = d / "trade.parquet"
        if depth_pq.exists() and trade_pq.exists():
            depth_parts.append(pd.read_parquet(depth_pq))
            trade_parts.append(pd.read_parquet(trade_pq))

    if not depth_parts:
        raise FileNotFoundError(f"未找到 depth.parquet: {symbol_dir}")
    if not trade_parts:
        raise FileNotFoundError(f"未找到 trade.parquet: {symbol_dir}")

    depth_df = pd.concat(depth_parts, ignore_index=True)
    trade_df = pd.concat(trade_parts, ignore_index=True)
    return depth_df, trade_df


def resample_to_1s(depth_df: pd.DataFrame, trade_df: pd.DataFrame) -> pd.DataFrame:
    """
    统一到 1 秒频率：
    - depth：按秒取 last，并对缺失秒 forward-fill（订单簿状态延续）
    - trade：按秒聚合，缺失秒填 0
    返回 index 为 candle_begin_time(UTC) 的 DataFrame
    """
    depth_df = depth_df.sort_values("exchange_time").copy()
    trade_df = trade_df.sort_values("exchange_time").copy()

    # 避免“某些天缺 depth”导致跨天 forward-fill：按 UTC 日期分桶逐日对齐后再 concat
    depth_df["date"] = pd.to_datetime(depth_df["exchange_time"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    trade_df["date"] = pd.to_datetime(trade_df["exchange_time"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")

    common_dates = sorted(set(depth_df["date"].unique()) & set(trade_df["date"].unique()))
    if not common_dates:
        raise ValueError("depth 与 trade 没有任何同日数据，无法对齐到 1 秒")

    parts: list[pd.DataFrame] = []
    for d in common_dates:
        d_depth = depth_df.loc[depth_df["date"] == d].drop(columns=["date"], errors="ignore")
        d_trade = trade_df.loc[trade_df["date"] == d].drop(columns=["date"], errors="ignore")
        if d_depth.empty or d_trade.empty:
            continue
        part = _resample_one_day(d_depth, d_trade)
        if not part.empty:
            parts.append(part)

    if not parts:
        raise ValueError("对齐结果为空（可能所有日期都无法对齐）")
    return pd.concat(parts).sort_index()
