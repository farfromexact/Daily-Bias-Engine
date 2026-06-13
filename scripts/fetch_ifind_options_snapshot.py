"""Fetch iFinD option data and persist normalized local parquet chains."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from daily_bias_engine.options.data import IFindOptionClient, OptionMarketDataStore, load_normalized_chain


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch iFinD A-share index option chains and persist local parquet data.")
    parser.add_argument("--date", help="Single trade date, YYYY-MM-DD.")
    parser.add_argument("--start-date", help="First trade date for range fetch, YYYY-MM-DD.")
    parser.add_argument("--end-date", help="Last trade date for range fetch, YYYY-MM-DD. Defaults to today when --start-date is set.")
    parser.add_argument(
        "--product",
        action="append",
        choices=["SSE50", "CSI300", "CSI1000"],
        help="Product group to fetch. Repeat the flag to fetch multiple groups. Defaults to all groups.",
    )
    parser.add_argument("--data-root", default=str(PROJECT_ROOT / "data" / "options_ifind"), help="Option parquet output root.")
    parser.add_argument("--overwrite", action="store_true", help="Refetch and overwrite existing local parquet files.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop immediately when a product/date fetch fails.")
    args = parser.parse_args()

    client = IFindOptionClient()
    store = OptionMarketDataStore(args.data_root)
    products = args.product or ["SSE50", "CSI300", "CSI1000"]
    trade_dates = _resolve_trade_dates(client, args.date, args.start_date, args.end_date)
    failures: list[tuple[str, str, str]] = []
    try:
        for trade_date in trade_dates:
            for product_group in products:
                existing_path = _normalized_chain_path(store.root, product_group, trade_date)
                if existing_path.exists() and not args.overwrite:
                    print(f"SKIP {trade_date} {product_group} path={existing_path}", flush=True)
                    continue
                try:
                    chain = load_normalized_chain(client, product_group, trade_date)
                    path = store.write_normalized_chain(chain)
                    print(f"OK {trade_date} {product_group} rows={len(chain)} path={path}", flush=True)
                except Exception as exc:
                    message = str(exc)
                    failures.append((trade_date, product_group, message))
                    print(f"FAIL {trade_date} {product_group}: {message}", file=sys.stderr, flush=True)
                    if args.fail_fast:
                        raise
    finally:
        client.close()

    if failures:
        print("\nFailures:", file=sys.stderr, flush=True)
        for trade_date, product_group, message in failures:
            print(f"- {trade_date} {product_group}: {message}", file=sys.stderr, flush=True)
        raise SystemExit(1)


def _resolve_trade_dates(
    client: IFindOptionClient,
    date: str | None,
    start_date: str | None,
    end_date: str | None,
) -> list[str]:
    if date and (start_date or end_date):
        raise ValueError("Use either --date or --start-date/--end-date, not both.")
    if date:
        return [pd.Timestamp(date).strftime("%Y-%m-%d")]
    if not start_date:
        raise ValueError("Either --date or --start-date is required.")
    end = end_date or pd.Timestamp.today().strftime("%Y-%m-%d")
    calendar = client.get_trading_calendar(start_date, end)
    return [pd.Timestamp(item).strftime("%Y-%m-%d") for item in calendar]


def _normalized_chain_path(root: Path, product_group: str, trade_date: str) -> Path:
    date_part = pd.Timestamp(trade_date).strftime("%Y-%m-%d")
    return root / "normalized_chain" / f"product_group={product_group.upper()}" / f"trade_date={date_part}" / "data.parquet"


if __name__ == "__main__":
    main()
