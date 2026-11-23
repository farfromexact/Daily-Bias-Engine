"""Update Wind market and option snapshots locally after the close."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT_ROOT / "src"), str(PROJECT_ROOT)]

from daily_bias_engine.desk_api import archive_market_bias
from daily_bias_engine.options.data import OptionMarketDataStore, WindPyOptionClient
from daily_bias_engine.pipeline import default_history_range, list_snapshots
from scripts.fetch_wind_options_snapshot import fetch_option_dates
from scripts.fetch_wind_snapshot import update_wind_snapshot

PRODUCTS = ("SSE50", "CSI300", "CSI1000")


def latest_option_date(options_root: Path, product: str) -> pd.Timestamp | None:
    partitions = options_root / "normalized_chain" / f"product_group={product.upper()}"
    dates = (pd.Timestamp(p.parent.name.split("=")[1]) for p in partitions.glob("trade_date=*/data.parquet"))
    return max(dates, default=None)


def update_wind_options(options_root: Path, target: str, start: str | None = None, dry_run: bool = False) -> None:
    store = OptionMarketDataStore(options_root)
    client = WindPyOptionClient()
    end_day = pd.Timestamp(target)
    if start and pd.Timestamp(start) > end_day:
        raise ValueError("--options-start must be on or before --end")
    for product in PRODUCTS:
        latest = latest_option_date(options_root, product)
        if start:
            first = pd.Timestamp(start)
        elif latest is not None:
            first = latest + pd.Timedelta(days=1)
        else:
            first = None
        if first is not None and first > end_day:
            print(f"Wind options {product} up to date through {target}", flush=True)
            continue
        plan = f"{first.date()} to {target}" if first is not None else f"latest trading day through {target}"
        print(f"Wind options {product}: {plan}", flush=True)
        if dry_run:
            continue
        # On first use, seed the most recent session. Explicit ranges backfill older chains.
        calendar_start = first if first is not None else end_day - pd.Timedelta(days=30)
        dates = client.get_trading_calendar(calendar_start, end_day)
        if first is None:
            dates = dates[-1:]
            if dates.empty:
                raise ValueError(f"No Wind trading dates found through {target}")
        # Stop at the first failure. A retry resumes with the first unwritten date.
        fetch_option_dates(client, store, [product], dates.strftime("%Y-%m-%d"), fail_fast=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end", help="Target date (defaults to the latest completed weekday).")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--snapshot-root", type=Path, default=PROJECT_ROOT / "data" / "snapshots")
    parser.add_argument("--options-root", type=Path, default=PROJECT_ROOT / "data" / "options_wind")
    parser.add_argument("--options-start", help="Backfill missing Wind option partitions from this date.")
    parser.add_argument("--keep-wind-snapshots", type=int, default=2)
    parser.add_argument("--full-refresh", action="store_true", help="Rebuild market history.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned ranges without contacting Wind.")
    args = parser.parse_args()
    if args.keep_wind_snapshots < 1:
        parser.error("--keep-wind-snapshots must be positive")
    _, target = default_history_range(args.years, args.end)
    update_wind_snapshot(args.snapshot_root, end=target, years=args.years,
                         full_refresh=args.full_refresh, dry_run=args.dry_run)
    update_wind_options(args.options_root, target, args.options_start, args.dry_run)
    if not args.dry_run:
        for snapshot in list_snapshots(args.snapshot_root, source="wind")[args.keep_wind_snapshots:]:
            archive_market_bias(args.snapshot_root, snapshot)
            shutil.rmtree(snapshot.path)
            print(f"removed_old_wind_snapshot={snapshot.path}", flush=True)


if __name__ == "__main__":
    main()
