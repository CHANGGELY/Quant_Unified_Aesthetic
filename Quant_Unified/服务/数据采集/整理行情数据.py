import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Literal, cast

import pandas as pd


# =================================================================
# ⚙️ 快速配置区 (可以直接在这里修改参数后点运行)
# =================================================================

# 1. 整理哪些币种的数据？(例如 "BTCUSDC,ETHUSDC"，留空则整理所有币种)
默认_SYMBOLS = ""

# 2. 整理哪个日期的数据？(例如 "2023-12-21"，留空则整理所有历史日期)
默认_DATE = ""

# 3. 整理时是否自动补全成交数据？
# 如果设置为 True，当程序发现深度数据(Depth)有空缺时，会自动调用《补全历史成交.py》去补全对应的成交数据(Trade)
默认_AUTO_FILL_TRADE_FROM_DEPTH_GAPS = True

# 4. 判定为“空缺”的阈值 (单位: 毫秒)
# 默认 60,000 毫秒 = 1 分钟。如果两行数据之间的时间差超过这个值，就认为中间有断档。
默认_FILL_DEPTH_GAP_MIN_MS = 60_000

# 5. 路径配置 (通常不需要修改)
默认_INPUT = str(Path(__file__).resolve().parents[2] / "data" / "行情数据")
默认_OUTPUT = str(Path(__file__).resolve().parents[2] / "data" / "行情数据_整理")
# 默认备份目录：整理完成后，将原始碎片文件移动到这里 (相当于归档)，而不是直接删除
默认_BACKUP_DIR = str(Path(__file__).resolve().parents[2] / "data" / "行情数据_备份")

# 6. 其他高级设置
默认_DTYPE = ""              # 只整理特定类型 (depth 或 trade)，留空则全部整理
默认_OVERWRITE = True       # 如果输出文件已存在，是否覆盖？
默认_MOVE_TO_BACKUP = True  # 【推荐】整理后将碎片文件移动到备份目录 (避免下次重复整理，且比删除更安全)
默认_DELETE_SOURCE = False   # (已弃用，建议用 MOVE_TO_BACKUP) 整理完后是否删除原始碎片文件？
默认_DELETE_TODAY = False    # 是否移动/删除今天的碎片文件？(今天的还在采集，建议不移动)
默认_CHECK_GAP = True        # 是否检查并生成空缺报告？
默认_GAP_MS_DEPTH = 2000     # 深度数据超过 2 秒没数据就算小缺口
默认_GAP_MS_TRADE = 10000    # 成交数据超过 10 秒没数据就算小缺口
默认_GAP_SAMPLES = 50        # 每个文件最多记录多少个缺口样本
默认_FILL_MAX_GAPS_PER_SYMBOL_DAY = 100 # 每个币种每天最多补全多少个大缺口
默认_FILL_MAX_WINDOW_MS = 24 * 60 * 60 * 1000  # 单次补全最大跨度 (默认 24 小时)

# =================================================================


数据类型 = Literal["depth", "trade"]


@dataclass(frozen=True)
class 缺口:
    symbol: str
    dtype: 数据类型
    date: str
    prev_exchange_time: int
    next_exchange_time: int
    gap_ms: int


def _iter_input_files(input_root: Path, symbols: list[str] | None) -> Iterable[Path]:
    if not input_root.exists():
        return
    for symbol_dir in sorted([p for p in input_root.iterdir() if p.is_dir()]):
        symbol = symbol_dir.name
        if symbols and symbol not in symbols:
            continue
        for date_dir in sorted([p for p in symbol_dir.iterdir() if p.is_dir()]):
            for parquet_file in sorted(date_dir.glob("*.parquet")):
                yield parquet_file


def _parse_file_meta(p: Path) -> tuple[str, str, 数据类型] | None:
    try:
        symbol = p.parents[1].name
        date = p.parent.name
        name = p.name
        if name.startswith("depth_"):
            return symbol, date, "depth"
        if name.startswith("trade_") or name.startswith("trade_hist_"):
            return symbol, date, "trade"
        return None
    except Exception:
        return None


