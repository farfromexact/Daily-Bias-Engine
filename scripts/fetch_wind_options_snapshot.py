"""Fetch Wind option data once and persist normalized local parquet chains."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from daily_bias_engine.options.data import OptionMarketDataStore, WindPyOptionClient, load_normalized_chain
from daily_bias_engine.pipeline import default_history_range


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Wind A-share index option chains and persist local parquet data.")
    parser.add_argument("--date", help="Single trade date, YYYY-MM-DD.")
    parser.add_argument("--start-date", help="First trade date for range fetch, YYYY-MM-DD.")
    parser.add_argument("--end-date", help="Last trade date for range fetch, YYYY-MM-DD. Defaults to today when --start-date is set.")
    parser.add_argument(
        "--product",
        action="append",
        choices=["SSE50", "CSI300", "CSI1000"],
        help="Product group to fetch. Repeat the flag to fetch multiple groups. Defaults to all groups.",
    )
    parser.add_argument("--data-root", default=str(PROJECT_ROOT / "data" / "options_wind"), help="Option parquet output root.")
    parser.add_argument("--overwrite", action="store_true", help="Refetch and overwrite existing local parquet files.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop immediately when a product/date fetch fails.")
    parser.add_argument("--active-only", action="store_true", help="Persist only contracts with positive price, volume, or open interest.")
    args = parser.parse_args()

    products = args.product or ["SSE50", "CSI300", "CSI1000"]
    client = WindPyOptionClient()
    store = OptionMarketDataStore(args.data_root)
    trade_dates = _resolve_trade_dates(client, args.date, args.start_date, args.end_date)
    fetch_option_dates(client, store, products, trade_dates, args.overwrite, args.fail_fast, args.active_only)


def fetch_option_dates(client, store, products, trade_dates, overwrite=False, fail_fast=False, active_only=False):
    failures = []
    for trade_date in trade_dates:
        for product in products:
            path = store.chain_path(product, trade_date)
            if path.exists() and not overwrite:
                continue
            try:
                chain = load_normalized_chain(client, product, trade_date)
                if active_only:
                    chain = _filter_active_chain(chain)
                path = store.write_normalized_chain(chain)
                print(f"OK {trade_date} {product} rows={len(chain)} path={path}", flush=True)
            except Exception as exc:
                if fail_fast:
                    raise
                failures.append((trade_date, product, str(exc)))
                print(f"FAIL {trade_date} {product}: {exc}", file=sys.stderr, flush=True)
    if failures:
        print("\nFailures:", file=sys.stderr, flush=True)
        for trade_date, product_group, message in failures:
            print(f"- {trade_date} {product_group}: {message}", file=sys.stderr, flush=True)
        raise SystemExit(1)


def _resolve_trade_dates(
    client: WindPyOptionClient,
    date: str | None,
    start_date: str | None,
    end_date: str | None,
) -> list[str]:
    if date and (start_date or end_date):
        raise ValueError("Use either --date or --start-date/--end-date, not both.")
    if date:
        day = pd.Timestamp(date).normalize()
        if day not in client.get_trading_calendar(date, date):
            raise ValueError(f"{date} is not a Wind trading day.")
        return [day.strftime("%Y-%m-%d")]
    if not start_date:
        raise ValueError("Either --date or --start-date is required.")
    end = end_date or default_history_range()[1]
    if pd.Timestamp(start_date) > pd.Timestamp(end):
        raise ValueError("--start-date must be on or before --end-date")
    calendar = client.get_trading_calendar(start_date, end)
    return [pd.Timestamp(item).strftime("%Y-%m-%d") for item in calendar]


def _filter_active_chain(chain: pd.DataFrame) -> pd.DataFrame:
    value_columns = [column for column in ["close", "settle", "open_interest", "volume"] if column in chain.columns]
    if not value_columns:
        return chain
    values = chain[value_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    return chain.loc[values.abs().sum(axis=1) > 0].copy()


if __name__ == "__main__":
    main()
