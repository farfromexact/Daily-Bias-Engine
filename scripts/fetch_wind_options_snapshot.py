"""Fetch Wind option data once and persist normalized local parquet chains."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from daily_bias_engine.options.data import OptionMarketDataStore, WindPyOptionClient, load_normalized_chain


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Wind A-share index option chains and persist local parquet data.")
    parser.add_argument("--date", required=True, help="Trade date, YYYY-MM-DD.")
    parser.add_argument(
        "--product",
        action="append",
        choices=["SSE50", "CSI300", "CSI1000"],
        help="Product group to fetch. Repeat the flag to fetch multiple groups. Defaults to all groups.",
    )
    parser.add_argument("--data-root", default=str(PROJECT_ROOT / "data" / "options"), help="Option parquet output root.")
    args = parser.parse_args()

    products = args.product or ["SSE50", "CSI300", "CSI1000"]
    client = WindPyOptionClient()
    store = OptionMarketDataStore(args.data_root)
    for product_group in products:
        chain = load_normalized_chain(client, product_group, args.date)
        path = store.write_normalized_chain(chain)
        print(f"{product_group} rows={len(chain)} path={path}")


if __name__ == "__main__":
    main()
