from __future__ import annotations

import argparse
import heapq
import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_EXCHANGE = "binance-futures"
DEFAULT_SYMBOL = "BTCUSDC"
DEFAULT_FROM_DATE = "2024-03-01"
DEFAULT_TO_DATE = "2024-03-02"
DEFAULT_DEPTH_LEVELS = 20
DEFAULT_SNAPSHOT_INTERVAL_MS = 1000


@dataclass(frozen=True)
class Paths:
    raw_dir: Path
    data_root: Path


def _project_quant_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_paths(exchange: str, symbol: str, from_date: str) -> Paths:
    quant_root = _project_quant_root()
    raw_dir = quant_root / "data" / "外部数据" / "Tardis" / "raw" / exchange / symbol / from_date
    data_root = quant_root / "data" / "外部数据" / "Tardis" / "processed"
    return Paths(raw_dir=raw_dir, data_root=data_root)


def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def _locate_dataset_file(download_dir: Path, exchange: str, data_type: str, day: str, symbol: str) -> Path:
    yyyy, mm, dd = day.split("-")

    candidates = [
        download_dir / f"{exchange}_{data_type}_{day}_{symbol}.csv.gz",
        download_dir / exchange / data_type / yyyy / mm / dd / f"{symbol}.csv.gz",
        download_dir / data_type / yyyy / mm / dd / f"{symbol}.csv.gz",
    ]
    for p in candidates:
        if p.exists():
            return p

    glob_patterns = [
        f"**/{exchange}_{data_type}_{day}_{symbol}.csv.gz",
        f"**/{exchange}_{data_type}_{day}_{symbol}*.csv.gz",
        f"**/{data_type}/{yyyy}/{mm}/{dd}/{symbol}.csv.gz",
        f"**/*{data_type}*{day}*{symbol}*.csv.gz",
    ]
    for pat in glob_patterns:
        hits = sorted(download_dir.glob(pat))
        if hits:
            return hits[0]

    raise FileNotFoundError(
        f"未找到数据文件: download_dir={download_dir}, exchange={exchange}, data_type={data_type}, day={day}, symbol={symbol}"
    )


def _depth_output_columns(depth_levels: int) -> list[str]:
    cols = ["exchange_time"]
    for i in range(1, depth_levels + 1):
        cols += [f"bid{i}_p", f"bid{i}_q"]
    for i in range(1, depth_levels + 1):
        cols += [f"ask{i}_p", f"ask{i}_q"]
    return cols


def _make_depth_schema(depth_levels: int):
    import pyarrow as pa

    fields = [("exchange_time", pa.int64())]
    for i in range(1, depth_levels + 1):
        fields += [(f"bid{i}_p", pa.float32()), (f"bid{i}_q", pa.float32())]
    for i in range(1, depth_levels + 1):
        fields += [(f"ask{i}_p", pa.float32()), (f"ask{i}_q", pa.float32())]
    return pa.schema(fields)


def _flush_parquet(writer, schema, buffer: dict[str, list]) -> None:
    import pyarrow as pa

    if not buffer or not buffer.get("exchange_time"):
        return
    table = pa.Table.from_pydict(buffer, schema=schema)
    writer.write_table(table)

    for v in buffer.values():
        v.clear()