def _read_parquet_safe(file_path: Path) -> pd.DataFrame | None:
    try:
        return pd.read_parquet(file_path)
    except Exception:
        return None


def _dedupe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if "timestamp" in df.columns:
        dedupe_cols = [c for c in df.columns if c != "timestamp"]
        if dedupe_cols:
            df = df.sort_values(["exchange_time", "timestamp"], kind="stable").drop_duplicates(
                subset=dedupe_cols, keep="first"
            )
            return df
    return df.drop_duplicates(keep="first")


def _normalize_types(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if "exchange_time" in df.columns:
        df["exchange_time"] = pd.to_numeric(df["exchange_time"], errors="coerce").astype("Int64")
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    return df.dropna(subset=[c for c in ["exchange_time", "symbol"] if c in df.columns]).copy()


def _check_gaps(
    df: pd.DataFrame,
    symbol: str,
    dtype: 数据类型,
    date: str,
    gap_threshold_ms: int,
    max_samples: int,
) -> tuple[dict, list[缺口]]:
    if df.empty or "exchange_time" not in df.columns:
        return {"gap_threshold_ms": gap_threshold_ms, "gap_count": 0, "max_gap_ms": 0}, []

    s = df["exchange_time"].astype("int64", errors="ignore")
    s = s.sort_values(kind="stable").reset_index(drop=True)
    diff = s.diff().fillna(0).astype("int64")
    gap_mask = diff > int(gap_threshold_ms)
    gap_count = int(gap_mask.sum())
    max_gap = int(diff.max()) if len(diff) else 0

    gaps: list[缺口] = []
    if gap_count:
        idxs = gap_mask[gap_mask].index.tolist()[:max_samples]
        for i in idxs:
            prev_t = int(s.iloc[i - 1])
            next_t = int(s.iloc[i])
            gaps.append(
                缺口(
                    symbol=symbol,
                    dtype=dtype,
                    date=date,
                    prev_exchange_time=prev_t,
                    next_exchange_time=next_t,
                    gap_ms=int(next_t - prev_t),
                )
            )

    summary = {
        "gap_threshold_ms": int(gap_threshold_ms),
        "gap_count": gap_count,
        "max_gap_ms": max_gap,
    }
    return summary, gaps


def _write_output(df: pd.DataFrame, out_file: Path, overwrite: bool) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if out_file.exists() and not overwrite:
        return
    df.to_parquet(out_file, engine="pyarrow", compression="snappy", index=False)


def _split_csv(s: str) -> list[str] | None:
    items = [x.strip() for x in str(s or "").split(",") if x.strip()]
    return items or None


def _iter_input_files_with_filters(
    input_root: Path,
    symbols: list[str] | None,
    date_filter: str | None,
    dtype_filter: 数据类型 | None,
) -> Iterable[Path]:
    for p in _iter_input_files(input_root, symbols):
        meta = _parse_file_meta(p)
        if not meta:
            continue
        _, date, dtype = meta
        if date_filter and date != date_filter:
            continue
        if dtype_filter and dtype != dtype_filter:
            continue
        yield p


def _build_groups(
    input_root: Path,
    symbols: list[str] | None,
    date_filter: str | None,
    dtype_filter: 数据类型 | None,
) -> dict[tuple[str, str, 数据类型], list[Path]]:
    groups: dict[tuple[str, str, 数据类型], list[Path]] = {}
    for f in _iter_input_files_with_filters(input_root, symbols, date_filter, dtype_filter):
        meta = _parse_file_meta(f)
        if not meta:
            continue
        symbol, date, dtype = meta
        groups.setdefault((symbol, date, dtype), []).append(f)
    return groups


def _run_fill_trade(symbol: str, start_ms: int, end_ms: int) -> int:
    if start_ms >= end_ms:
        return 0
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "补全历史成交.py"),
        "--symbol",
        str(symbol),
        "--start-ms",
        str(int(start_ms)),
        "--end-ms",
        str(int(end_ms)),
    ]
    p = subprocess.run(cmd, check=False)
    return int(p.returncode or 0)


