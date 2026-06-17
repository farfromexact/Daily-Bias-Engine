"""Fetch iFinD data and save a local snapshot for Streamlit.

Default behavior is incremental: reuse the latest iFinD snapshot when present,
fetch only newer source dates, merge raw tables, and persist a new full snapshot.
Use ``--full-refresh`` or an explicit ``--start`` to rebuild a full range.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from daily_bias_engine.data import IFindDataClient, RawDataCache
from daily_bias_engine.env import load_local_env
from daily_bias_engine.pipeline import (
    default_history_range,
    fetch_raw_inputs,
    latest_raw_data_date,
    list_snapshots,
    load_snapshot_raw,
    merge_raw_inputs,
    run_pipeline_from_client,
    run_pipeline_from_raw,
    save_snapshot,
)

load_local_env(PROJECT_ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch iFinD data and persist a local Daily Bias Engine snapshot.")
    parser.add_argument("--start", default=None, help="Start date, YYYY-MM-DD. Supplying this forces a full range fetch.")
    parser.add_argument("--end", default=None, help="End date, YYYY-MM-DD. Defaults to the latest weekday.")
    parser.add_argument("--years", type=int, default=3, help="Trailing years to retain or fetch when initializing.")
    parser.add_argument("--snapshot-root", default=str(PROJECT_ROOT / "data" / "snapshots"), help="Snapshot output directory.")
    parser.add_argument("--base-snapshot", default=None, help="Existing snapshot directory to use as the incremental base.")
    parser.add_argument("--full-refresh", action="store_true", help="Force a full range fetch instead of incremental update.")
    args = parser.parse_args()

    snapshot_dir = update_ifind_snapshot(
        snapshot_root=Path(args.snapshot_root),
        start=args.start,
        end=args.end,
        years=args.years,
        base_snapshot=Path(args.base_snapshot) if args.base_snapshot else None,
        full_refresh=args.full_refresh,
    )
    if snapshot_dir is None:
        return


def update_ifind_snapshot(
    snapshot_root: Path,
    start: str | None = None,
    end: str | None = None,
    years: int = 3,
    base_snapshot: Path | None = None,
    full_refresh: bool = False,
) -> Path | None:
    default_start, default_end = default_history_range(years=years, end_date=end)
    if full_refresh or start:
        return _full_refresh(snapshot_root, start or default_start, default_end, years)

    base_path = base_snapshot or _latest_ifind_snapshot(snapshot_root)
    if base_path is None:
        print("No existing iFinD snapshot found; initializing full history.", flush=True)
        return _full_refresh(snapshot_root, default_start, default_end, years)

    base_raw = load_snapshot_raw(base_path)
    base_latest = latest_raw_data_date(base_raw)
    if base_latest is None:
        print(f"Base snapshot has no index data; rebuilding full history from {default_start} to {default_end}.", flush=True)
        return _full_refresh(snapshot_root, default_start, default_end, years)

    end_ts = pd.Timestamp(default_end).normalize()
    if end_ts <= base_latest:
        print(f"up to date: base snapshot already covers {base_latest.date()} (target {end_ts.date()}).", flush=True)
        return None

    fetch_start = str((base_latest + pd.Timedelta(days=1)).date())
    fetch_end = str(end_ts.date())
    print(f"incremental_fetch={fetch_start} to {fetch_end} base={base_path}", flush=True)

    client = IFindDataClient(cache=RawDataCache(PROJECT_ROOT / "data" / "raw" / "ifind"))
    try:
        new_raw = fetch_raw_inputs(client, fetch_start, fetch_end)
    finally:
        client.close()

    new_latest = latest_raw_data_date(new_raw)
    if new_latest is None or new_latest <= base_latest:
        print(f"up to date: iFinD returned no new index data after {base_latest.date()}.", flush=True)
        return None

    trim_start, _ = default_history_range(years=years, end_date=new_latest)
    merged_raw = merge_raw_inputs(base_raw, new_raw, start_date=trim_start)
    snapshot_start = _raw_min_date(merged_raw) or pd.Timestamp(trim_start)
    snapshot_end = latest_raw_data_date(merged_raw) or new_latest
    result = run_pipeline_from_raw(merged_raw, config_dir=PROJECT_ROOT / "configs", data_mode="ifind")
    snapshot_dir = save_snapshot(
        result=result,
        output_root=snapshot_root,
        source="ifind",
        start_date=str(snapshot_start.date()),
        end_date=str(snapshot_end.date()),
    )
    _print_snapshot_summary(snapshot_dir, snapshot_start, snapshot_end, result)
    return snapshot_dir


def _full_refresh(snapshot_root: Path, start_date: str, end_date: str, years: int) -> Path:
    client = IFindDataClient(cache=RawDataCache(PROJECT_ROOT / "data" / "raw" / "ifind"))
    try:
        result = run_pipeline_from_client(
            client=client,
            start_date=start_date,
            end_date=end_date,
            config_dir=PROJECT_ROOT / "configs",
            data_mode="ifind",
        )
    finally:
        client.close()

    snapshot_dir = save_snapshot(
        result=result,
        output_root=snapshot_root,
        source="ifind",
        start_date=start_date,
        end_date=end_date,
    )
    _print_snapshot_summary(snapshot_dir, pd.Timestamp(start_date), pd.Timestamp(end_date), result)
    return snapshot_dir


def _latest_ifind_snapshot(snapshot_root: Path) -> Path | None:
    snapshots = [item for item in list_snapshots(snapshot_root) if item.source == "ifind"]
    return snapshots[0].path if snapshots else None


def _raw_min_date(raw: dict[str, pd.DataFrame]) -> pd.Timestamp | None:
    frame = raw.get("index_ohlcv")
    if frame is None or frame.empty:
        return None
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.min().normalize()


def _print_snapshot_summary(
    snapshot_dir: Path,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    result: dict,
) -> None:
    latest = result["report"]["latest"]
    print(f"snapshot={snapshot_dir}", flush=True)
    print(f"range={start_date.date()} to {end_date.date()}", flush=True)
    print(
        "latest="
        f"{latest.get('date')} "
        f"{latest.get('bias_label')} "
        f"score={latest.get('total_score'):.3f} "
        f"trend_prob={latest.get('trend_day_probability'):.3f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
