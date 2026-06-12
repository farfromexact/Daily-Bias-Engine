"""Fetch iFinD data once and save a local snapshot for Streamlit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from daily_bias_engine.data import IFindDataClient, RawDataCache
from daily_bias_engine.pipeline import default_history_range, run_pipeline_from_client, save_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch iFinD data and persist a local Daily Bias Engine snapshot.")
    parser.add_argument("--start", default=None, help="Start date, YYYY-MM-DD. Defaults to end minus --years.")
    parser.add_argument("--end", default=None, help="End date, YYYY-MM-DD. Defaults to the latest weekday.")
    parser.add_argument("--years", type=int, default=3, help="Trailing years to fetch when --start is omitted.")
    parser.add_argument("--snapshot-root", default=str(PROJECT_ROOT / "data" / "snapshots"), help="Snapshot output directory.")
    args = parser.parse_args()
    default_start, default_end = default_history_range(years=args.years, end_date=args.end)
    start_date = args.start or default_start
    end_date = args.end or default_end

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
        output_root=args.snapshot_root,
        source="ifind",
        start_date=start_date,
        end_date=end_date,
    )
    latest = result["report"]["latest"]
    print(f"snapshot={snapshot_dir}")
    print(f"range={start_date} to {end_date}")
    print(
        "latest="
        f"{latest.get('date')} "
        f"{latest.get('bias_label')} "
        f"score={latest.get('total_score'):.3f} "
        f"trend_prob={latest.get('trend_day_probability'):.3f}"
    )


if __name__ == "__main__":
    main()