def _plan_fill_from_depth_gaps(
    gap_samples: list[dict],
    min_gap_ms: int,
    max_gaps_per_symbol_day: int,
    max_window_ms: int,
) -> list[dict]:
    candidates: dict[tuple[str, str], list[dict]] = {}
    for g in gap_samples or []:
        try:
            if g.get("dtype") != "depth":
                continue
            if int(g.get("gap_ms", 0)) < int(min_gap_ms):
                continue
            symbol = str(g.get("symbol") or "")
            date = str(g.get("date") or "")
            if not symbol or not date:
                continue
            candidates.setdefault((symbol, date), []).append(g)
        except Exception:
            continue

    plans: list[dict] = []
    for (symbol, date), gaps in sorted(candidates.items()):
        gaps_sorted = sorted(gaps, key=lambda x: int(x.get("gap_ms", 0)), reverse=True)
        for g in gaps_sorted[: int(max_gaps_per_symbol_day)]:
            try:
                start_ms = int(g["prev_exchange_time"]) + 1
                end_ms = int(g["next_exchange_time"]) - 1
                if end_ms - start_ms > int(max_window_ms):
                    end_ms = start_ms + int(max_window_ms)
                if start_ms >= end_ms:
                    continue
                plans.append(
                    {
                        "symbol": symbol,
                        "date": date,
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "gap_ms": int(g.get("gap_ms", 0)),
                    }
                )
            except Exception:
                continue
    return plans


