"""Estimate dealer-gamma direction for a completed Wind five-minute cutoff."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from daily_bias_engine.data import WindPyDataClient
from daily_bias_engine.data.client import MarketDataError
from daily_bias_engine.options.analytics.intraday_gex import PRODUCT_ROOTS, SHANGHAI, completed_bar, local_time
from daily_bias_engine.options.data.intraday_wind import IntradayCache, WindIntradayClient
from daily_bias_engine.options.reports.intraday_gex import build_snapshot, publish_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--as-of", help="Shanghai cutoff, e.g. 2026-11-23T14:35. Defaults to now.")
    mode.add_argument("--watch", action="store_true", help="Collect each newly completed five-minute cutoff until Ctrl+C.")
    parser.add_argument("--product", action="append", choices=sorted(PRODUCT_ROOTS.values()), help="Repeat to select products.")
    parser.add_argument("--data-root", type=Path, default=PROJECT_ROOT / "data/options_wind")
    parser.add_argument("--cache-root", type=Path, default=PROJECT_ROOT / "data/raw/wind/intraday_gex")
    args = parser.parse_args()
    now = local_time(pd.Timestamp.now(tz=SHANGHAI))
    try:
        cutoff = local_time(args.as_of) if args.as_of else now
    except (ValueError, OverflowError):
        parser.error("--as-of must be a valid Shanghai or timezone-qualified timestamp.")
    if pd.isna(cutoff) or cutoff > now:
        parser.error("--as-of must be a valid past or current timestamp.")
    calendar = WindPyDataClient()
    cache = IntradayCache(args.cache_root)
    client = WindIntradayClient()
    products = list(dict.fromkeys(args.product or PRODUCT_ROOTS.values()))
    last_done = {}
    sessions_day = None
    while True:
        if args.watch:
            cutoff = local_time(pd.Timestamp.now(tz=SHANGHAI)) - pd.Timedelta(seconds=15)
        try:
            if sessions_day != cutoff.date():
                sessions = calendar.get_trading_calendar(cutoff.normalize() - pd.Timedelta(days=55), cutoff.normalize())
                sessions_day = cutoff.date()
            end = completed_bar(cutoff, sessions)
            for product in products:
                if last_done.get(product) == end:
                    continue
                print(f"Wind intraday {product} through {end}", flush=True)
                try:
                    report = build_snapshot(product, end, sessions, args.data_root, cache, client)
                    path = publish_snapshot(report, args.data_root)
                except (MarketDataError, OSError, ValueError) as exc:
                    print(f"{product}: {exc}", file=sys.stderr, flush=True)
                    continue
                last_done[product] = end
                print(f"{report['as_of']} {report['sign']} {path}", flush=True)
            if not args.watch:
                if not all(last_done.get(p) == end for p in products):
                    raise SystemExit(1)
                return
        except (MarketDataError, OSError, ValueError) as exc:
            if not args.watch:
                raise
            print(f"Wind calendar: {exc}", file=sys.stderr, flush=True)
        time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
