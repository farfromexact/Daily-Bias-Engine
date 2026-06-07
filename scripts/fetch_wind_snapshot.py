"""Fetch Wind data once and save a local snapshot for Streamlit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from daily_bias_engine.data import RawDataCache, WindPyDataClient
from daily_bias_engine.pipeline import run_pipeline_from_client, save_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Wind data and persist a local Daily Bias Engine snapshot.")
    parser.add_argument("--start", default="2024-01-01", help="Start date, YYYY-MM-DD.")
    parser.add_argument("--end", default="2024-04-30", help="End date, YYYY-MM-DD.")
    parser.add_argument("--snapshot-root", default=str(PROJECT_ROOT / "data" / "snapshots"), help="Snapshot output directory.")
    args = parser.parse_args()

    client = WindPyDataClient(cache=RawDataCache(PROJECT_ROOT / "data" / "raw" / "wind"))
    result = run_pipeline_from_client(
        client=client,
        start_date=args.start,
        end_date=args.end,
        config_dir=PROJECT_ROOT / "configs",
        data_mode="wind",
    )
    snapshot_dir = save_snapshot(
        result=result,
        output_root=args.snapshot_root,
        source="wind",
        start_date=args.start,
        end_date=args.end,
    )
    latest = result["report"]["latest"]
    print(f"snapshot={snapshot_dir}")
    print(
        "latest="
        f"{latest.get('date')} "
        f"{latest.get('bias_label')} "
        f"score={latest.get('total_score'):.3f} "
        f"trend_prob={latest.get('trend_day_probability'):.3f}"
    )


if __name__ == "__main__":
    main()
