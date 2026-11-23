"""Build or increment a market snapshot using the official WindPy SDK."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from daily_bias_engine.data import MarketDataError, RawDataCache, WindPyDataClient
from daily_bias_engine.pipeline import (
    MARKET_UNIVERSE, default_history_range, fetch_raw_inputs, list_snapshots,
    load_snapshot_raw, merge_raw_inputs, run_pipeline_from_raw, save_snapshot,
)


def _last_observations(raw: dict[str, pd.DataFrame]) -> dict[tuple[str, str], pd.Timestamp]:
    dates = {}
    for table, names in MARKET_UNIVERSE.items():
        if table not in raw:
            continue
        key = "series" if table == "rates" else "symbol"
        value = {"rates": "rate", "open_interest": "open_interest", "margin_financing": "margin_balance"}.get(table, "close")
        frame = raw[table].dropna(subset=[value])
        newest = frame.groupby(key)["date"].max()
        for name in names:
            if name in newest:
                dates[table, name] = pd.Timestamp(newest[name]).normalize()
    return dates


def _latest_wind_snapshot(root: Path) -> Path | None:
    snapshots = list_snapshots(root, source="wind")
    return snapshots[0].path if snapshots else None


def update_wind_snapshot(
    snapshot_root: Path, start: str | None = None, end: str | None = None, years: int = 3,
    base_snapshot: Path | None = None, full_refresh: bool = False, dry_run: bool = False,
) -> Path | None:
    history_start, target = default_history_range(years, end)
    fetch_start = start or history_start
    base = None
    previous = {}
    expected = {(table, name) for table, names in MARKET_UNIVERSE.items() for name in names}
    if not (full_refresh or start):
        base_path = base_snapshot or _latest_wind_snapshot(snapshot_root)
        if base_path is not None:
            manifest = json.loads((base_path / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("source") != "wind":
                raise ValueError(f"Incremental base must be a Wind snapshot: {base_path}")
            base = load_snapshot_raw(base_path)
            previous = _last_observations(base)
            if previous.keys() != expected:
                print("Wind snapshot predates the current instrument universe. Rebuilding full history.", flush=True)
                base = None
            else:
                # Overseas closes and EDB rates can arrive after the domestic index close.
                first_missing = min(previous.values()) + pd.Timedelta(days=1)
                if first_missing > pd.Timestamp(target):
                    print(f"market up to date through {target}", flush=True)
                    return None
                fetch_start = str(max(pd.Timestamp(history_start), first_missing).date())
    if pd.Timestamp(fetch_start) > pd.Timestamp(target):
        raise ValueError("Start date must be on or before the target date.")
    mode = "incremental" if base is not None else "full"
    print(f"Wind market {mode}: {fetch_start} to {target}", flush=True)
    if dry_run:
        return None

    client = WindPyDataClient(cache=RawDataCache(PROJECT_ROOT / "data" / "raw" / "wind"))
    incoming = fetch_raw_inputs(client, fetch_start, target)
    observations = _last_observations(incoming)
    if base is None:
        missing = expected - observations.keys()
        if missing:
            raise MarketDataError(f"Wind returned no usable history for {sorted(missing)} in {fetch_start}..{target}")
        raw = incoming
    else:
        if not any(date > previous[key] for key, date in observations.items()):
            print("Wind has no new observations for this range.", flush=True)
            return None
        # Historical backfills with --end must never truncate a newer base snapshot.
        trim_start, _ = default_history_range(years, max(pd.Timestamp(target), previous["index_ohlcv", "000300.SH"]))
        raw = merge_raw_inputs(base, incoming, start_date=trim_start)

    dates = pd.to_datetime(raw["index_ohlcv"]["date"])
    result = run_pipeline_from_raw(raw, PROJECT_ROOT / "configs", data_mode="wind")
    path = save_snapshot(result, snapshot_root, "wind", str(dates.min().date()), str(dates.max().date()))
    print(f"snapshot={path}", flush=True)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", help="First source date. Supplying this fetches a fresh range.")
    parser.add_argument("--end", help="Last source date, YYYY-MM-DD.")
    parser.add_argument("--years", type=int, default=3, help="Trailing years to keep (default 3).")
    parser.add_argument("--snapshot-root", type=Path, default=PROJECT_ROOT / "data" / "snapshots")
    parser.add_argument("--base-snapshot", type=Path, help="Wind snapshot to use as the incremental base.")
    parser.add_argument("--full-refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Show the range without starting WindPy.")
    args = parser.parse_args()
    update_wind_snapshot(**vars(args))


if __name__ == "__main__":
    main()