def _organize_groups(
    groups: dict[tuple[str, str, 数据类型], list[Path]],
    output_root: Path,
    overwrite: bool,
    delete_source: bool,
    move_to_backup: bool,
    backup_root: Path,
    delete_today: bool,
    check_gap: bool,
    gap_ms_depth: int,
    gap_ms_trade: int,
    gap_samples_limit: int,
    report_groups_by_key: dict[tuple[str, str, 数据类型], dict],
    gap_summaries_by_key: dict[tuple[str, str, 数据类型], dict],
    gap_samples_by_key: dict[tuple[str, str, 数据类型], list[dict]],
) -> None:
    today_str = datetime.now().strftime("%Y-%m-%d")

    for (symbol, date, dtype), files in sorted(groups.items()):
        dfs: list[pd.DataFrame] = []
        bad_files: list[str] = []

        out_path = output_root / symbol / date / f"{dtype}.parquet"

        # 1. 尝试读取已存在的输出文件 (支持增量合并)
        if out_path.exists() and out_path.stat().st_size > 0:
            try:
                df_existing = pd.read_parquet(out_path)
                if not df_existing.empty:
                    dfs.append(df_existing)
            except Exception:
                pass  # 如果旧文件损坏，就忽略它，重新生成

        # 2. 读取新的碎片文件
        for p in sorted(files):
            df = _read_parquet_safe(p)
            if df is None:
                bad_files.append(str(p))
                continue
            dfs.append(df)

        if not dfs:
            report_groups_by_key[(symbol, date, dtype)] = {
                "symbol": symbol,
                "date": date,
                "dtype": dtype,
                "input_files": len(files),
                "bad_files": bad_files,
                "output": None,
                "rows": 0,
                "deleted_files": [],
                "moved_files": [],
                "delete_errors": [],
                "delete_skipped_reason": None,
            }
            gap_summaries_by_key.pop((symbol, date, dtype), None)
            gap_samples_by_key.pop((symbol, date, dtype), None)
            continue

        df_all = pd.concat(dfs, ignore_index=True)
        df_all = _normalize_types(df_all)
        
        # 即使最终为空，也可能需要写入空文件或记录
        if df_all.empty:
            _write_output(df_all, out_path, overwrite=overwrite)
            report_groups_by_key[(symbol, date, dtype)] = {
                "symbol": symbol,
                "date": date,
                "dtype": dtype,
                "input_files": len(files),
                "bad_files": bad_files,
                "output": str(out_path),
                "rows": 0,
                "deleted_files": [],
                "moved_files": [],
                "delete_errors": [],
                "delete_skipped_reason": None,
            }
            gap_summaries_by_key.pop((symbol, date, dtype), None)
            gap_samples_by_key.pop((symbol, date, dtype), None)
            continue

        sort_cols = [c for c in ["exchange_time", "timestamp"] if c in df_all.columns]
        if sort_cols:
            df_all = df_all.sort_values(sort_cols, kind="stable").reset_index(drop=True)
        df_all = _dedupe(df_all)

        _write_output(df_all, out_path, overwrite=True) # 总是 overwrite，因为我们已经合并了旧数据

        delete_skipped_reason = None
        deleted_files: list[str] = []
        moved_files: list[str] = []
        delete_errors: list[str] = []

        # 3. 处理源文件 (移动到备份 或 删除)
        if (move_to_backup or delete_source) and not bad_files:
            if date == today_str and not delete_today:
                delete_skipped_reason = "today"
            elif not out_path.exists():
                delete_skipped_reason = "no_output"
            else:
                for p in sorted(files):
                    try:
                        if move_to_backup:
                            # 移动逻辑
                            # 目标路径: backup_root / symbol / date / filename
                            backup_path = backup_root / symbol / date / p.name
                            backup_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(p), str(backup_path))
                            moved_files.append(str(p))
                        elif delete_source:
                            # 删除逻辑
                            p.unlink(missing_ok=True)
                            deleted_files.append(str(p))
                    except Exception as e:
                        delete_errors.append(f"{p}: {e}")

        report_groups_by_key[(symbol, date, dtype)] = {
            "symbol": symbol,
            "date": date,
            "dtype": dtype,
            "input_files": len(files),
            "bad_files": bad_files,
            "output": str(out_path),
            "rows": int(len(df_all)),
            "deleted_files": deleted_files,
            "moved_files": moved_files,
            "delete_errors": delete_errors,
            "delete_skipped_reason": delete_skipped_reason,
        }

        if check_gap:
            threshold = int(gap_ms_depth) if dtype == "depth" else int(gap_ms_trade)
            summary, gaps = _check_gaps(
                df_all,
                symbol=symbol,
                dtype=dtype,
                date=date,
                gap_threshold_ms=int(threshold),
                max_samples=int(gap_samples_limit),
            )
            gap_summaries_by_key[(symbol, date, dtype)] = {
                "symbol": symbol,
                "date": date,
                "dtype": dtype,
                **summary,
            }
            gap_samples_by_key[(symbol, date, dtype)] = [g.__dict__ for g in gaps]
        else:
            gap_summaries_by_key.pop((symbol, date, dtype), None)
            gap_samples_by_key.pop((symbol, date, dtype), None)

        print(f"整理完成 {symbol} {date} {dtype}: 输入{len(files)}个文件 -> {out_path.name}, 行数={len(df_all)}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=默认_INPUT,
    )
    parser.add_argument(
        "--output",
        default=默认_OUTPUT,
    )
    parser.add_argument(
        "--backup-dir",
        default=默认_BACKUP_DIR,
        help="整理后碎片文件的备份目录",
    )
    parser.add_argument("--symbols", default=默认_SYMBOLS, help="逗号分隔，如 BTCUSDC,ETHUSDC")
    parser.add_argument("--date", default=默认_DATE, help="YYYY-MM-DD，留空表示所有日期")
    parser.add_argument(
        "--dtype",
        default=默认_DTYPE,
        choices=["", "depth", "trade"],
    )
    parser.add_argument("--overwrite", action="store_true", default=bool(默认_OVERWRITE))
    parser.add_argument("--move-to-backup", action="store_true", default=bool(默认_MOVE_TO_BACKUP))
    parser.add_argument("--delete-source", action="store_true", default=bool(默认_DELETE_SOURCE))
    parser.add_argument("--delete-today", action="store_true", default=bool(默认_DELETE_TODAY))
    parser.add_argument("--check-gap", action="store_true", default=bool(默认_CHECK_GAP))
    parser.add_argument("--gap-ms-depth", type=int, default=int(默认_GAP_MS_DEPTH))
    parser.add_argument("--gap-ms-trade", type=int, default=int(默认_GAP_MS_TRADE))
    parser.add_argument("--gap-samples", type=int, default=int(默认_GAP_SAMPLES))

    parser.add_argument(
        "--auto-fill-trade-from-depth-gaps",
        action="store_true",
        default=bool(默认_AUTO_FILL_TRADE_FROM_DEPTH_GAPS),
    )
    parser.add_argument("--fill-depth-gap-min-ms", type=int, default=int(默认_FILL_DEPTH_GAP_MIN_MS))
    parser.add_argument(
        "--fill-max-gaps-per-symbol-day",
        type=int,
        default=int(默认_FILL_MAX_GAPS_PER_SYMBOL_DAY),
    )
    parser.add_argument("--fill-max-window-ms", type=int, default=int(默认_FILL_MAX_WINDOW_MS))
    args = parser.parse_args(argv)

    input_root = Path(args.input).expanduser().resolve()
    output_root = Path(args.output).expanduser().resolve()

    symbols = _split_csv(args.symbols)
    date_filter = (args.date or "").strip() or None
    dtype_filter = cast(数据类型 | None, ((args.dtype or "").strip() or None))

    check_gap_enabled = bool(args.check_gap or args.auto_fill_trade_from_depth_gaps)
    groups = _build_groups(input_root, symbols, date_filter, dtype_filter)

    if not groups:
        print(f"未找到可整理的数据目录: {input_root}")
        return 1

    report: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_root": str(input_root),
        "output_root": str(output_root),
        "backup_root": str(args.backup_dir),
        "move_to_backup": bool(args.move_to_backup),
        "delete_source": bool(args.delete_source),
        "delete_today": bool(args.delete_today),
        "check_gap": bool(check_gap_enabled),
        "auto_fill_trade_from_depth_gaps": bool(args.auto_fill_trade_from_depth_gaps),
        "groups": [],
        "gap_summaries": [],
        "gap_samples": [],
    }

    report_groups_by_key: dict[tuple[str, str, 数据类型], dict] = {}
    gap_summaries_by_key: dict[tuple[str, str, 数据类型], dict] = {}
    gap_samples_by_key: dict[tuple[str, str, 数据类型], list[dict]] = {}

    _organize_groups(
        groups,
        output_root=output_root,
        overwrite=bool(args.overwrite),
        delete_source=bool(args.delete_source),
        move_to_backup=bool(args.move_to_backup),
        backup_root=Path(args.backup_dir),
        delete_today=bool(args.delete_today),
        check_gap=bool(check_gap_enabled),
        gap_ms_depth=int(args.gap_ms_depth),
        gap_ms_trade=int(args.gap_ms_trade),
        gap_samples_limit=int(args.gap_samples),
        report_groups_by_key=report_groups_by_key,
        gap_summaries_by_key=gap_summaries_by_key,
        gap_samples_by_key=gap_samples_by_key,
    )

    if args.auto_fill_trade_from_depth_gaps:
        gap_samples_flat: list[dict] = []
        for v in gap_samples_by_key.values():
            gap_samples_flat.extend(v)

        plans = _plan_fill_from_depth_gaps(
            gap_samples_flat,
            min_gap_ms=int(args.fill_depth_gap_min_ms),
            max_gaps_per_symbol_day=int(args.fill_max_gaps_per_symbol_day),
            max_window_ms=int(args.fill_max_window_ms),
        )
        if plans:
            for plan in plans:
                symbol = str(plan["symbol"])
                date = str(plan["date"])
                start_ms = int(plan["start_ms"])
                end_ms = int(plan["end_ms"])
                print(f"触发补全 trade: {symbol} {date} {start_ms}->{end_ms}")
                _run_fill_trade(symbol=symbol, start_ms=start_ms, end_ms=end_ms)

            affected_pairs = sorted({(str(p["symbol"]), str(p["date"])) for p in plans})
            for symbol, date in affected_pairs:
                trade_groups = _build_groups(
                    input_root,
                    symbols=[symbol],
                    date_filter=date,
                    dtype_filter=cast(数据类型, "trade"),
                )
                if not trade_groups:
                    continue
                _organize_groups(
                    trade_groups,
                    output_root=output_root,
                    overwrite=bool(args.overwrite),
                    delete_source=bool(args.delete_source),
                    move_to_backup=bool(args.move_to_backup),
                    backup_root=Path(args.backup_dir),
                    delete_today=bool(args.delete_today),
                    check_gap=bool(check_gap_enabled),
                    gap_ms_depth=int(args.gap_ms_depth),
                    gap_ms_trade=int(args.gap_ms_trade),
                    gap_samples_limit=int(args.gap_samples),
                    report_groups_by_key=report_groups_by_key,
                    gap_summaries_by_key=gap_summaries_by_key,
                    gap_samples_by_key=gap_samples_by_key,
                )

    report["groups"] = [report_groups_by_key[k] for k in sorted(report_groups_by_key.keys())]
    report["gap_summaries"] = [gap_summaries_by_key[k] for k in sorted(gap_summaries_by_key.keys())]
    report["gap_samples"] = []
    for k in sorted(gap_samples_by_key.keys()):
        report["gap_samples"].extend(gap_samples_by_key[k])

    report_path = output_root / "整理报告.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已生成: {report_path}")

    # 生成 Markdown 报告
    md_lines = [
        "# 📊 行情数据整理报告",
        f"- **生成时间**: {report['generated_at']}",
        f"- **输入目录**: `{report['input_root']}`",
        f"- **输出目录**: `{report['output_root']}`",
        "",
        "## 1. 整理概览",
        "| 币种 | 日期 | 类型 | 文件数 | 输出行数 | 状态 |",
        "|---|---|---|---|---|---|",
    ]
    
    for g in report["groups"]:
        status = "✅ 成功" if g["rows"] > 0 else "⚠️ 空数据"
        if g["bad_files"]:
            status = "❌ 有损坏文件"
        md_lines.append(
            f"| {g['symbol']} | {g['date']} | {g['dtype']} | {g['input_files']} | {g['rows']:,} | {status} |"
        )
    
    md_lines.extend([
        "",
        "## 2. 连续性检查 (缺口报告)",
        "> **缺口定义**: 相邻两条数据的时间差超过阈值。",
        "",
        "| 币种 | 日期 | 类型 | 阈值(ms) | 缺口数量 | 最大断档(秒) |",
        "|---|---|---|---|---|---|",
    ])
    
    if not report["gap_summaries"]:
        md_lines.append("\n*(无缺口或未开启检查)*")
    else:
        for s in report["gap_summaries"]:
            max_gap_sec = round(s["max_gap_ms"] / 1000, 1)
            md_lines.append(
                f"| {s['symbol']} | {s['date']} | {s['dtype']} | {s['gap_threshold_ms']} | {s['gap_count']} | **{max_gap_sec}s** |"
            )

    md_lines.extend([
        "",
        "## 3. 详细缺口样本 (Top 50)",
        "| 币种 | 类型 | 时间 (前) | 时间 (后) | 断档时长 |",
        "|---|---|---|---|---|",
    ])

    if not report["gap_samples"]:
        md_lines.append("\n*(无详细样本)*")
    else:
        for gap in report["gap_samples"]:
            # 转换时间戳为可读格式
            try:
                t1 = datetime.fromtimestamp(gap["prev_exchange_time"] / 1000).strftime('%H:%M:%S.%f')[:-3]
                t2 = datetime.fromtimestamp(gap["next_exchange_time"] / 1000).strftime('%H:%M:%S.%f')[:-3]
            except Exception:
                t1 = str(gap["prev_exchange_time"])
                t2 = str(gap["next_exchange_time"])
                
            duration = round(gap["gap_ms"] / 1000, 3)
            md_lines.append(
                f"| {gap['symbol']} | {gap['dtype']} | {t1} | {t2} | {duration}s |"
            )

    md_path = output_root / "整理报告.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"可读报告已生成: {md_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