def convert_incremental_book_l2_to_depth_parquet(
    *,
    input_csv_gz: Path,
    output_parquet: Path,
    depth_levels: int,
    snapshot_interval_ms: int,
    log_every_n_snapshots: int = 60,
    chunksize: int = 200_000,
) -> None:
    import pyarrow.parquet as pq

    if depth_levels <= 0:
        raise ValueError("depth_levels must be > 0")
    if snapshot_interval_ms <= 0:
        raise ValueError("snapshot_interval_ms must be > 0")

    _ensure_parent(output_parquet)

    need_cols = ["timestamp", "local_timestamp", "is_snapshot", "side", "price", "amount"]
    dtypes = {
        "timestamp": "int64",
        "local_timestamp": "int64",
        "is_snapshot": "object",
        "side": "object",
        "price": "float64",
        "amount": "float64",
    }

    bids: dict[float, float] = {}
    asks: dict[float, float] = {}
    prev_is_snapshot: bool | None = None
    next_snapshot_ms: int | None = None
    snap_count = 0

    schema = _make_depth_schema(depth_levels)
    writer = pq.ParquetWriter(output_parquet, schema=schema, compression="zstd")
    buffer: dict[str, list] = {c: [] for c in _depth_output_columns(depth_levels)}

    def emit_snapshot(ts_ms: int) -> None:
        nonlocal snap_count

        buffer["exchange_time"].append(int(ts_ms))

        bid_prices = heapq.nlargest(depth_levels, bids.keys())
        ask_prices = heapq.nsmallest(depth_levels, asks.keys())

        for i in range(depth_levels):
            if i < len(bid_prices):
                p = float(bid_prices[i])
                q = float(bids.get(p, 0.0))
                buffer[f"bid{i+1}_p"].append(np.float32(p))
                buffer[f"bid{i+1}_q"].append(np.float32(q))
            else:
                buffer[f"bid{i+1}_p"].append(np.nan)
                buffer[f"bid{i+1}_q"].append(np.nan)

        for i in range(depth_levels):
            if i < len(ask_prices):
                p = float(ask_prices[i])
                q = float(asks.get(p, 0.0))
                buffer[f"ask{i+1}_p"].append(np.float32(p))
                buffer[f"ask{i+1}_q"].append(np.float32(q))
            else:
                buffer[f"ask{i+1}_p"].append(np.nan)
                buffer[f"ask{i+1}_q"].append(np.nan)

        snap_count += 1
        if snap_count % log_every_n_snapshots == 0:
            logging.info("depth snapshots=%s (last_ts_ms=%s)", snap_count, ts_ms)

        if len(buffer["exchange_time"]) >= 10_000:
            _flush_parquet(writer, schema, buffer)

    try:
        for chunk in pd.read_csv(
            input_csv_gz,
            compression="gzip",
            usecols=need_cols,
            dtype=dtypes,
            chunksize=chunksize,
        ):
            if chunk.empty:
                continue

            ts_us = chunk["timestamp"].to_numpy(dtype=np.int64, copy=False)
            is_snapshot_raw = chunk["is_snapshot"].to_numpy(copy=False)
            side_raw = chunk["side"].to_numpy(copy=False)
            price = chunk["price"].to_numpy(dtype=np.float64, copy=False)
            amount = chunk["amount"].to_numpy(dtype=np.float64, copy=False)

            for i in range(len(chunk)):
                ts_ms = int(ts_us[i] // 1000)
                if next_snapshot_ms is None:
                    next_snapshot_ms = (ts_ms // snapshot_interval_ms) * snapshot_interval_ms

                is_snapshot = str(is_snapshot_raw[i]).lower() == "true"
                if is_snapshot and (prev_is_snapshot is False):
                    bids.clear()
                    asks.clear()
                prev_is_snapshot = is_snapshot

                side = str(side_raw[i]).lower()
                p = float(price[i])
                q = float(amount[i])
                if q <= 0.0:
                    if side == "bid":
                        bids.pop(p, None)
                    elif side == "ask":
                        asks.pop(p, None)
                else:
                    if side == "bid":
                        bids[p] = q
                    elif side == "ask":
                        asks[p] = q

                if next_snapshot_ms is None:
                    continue
                while ts_ms >= next_snapshot_ms:
                    emit_snapshot(next_snapshot_ms)
                    next_snapshot_ms += snapshot_interval_ms

        _flush_parquet(writer, schema, buffer)
    finally:
        writer.close()

    if snap_count == 0:
        raise ValueError(f"depth 快照结果为空: {input_csv_gz}")


def _make_trade_schema():
    import pyarrow as pa

    return pa.schema(
        [
            ("exchange_time", pa.int64()),
            ("price", pa.float32()),
            ("qty", pa.float32()),
            ("is_buyer_maker", pa.bool_()),
        ]
    )


def _infer_trade_cols(columns: list[str]) -> dict[str, str]:
    cols = {c.lower(): c for c in columns}

    def pick(*names: str) -> str | None:
        for n in names:
            if n.lower() in cols:
                return cols[n.lower()]
        return None

    ts = pick("timestamp")
    price = pick("price")
    qty = pick("amount", "size", "qty", "quantity")
    side = pick("side")
    is_bm = pick("is_buyer_maker", "buyer_is_maker", "isBuyerMaker")

    missing = [k for k, v in [("timestamp", ts), ("price", price), ("qty", qty)] if v is None]
    if missing:
        raise ValueError(f"trades 缺少必要列: {missing}, columns={columns}")

    out: dict[str, str] = {"timestamp": ts, "price": price, "qty": qty}
    if side is not None:
        out["side"] = side
    if is_bm is not None:
        out["is_buyer_maker"] = is_bm
    return out


def convert_trades_to_trade_parquet(
    *,
    input_csv_gz: Path,
    output_parquet: Path,
    chunksize: int = 500_000,
) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    _ensure_parent(output_parquet)

    head = pd.read_csv(input_csv_gz, compression="gzip", nrows=0)
    mapping = _infer_trade_cols(list(head.columns))
    usecols = list({mapping[k] for k in mapping.keys()})

    schema = _make_trade_schema()
    writer = pq.ParquetWriter(output_parquet, schema=schema, compression="zstd")
    buffer: dict[str, list] = {"exchange_time": [], "price": [], "qty": [], "is_buyer_maker": []}
    rows_written = 0

    try:
        for chunk in pd.read_csv(input_csv_gz, compression="gzip", usecols=usecols, chunksize=chunksize):
            if chunk.empty:
                continue

            ts_ms = (chunk[mapping["timestamp"]].to_numpy(dtype=np.int64, copy=False) // 1000).astype("int64")
            price = chunk[mapping["price"]].to_numpy(dtype=np.float32, copy=False)
            qty = chunk[mapping["qty"]].to_numpy(dtype=np.float32, copy=False)

            if "is_buyer_maker" in mapping:
                is_bm = chunk[mapping["is_buyer_maker"]].astype("bool").to_numpy(copy=False)
            else:
                if "side" not in mapping:
                    raise ValueError("trades 既没有 is_buyer_maker 也没有 side，无法推导方向")
                side = chunk[mapping["side"]].astype("string").str.lower()
                is_bm = (side == "sell").to_numpy(dtype=bool, copy=False)

            buffer["exchange_time"].extend(ts_ms.tolist())
            buffer["price"].extend(price.tolist())
            buffer["qty"].extend(qty.tolist())
            buffer["is_buyer_maker"].extend(is_bm.tolist())

            if len(buffer["exchange_time"]) >= 200_000:
                table = pa.Table.from_pydict(buffer, schema=schema)
                writer.write_table(table)
                rows_written += len(buffer["exchange_time"])
                for v in buffer.values():
                    v.clear()
                logging.info("trades written rows=%s", rows_written)

        if buffer["exchange_time"]:
            table = pa.Table.from_pydict(buffer, schema=schema)
            writer.write_table(table)
            rows_written += len(buffer["exchange_time"])
    finally:
        writer.close()

    if rows_written == 0:
        raise ValueError(f"trade 结果为空: {input_csv_gz}")


def download_tardis_csv(
    *,
    exchange: str,
    symbol: str,
    from_date: str,
    to_date: str,
    download_dir: Path,
    http_proxy: str | None = None,
    api_key: str = "",
) -> None:
    import requests

    if api_key:
        raise ValueError("免费匿名下载请保持 api_key 为空")

    download_dir.mkdir(parents=True, exist_ok=True)
    proxies = None
    if http_proxy:
        proxies = {"http": http_proxy, "https": http_proxy}

    logging.info(
        "Downloading: exchange=%s symbol=%s from=%s to=%s -> %s", exchange, symbol, from_date, to_date, download_dir
    )

    from_d = date.fromisoformat(from_date)
    to_d = date.fromisoformat(to_date)

    for day in _iter_days(from_d, to_d):
        yyyy, mm, dd = day.isoformat().split("-")
        for data_type in ["incremental_book_L2", "trades"]:
            url = f"https://datasets.tardis.dev/v1/{exchange}/{data_type}/{yyyy}/{mm}/{dd}/{symbol}.csv.gz"
            out = download_dir / f"{exchange}_{data_type}_{day.isoformat()}_{symbol}.csv.gz"
            if out.exists() and out.stat().st_size > 0:
                logging.info("Skip existing: %s", out)
                continue

            logging.info("GET %s", url)
            _ensure_parent(out)

            with requests.get(url, stream=True, timeout=1800, proxies=proxies, headers={"User-Agent": "predict5"}) as r:
                if r.status_code == 403:
                    raise PermissionError(f"403: 该日期可能不是免费日或被限制访问: {url}")
                r.raise_for_status()
                total = int(r.headers.get("content-length", "0") or "0")
                downloaded = 0
                with out.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total and downloaded % (256 * 1024 * 1024) < 1024 * 1024:
                            pct = downloaded / total * 100
                            logging.info("%s %s %.1f%% (%s/%s MiB)", data_type, day.isoformat(), pct, downloaded // (1024*1024), total // (1024*1024))

            if out.stat().st_size == 0:
                raise IOError(f"下载结果为空文件: {out}")


def _iter_days(start: date, end: date):
    d = start
    while d < end:
        yield d
        d = d.fromordinal(d.toordinal() + 1)


def convert_one_day(
    *,
    exchange: str,
    symbol: str,
    day: str,
    download_dir: Path,
    data_root: Path,
    depth_levels: int,
    snapshot_interval_ms: int,
) -> Path:
    l2_path = _locate_dataset_file(download_dir, exchange, "incremental_book_L2", day, symbol)
    trades_path = _locate_dataset_file(download_dir, exchange, "trades", day, symbol)

    out_dir = data_root / symbol / day
    out_dir.mkdir(parents=True, exist_ok=True)
    depth_pq = out_dir / "depth.parquet"
    trade_pq = out_dir / "trade.parquet"

    logging.info("Converting depth: %s -> %s", l2_path, depth_pq)
    convert_incremental_book_l2_to_depth_parquet(
        input_csv_gz=l2_path,
        output_parquet=depth_pq,
        depth_levels=depth_levels,
        snapshot_interval_ms=snapshot_interval_ms,
    )

    logging.info("Converting trades: %s -> %s", trades_path, trade_pq)
    convert_trades_to_trade_parquet(input_csv_gz=trades_path, output_parquet=trade_pq)
    return out_dir


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="tardis_fetch_convert")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_dl = sub.add_parser("download")
    p_dl.add_argument("--exchange", default=DEFAULT_EXCHANGE)
    p_dl.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p_dl.add_argument("--from-date", default=DEFAULT_FROM_DATE)
    p_dl.add_argument("--to-date", default=DEFAULT_TO_DATE)
    p_dl.add_argument("--raw-dir", default=None)
    p_dl.add_argument("--http-proxy", default=None)

    p_cv = sub.add_parser("convert")
    p_cv.add_argument("--exchange", default=DEFAULT_EXCHANGE)
    p_cv.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p_cv.add_argument("--day", default=DEFAULT_FROM_DATE)
    p_cv.add_argument("--raw-dir", default=None)
    p_cv.add_argument("--data-root", default=None)
    p_cv.add_argument("--depth-levels", type=int, default=DEFAULT_DEPTH_LEVELS)
    p_cv.add_argument("--snapshot-interval-ms", type=int, default=DEFAULT_SNAPSHOT_INTERVAL_MS)

    p_all = sub.add_parser("all")
    p_all.add_argument("--exchange", default=DEFAULT_EXCHANGE)
    p_all.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p_all.add_argument("--from-date", default=DEFAULT_FROM_DATE)
    p_all.add_argument("--to-date", default=DEFAULT_TO_DATE)
    p_all.add_argument("--raw-dir", default=None)
    p_all.add_argument("--data-root", default=None)
    p_all.add_argument("--depth-levels", type=int, default=DEFAULT_DEPTH_LEVELS)
    p_all.add_argument("--snapshot-interval-ms", type=int, default=DEFAULT_SNAPSHOT_INTERVAL_MS)
    p_all.add_argument("--http-proxy", default=None)

    return p.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    args = _parse_args()
    if args.cmd in {"download", "all"}:
        paths = _default_paths(args.exchange, args.symbol, args.from_date)
        raw_dir = Path(args.raw_dir) if args.raw_dir else paths.raw_dir
        download_tardis_csv(
            exchange=args.exchange,
            symbol=args.symbol,
            from_date=args.from_date,
            to_date=args.to_date,
            download_dir=raw_dir,
            http_proxy=args.http_proxy,
        )
        logging.info("Download done: %s", raw_dir)

    if args.cmd in {"convert", "all"}:
        if args.cmd == "convert":
            day = args.day
            from_day = day
        else:
            from_day = args.from_date

        paths = _default_paths(args.exchange, args.symbol, from_day)
        raw_dir = Path(args.raw_dir) if args.raw_dir else paths.raw_dir
        data_root = Path(args.data_root) if args.data_root else paths.data_root

        if args.cmd == "convert":
            out_dir = convert_one_day(
                exchange=args.exchange,
                symbol=args.symbol,
                day=day,
                download_dir=raw_dir,
                data_root=data_root,
                depth_levels=args.depth_levels,
                snapshot_interval_ms=args.snapshot_interval_ms,
            )
            logging.info("Convert done: %s", out_dir)
        else:
            from_d = date.fromisoformat(args.from_date)
            to_d = date.fromisoformat(args.to_date)
            day = from_d
            while day < to_d:
                day_s = day.isoformat()
                out_dir = convert_one_day(
                    exchange=args.exchange,
                    symbol=args.symbol,
                    day=day_s,
                    download_dir=raw_dir,
                    data_root=data_root,
                    depth_levels=args.depth_levels,
                    snapshot_interval_ms=args.snapshot_interval_ms,
                )
                logging.info("Converted day=%s -> %s", day_s, out_dir)
                day = day.fromordinal(day.toordinal() + 1)


if __name__ == "__main__":
    main()
