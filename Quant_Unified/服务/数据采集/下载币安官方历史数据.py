"""
币安官方历史数据下载器（Binance Vision / data.binance.vision）

重要说明（务必读）：
1) Binance Vision 官方免费公开数据目前不提供「50档 L2 订单簿快照/增量」历史文件。
   - 可用：bookTicker（L1 最优买卖）、aggTrades（成交）、fundingRate、metrics、bookDepth(按价差百分比聚合的深度)、premiumIndexKlines、markPriceKlines 等。
   - 想要真正的 50 档深度历史：只能自己长期实时采集，或购买第三方。
2) 为了让现有训练/回测流程可直接复用：
   - 将 bookTicker 转换为 depth.parquet（仅填充 bid1/ask1，其余档位填空），并保持列名与实时采集一致。
   - 将 aggTrades 转换为 trade.parquet（字段与实时采集一致）。
   - 其他数据按日落盘：metrics.parquet / book_depth.parquet / premium_index_1m.parquet / mark_price_1m.parquet
   - fundingRate 是月文件，脚本会按天拆分写入 funding_rate.parquet
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Callable, Iterable
import xml.etree.ElementTree as ET

import pandas as pd
import requests


S3_LIST_BASE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DL_BASE = "https://data.binance.vision/"


# 当前文件: Quant_Unified/服务/数据采集/下载币安官方历史数据.py
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]  # Quant_Unified


@dataclass(frozen=True)
class DailyTask:
    dataset: str
    symbol: str
    key: str
    day: str  # YYYY-MM-DD


@dataclass(frozen=True)
class MonthlyTask:
    dataset: str
    symbol: str
    key: str
    month: str  # YYYY-MM


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _parse_month(s: str) -> date:
    return datetime.strptime(s + "-01", "%Y-%m-%d").date()


def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def _atomic_write_parquet(df: pd.DataFrame, out_file: Path) -> None:
    _ensure_parent(out_file)
    tmp = out_file.with_suffix(out_file.suffix + f".tmp_{time.time_ns()}")
    df.to_parquet(tmp, engine="pyarrow", compression="snappy", index=False)
    tmp.replace(out_file)


def _s3_list_keys(prefix: str) -> list[str]:
    """
    使用 S3 ListObjects（XML）列出 prefix 下所有 keys（自动翻页）。
    """
    ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    keys: list[str] = []
    marker: str | None = None

    while True:
        params = {"prefix": prefix, "max-keys": "1000"}
        if marker:
            params["marker"] = marker

        r = requests.get(S3_LIST_BASE, params=params, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.text)

        for c in root.findall("s3:Contents", ns):
            k = c.find("s3:Key", ns)
            if k is None or not k.text:
                continue
            keys.append(k.text)

        is_trunc = root.findtext("s3:IsTruncated", default="false", namespaces=ns).lower() == "true"
        if not is_trunc:
            break

        marker = root.findtext("s3:NextMarker", default="", namespaces=ns) or (keys[-1] if keys else None)
        if not marker:
            break

    return keys


def _download_to_cache(key: str, cache_root: Path, overwrite: bool) -> Path:
    """
    下载 key 对应的 zip 到本地 cache，并返回路径。
    """
    dest = cache_root / key
    if dest.exists() and not overwrite:
        return dest

    _ensure_parent(dest)
    url = DL_BASE + key
    last_err: Exception | None = None
    for attempt in range(1, 6):
        tmp = dest.with_suffix(dest.suffix + f".tmp_{time.time_ns()}")
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
            tmp.replace(dest)
            return dest
        except Exception as e:
            last_err = e
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            # 简单指数退避
            time.sleep(min(2**attempt, 20))

    assert last_err is not None
    raise last_err
    return dest


def _read_single_csv_from_zip(zip_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise RuntimeError(f"zip 内无 csv: {zip_path}")
        if len(names) != 1:
            # 绝大多数文件只有 1 个 csv，若异常也优先取第一个
            names = [names[0]]
        with z.open(names[0]) as f:
            return pd.read_csv(f)


def _convert_agg_trades(zip_path: Path, symbol: str, out_day_dir: Path, overwrite: bool) -> None:
    out_file = out_day_dir / "trade.parquet"
    if out_file.exists() and not overwrite:
        return
    df = _read_single_csv_from_zip(zip_path)
    # columns: agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker
    df = df.rename(
        columns={
            "price": "price",
            "quantity": "qty",
            "transact_time": "exchange_time",
            "is_buyer_maker": "is_buyer_maker",
        }
    )
    df["exchange_time"] = pd.to_numeric(df["exchange_time"], errors="coerce").astype("int64")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce")
    df["is_buyer_maker"] = df["is_buyer_maker"].astype(str).str.lower().isin(["true", "1", "t", "yes"])
    df["timestamp"] = df["exchange_time"] / 1000.0
    df["symbol"] = symbol
    out = df[["timestamp", "exchange_time", "symbol", "price", "qty", "is_buyer_maker"]].dropna(
        subset=["exchange_time", "price", "qty"]
    )
    _atomic_write_parquet(out, out_file)


def _convert_book_ticker(zip_path: Path, symbol: str, out_day_dir: Path, depth_levels: int, overwrite: bool) -> None:
    out_file = out_day_dir / "depth.parquet"
    if out_file.exists() and not overwrite:
        return
    df = _read_single_csv_from_zip(zip_path)
    # columns: update_id,best_bid_price,best_bid_qty,best_ask_price,best_ask_qty,transaction_time,event_time
    df["exchange_time"] = pd.to_numeric(df["transaction_time"], errors="coerce").astype("int64")
    bid_p = pd.to_numeric(df["best_bid_price"], errors="coerce")
    bid_q = pd.to_numeric(df["best_bid_qty"], errors="coerce")
    ask_p = pd.to_numeric(df["best_ask_price"], errors="coerce")
    ask_q = pd.to_numeric(df["best_ask_qty"], errors="coerce")

    # 0E-8 / 0 属于缺失值，避免污染价差/中间价
    ask_p = ask_p.mask(ask_p <= 0)
    bid_p = bid_p.mask(bid_p <= 0)
    ask_q = ask_q.mask(ask_q < 0)
    bid_q = bid_q.mask(bid_q < 0)

    base = pd.DataFrame(
        {
            "timestamp": df["exchange_time"] / 1000.0,
            "exchange_time": df["exchange_time"],
            "symbol": symbol,
            "bid1_p": bid_p,
            "bid1_q": bid_q,
            "ask1_p": ask_p,
            "ask1_q": ask_q,
        }
    )

    cols = ["timestamp", "exchange_time", "symbol"]
    for i in range(1, int(depth_levels) + 1):
        cols.extend([f"bid{i}_p", f"bid{i}_q"])
    for i in range(1, int(depth_levels) + 1):
        cols.extend([f"ask{i}_p", f"ask{i}_q"])
    out = base.reindex(columns=cols).dropna(subset=["exchange_time"])
    _atomic_write_parquet(out, out_file)


def _convert_metrics(zip_path: Path, symbol: str, out_day_dir: Path, overwrite: bool) -> None:
    out_file = out_day_dir / "metrics.parquet"
    if out_file.exists() and not overwrite:
        return
    df = _read_single_csv_from_zip(zip_path)
    df["symbol"] = symbol
    _atomic_write_parquet(df, out_file)


def _convert_book_depth(zip_path: Path, symbol: str, out_day_dir: Path, overwrite: bool) -> None:
    out_file = out_day_dir / "book_depth.parquet"
    if out_file.exists() and not overwrite:
        return
    df = _read_single_csv_from_zip(zip_path)
    df["symbol"] = symbol
    _atomic_write_parquet(df, out_file)


def _convert_kline_like(zip_path: Path, symbol: str, out_file: Path, overwrite: bool) -> None:
    if out_file.exists() and not overwrite:
        return
    df = _read_single_csv_from_zip(zip_path)
    df["symbol"] = symbol
    _atomic_write_parquet(df, out_file)


def _convert_funding_rate_monthly(zip_path: Path, symbol: str, out_root: Path, overwrite: bool) -> None:
    df = _read_single_csv_from_zip(zip_path)
    if df.empty:
        return
    df["calc_time"] = pd.to_numeric(df["calc_time"], errors="coerce").astype("int64")
    df["symbol"] = symbol
    # 按天拆分
    dt = pd.to_datetime(df["calc_time"], unit="ms", utc=True)
    df["date"] = dt.dt.strftime("%Y-%m-%d")
    for d, sub in df.groupby("date", sort=True):
        out_file = out_root / symbol / d / "funding_rate.parquet"
        if out_file.exists() and not overwrite:
            continue
        _atomic_write_parquet(sub.drop(columns=["date"]), out_file)


def _extract_day(key: str, pattern: re.Pattern) -> str | None:
    m = pattern.search(key)
    return m.group(1) if m else None


def _extract_month(key: str, pattern: re.Pattern) -> str | None:
    m = pattern.search(key)
    return m.group(1) if m else None


def _split_csv(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="下载币安官方历史数据（Binance Vision）并转换为本地 parquet")
    p.add_argument("--symbols", type=str, default="", help="逗号分隔交易对，例如 ETHUSDC,BTCUSDC；留空则使用默认")
    p.add_argument(
        "--out-root",
        type=str,
        default=str(PROJECT_ROOT / "data" / "行情数据_整理"),
        help="输出目录（会按 symbol/date 组织）",
    )
    p.add_argument(
        "--cache-root",
        type=str,
        default=str(PROJECT_ROOT / "data" / "币安官方历史数据_raw"),
        help="原始 zip 缓存目录（可断点续跑）",
    )
    p.add_argument(
        "--start-date",
        type=str,
        default="",
        help="起始日期 YYYY-MM-DD（可选，留空表示不限制）",
    )
    p.add_argument(
        "--end-date",
        type=str,
        default="",
        help="结束日期 YYYY-MM-DD（可选，留空表示不限制）",
    )
    p.add_argument(
        "--datasets",
        type=str,
        default="bookTicker,aggTrades,metrics,bookDepth,fundingRate,premiumIndexKlines,markPriceKlines",
        help="要下载的数据集，逗号分隔",
    )
    p.add_argument("--kline-interval", type=str, default="1m", help="K线类数据的周期（默认 1m）")
    p.add_argument("--depth-levels", type=int, default=50, help="转换 depth.parquet 的档位数（默认 50）")
    p.add_argument("--max-workers", type=int, default=8, help="并发下载/处理线程数")
    p.add_argument("--overwrite", action="store_true", help="覆盖已存在的输出 parquet")
    p.add_argument("--overwrite-cache", action="store_true", help="覆盖已存在的缓存 zip")
    p.add_argument("--dry-run", action="store_true", help="只打印计划，不下载/不写文件")
    return p


def _default_symbols() -> list[str]:
    # 与实时采集默认一致（可按需加戏币）
    return ["BTCUSDC", "ETHUSDC", "SOLUSDC", "XRPUSDC", "BNBUSDC"]


def _iter_daily_tasks(
    dataset: str,
    symbol: str,
    kline_interval: str,
    start: date | None,
    end: date | None,
) -> Iterable[DailyTask]:
    if dataset in {"aggTrades", "bookTicker", "metrics", "bookDepth"}:
        prefix = f"data/futures/um/daily/{dataset}/{symbol}/"
        date_pat = re.compile(rf"{re.escape(symbol)}-{re.escape(dataset)}-(\d{{4}}-\d{{2}}-\d{{2}})\.zip$")
    elif dataset in {"premiumIndexKlines", "markPriceKlines"}:
        prefix = f"data/futures/um/daily/{dataset}/{symbol}/{kline_interval}/"
        date_pat = re.compile(rf"{re.escape(symbol)}-{re.escape(kline_interval)}-(\d{{4}}-\d{{2}}-\d{{2}})\.zip$")
    else:
        return

    for key in _s3_list_keys(prefix):
        if not key.endswith(".zip") or key.endswith(".zip.CHECKSUM"):
            continue
        day = _extract_day(key, date_pat)
        if not day:
            continue
        d = _parse_date(day)
        if start and d < start:
            continue
        if end and d > end:
            continue
        yield DailyTask(dataset=dataset, symbol=symbol, key=key, day=day)


def _iter_monthly_tasks(dataset: str, symbol: str, start: date | None, end: date | None) -> Iterable[MonthlyTask]:
    if dataset != "fundingRate":
        return
    prefix = f"data/futures/um/monthly/fundingRate/{symbol}/"
    month_pat = re.compile(rf"{re.escape(symbol)}-fundingRate-(\d{{4}}-\d{{2}})\.zip$")
    for key in _s3_list_keys(prefix):
        if not key.endswith(".zip") or key.endswith(".zip.CHECKSUM"):
            continue
        month = _extract_month(key, month_pat)
        if not month:
            continue
        m_date = _parse_month(month)
        if start and m_date < start.replace(day=1):
            continue
        if end and m_date > end.replace(day=1):
            continue
        yield MonthlyTask(dataset=dataset, symbol=symbol, key=key, month=month)


def _process_daily(
    task: DailyTask,
    *,
    out_root: Path,
    cache_root: Path,
    depth_levels: int,
    kline_interval: str,
    overwrite: bool,
    overwrite_cache: bool,
    dry_run: bool,
) -> str:
    out_day_dir = out_root / task.symbol / task.day
    if dry_run:
        return f"[DRY] {task.dataset} {task.symbol} {task.day}"

    # 若输出已存在，优先跳过（避免重复下载/解压）
    if not overwrite:
        if task.dataset == "aggTrades" and (out_day_dir / "trade.parquet").exists():
            return f"[SKIP] aggTrades {task.symbol} {task.day}"
        if task.dataset == "bookTicker" and (out_day_dir / "depth.parquet").exists():
            return f"[SKIP] bookTicker {task.symbol} {task.day}"
        if task.dataset == "metrics" and (out_day_dir / "metrics.parquet").exists():
            return f"[SKIP] metrics {task.symbol} {task.day}"
        if task.dataset == "bookDepth" and (out_day_dir / "book_depth.parquet").exists():
            return f"[SKIP] bookDepth {task.symbol} {task.day}"
        if task.dataset == "premiumIndexKlines" and (out_day_dir / f"premium_index_{kline_interval}.parquet").exists():
            return f"[SKIP] premiumIndexKlines {task.symbol} {task.day}"
        if task.dataset == "markPriceKlines" and (out_day_dir / f"mark_price_{kline_interval}.parquet").exists():
            return f"[SKIP] markPriceKlines {task.symbol} {task.day}"

    zip_path = _download_to_cache(task.key, cache_root=cache_root, overwrite=overwrite_cache)

    if task.dataset == "aggTrades":
        _convert_agg_trades(zip_path, task.symbol, out_day_dir, overwrite=overwrite)
    elif task.dataset == "bookTicker":
        _convert_book_ticker(zip_path, task.symbol, out_day_dir, depth_levels=depth_levels, overwrite=overwrite)
    elif task.dataset == "metrics":
        _convert_metrics(zip_path, task.symbol, out_day_dir, overwrite=overwrite)
    elif task.dataset == "bookDepth":
        _convert_book_depth(zip_path, task.symbol, out_day_dir, overwrite=overwrite)
    elif task.dataset == "premiumIndexKlines":
        _convert_kline_like(
            zip_path,
            task.symbol,
            out_day_dir / f"premium_index_{kline_interval}.parquet",
            overwrite=overwrite,
        )
    elif task.dataset == "markPriceKlines":
        _convert_kline_like(
            zip_path,
            task.symbol,
            out_day_dir / f"mark_price_{kline_interval}.parquet",
            overwrite=overwrite,
        )
    else:
        return f"[SKIP] {task.dataset} {task.symbol} {task.day}"
    return f"[OK] {task.dataset} {task.symbol} {task.day}"


def _process_monthly(
    task: MonthlyTask,
    *,
    out_root: Path,
    cache_root: Path,
    overwrite: bool,
    overwrite_cache: bool,
    dry_run: bool,
) -> str:
    if dry_run:
        return f"[DRY] {task.dataset} {task.symbol} {task.month}"
    zip_path = _download_to_cache(task.key, cache_root=cache_root, overwrite=overwrite_cache)
    if task.dataset == "fundingRate":
        _convert_funding_rate_monthly(zip_path, task.symbol, out_root, overwrite=overwrite)
        return f"[OK] fundingRate {task.symbol} {task.month}"
    return f"[SKIP] {task.dataset} {task.symbol} {task.month}"


def main() -> int:
    args = build_arg_parser().parse_args()

    symbols = _split_csv(args.symbols) or _default_symbols()
    out_root = Path(args.out_root)
    cache_root = Path(args.cache_root)

    start = _parse_date(args.start_date) if args.start_date else None
    end = _parse_date(args.end_date) if args.end_date else None
    if start and end and start > end:
        raise SystemExit("start-date must be <= end-date")

    datasets = _split_csv(args.datasets)
    kline_interval = str(args.kline_interval).strip() or "1m"

    daily_tasks: list[DailyTask] = []
    monthly_tasks: list[MonthlyTask] = []

    for sym in symbols:
        for ds in datasets:
            if ds in {"fundingRate"}:
                monthly_tasks.extend(list(_iter_monthly_tasks(ds, sym, start=start, end=end)))
            else:
                daily_tasks.extend(
                    list(_iter_daily_tasks(ds, sym, kline_interval=kline_interval, start=start, end=end))
                )

    print(f"Symbols: {symbols}")
    print(f"Datasets: {datasets}")
    print(f"Daily tasks: {len(daily_tasks):,} | Monthly tasks: {len(monthly_tasks):,}")
    print(f"Out: {out_root}")
    print(f"Cache: {cache_root}")
    if args.dry_run:
        for t in (daily_tasks[:10] + [DailyTask("...", "...", "...", "...")] + daily_tasks[-10:]) if daily_tasks else []:
            print(t)
        return 0

    # 并发处理日文件
    ok = 0
    fail = 0
    with ThreadPoolExecutor(max_workers=int(args.max_workers)) as ex:
        futures = []
        for t in daily_tasks:
            futures.append(
                ex.submit(
                    _process_daily,
                    t,
                    out_root=out_root,
                    cache_root=cache_root,
                    depth_levels=int(args.depth_levels),
                    kline_interval=kline_interval,
                    overwrite=bool(args.overwrite),
                    overwrite_cache=bool(args.overwrite_cache),
                    dry_run=False,
                )
            )
        for t in monthly_tasks:
            futures.append(
                ex.submit(
                    _process_monthly,
                    t,
                    out_root=out_root,
                    cache_root=cache_root,
                    overwrite=bool(args.overwrite),
                    overwrite_cache=bool(args.overwrite_cache),
                    dry_run=False,
                )
            )

        for fut in as_completed(futures):
            try:
                msg = fut.result()
                ok += 1
                # 控制输出量：只打印少量进度
                if ok <= 20 or ok % 500 == 0:
                    print(msg)
            except Exception as e:
                fail += 1
                print(f"[FAIL] {e}")

    print(f"Done. ok={ok:,} fail={fail:,}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
