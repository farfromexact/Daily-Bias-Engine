"""Incrementally update local iFinD market and option snapshots."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from daily_bias_engine.options.data import IFindOptionClient, OptionMarketDataStore, load_normalized_chain
from daily_bias_engine.pipeline import default_history_range, latest_raw_data_date, list_snapshots, load_snapshot_raw
from scripts.fetch_ifind_snapshot import update_ifind_snapshot

PRODUCT_GROUPS = ("SSE50", "CSI300", "CSI1000")


def main() -> None:
    parser = argparse.ArgumentParser(description="Incrementally update iFinD market and option snapshots.")
    parser.add_argument("--end", default=None, help="Target end date, YYYY-MM-DD. Defaults to latest weekday.")
    parser.add_argument("--years", type=int, default=3, help="Trailing years retained in market snapshots.")
    parser.add_argument("--snapshot-root", default=str(PROJECT_ROOT / "data" / "snapshots"))
    parser.add_argument("--options-root", default=str(PROJECT_ROOT / "data" / "options_ifind"))
    parser.add_argument("--keep-ifind-snapshots", type=int, default=2, help="Number of iFinD market snapshots to keep.")
    parser.add_argument("--full-refresh", action="store_true", help="Force a full market snapshot refresh.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned ranges without calling iFinD or writing data.")
    args = parser.parse_args()

    snapshot_root = Path(args.snapshot_root)
    options_root = Path(args.options_root)
    _, target_end = default_history_range(years=args.years, end_date=args.end)

    if args.dry_run:
        _print_dry_run(snapshot_root, options_root, args.years, target_end, args.full_refresh)
        return

    market_snapshot = update_ifind_snapshot(
        snapshot_root=snapshot_root,
        end=target_end,
        years=args.years,
        full_refresh=args.full_refresh,
    )
    option_paths = update_ifind_options(options_root=options_root, end_date=target_end)
    removed = prune_ifind_snapshots(snapshot_root, keep=args.keep_ifind_snapshots)

    if market_snapshot is None and not option_paths and not removed:
        print("No iFinD data updates were needed.", flush=True)
    else:
        if market_snapshot is not None:
            print(f"market_snapshot={market_snapshot}", flush=True)
        print(f"option_files_updated={len(option_paths)}", flush=True)
        print(f"ifind_snapshots_removed={len(removed)}", flush=True)


def update_ifind_options(
    options_root: Path,
    end_date: str,
    products: tuple[str, ...] = PRODUCT_GROUPS,
) -> list[Path]:
    product_latest = {product: latest_option_date(options_root, product) for product in products}
    end_ts = pd.Timestamp(end_date).normalize()
    starts = [date + pd.Timedelta(days=1) for date in product_latest.values() if date is not None and date < end_ts]
    starts.extend(pd.Timestamp("2026-01-01") for date in product_latest.values() if date is None)
    if not starts:
        print(f"options up to date through {end_ts.date()}.", flush=True)
        return []

    calendar_start = str(min(starts).date())
    calendar_end = str(end_ts.date())
    client = IFindOptionClient()
    store = OptionMarketDataStore(options_root)
    updated: list[Path] = []
    failures: list[tuple[str, str, str]] = []
    try:
        trade_dates = [pd.Timestamp(item).strftime("%Y-%m-%d") for item in client.get_trading_calendar(calendar_start, calendar_end)]
        for trade_date in trade_dates:
            trade_ts = pd.Timestamp(trade_date).normalize()
            for product in products:
                latest = product_latest[product]
                if latest is not None and trade_ts <= latest:
                    continue
                existing_path = _normalized_chain_path(store.root, product, trade_date)
                if existing_path.exists():
                    print(f"SKIP {trade_date} {product} path={existing_path}", flush=True)
                    continue
                try:
                    chain = load_normalized_chain(client, product, trade_date)
                    path = store.write_normalized_chain(chain)
                    updated.append(path)
                    print(f"OK {trade_date} {product} rows={len(chain)} path={path}", flush=True)
                except Exception as exc:
                    failures.append((trade_date, product, str(exc)))
                    print(f"FAIL {trade_date} {product}: {exc}", file=sys.stderr, flush=True)
    finally:
        client.close()

    if failures:
        for trade_date, product, message in failures:
            print(f"- {trade_date} {product}: {message}", file=sys.stderr, flush=True)
        raise SystemExit(1)
    return updated


def latest_option_date(options_root: Path, product: str) -> pd.Timestamp | None:
    root = options_root / "normalized_chain" / f"product_group={product.upper()}"
    if not root.exists():
        return None
    dates = []
    for path in root.glob("trade_date=*/data.parquet"):
        date_part = path.parent.name.split("=", 1)[-1]
        dates.append(pd.Timestamp(date_part).normalize())
    return max(dates) if dates else None


def prune_ifind_snapshots(snapshot_root: Path, keep: int = 2) -> list[Path]:
    if keep < 1:
        raise ValueError("keep must be at least 1.")
    snapshots = [item for item in list_snapshots(snapshot_root) if item.source == "ifind"]
    removed: list[Path] = []
    for snapshot in snapshots[keep:]:
        shutil.rmtree(snapshot.path)
        removed.append(snapshot.path)
        print(f"removed_old_snapshot={snapshot.path}", flush=True)
    return removed


def _print_dry_run(
    snapshot_root: Path,
    options_root: Path,
    years: int,
    target_end: str,
    full_refresh: bool,
) -> None:
    default_start, _ = default_history_range(years=years, end_date=target_end)
    if full_refresh:
        print(f"market full refresh: {default_start} to {target_end}")
    else:
        snapshots = [item for item in list_snapshots(snapshot_root) if item.source == "ifind"]
        if not snapshots:
            print(f"market initialize: {default_start} to {target_end}")
        else:
            raw = load_snapshot_raw(snapshots[0].path)
            latest = latest_raw_data_date(raw)
            if latest is None:
                print(f"market rebuild: {default_start} to {target_end}")
            elif pd.Timestamp(target_end).normalize() <= latest:
                print(f"market up to date: {latest.date()} >= {target_end}")
            else:
                start = latest + pd.Timedelta(days=1)
                print(f"market incremental: {start.date()} to {target_end} base={snapshots[0].path}")

    for product in PRODUCT_GROUPS:
        latest = latest_option_date(options_root, product)
        if latest is None:
            print(f"options {product}: initialize from 2026-01-01 to {target_end}")
        elif pd.Timestamp(target_end).normalize() <= latest:
            print(f"options {product}: up to date through {latest.date()}")
        else:
            start = latest + pd.Timedelta(days=1)
            print(f"options {product}: incremental {start.date()} to {target_end}")


def _normalized_chain_path(root: Path, product_group: str, trade_date: str) -> Path:
    date_part = pd.Timestamp(trade_date).strftime("%Y-%m-%d")
    return root / "normalized_chain" / f"product_group={product_group.upper()}" / f"trade_date={date_part}" / "data.parquet"


if __name__ == "__main__":
    main()
