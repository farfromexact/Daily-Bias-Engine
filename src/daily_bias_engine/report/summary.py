"""Report helpers for engine outputs."""

from __future__ import annotations

from typing import Any

import pandas as pd


def latest_record(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}
    prepared = frame.copy()
    prepared["date"] = pd.to_datetime(prepared["date"])
    latest = prepared.sort_values("date").iloc[-1].to_dict()
    if isinstance(latest.get("date"), pd.Timestamp):
        latest["date"] = latest["date"].strftime("%Y-%m-%d")
    return latest


def build_daily_report(
    factors: pd.DataFrame,
    engine_output: pd.DataFrame,
    labels: pd.DataFrame | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact JSON-serializable report payload."""

    latest_engine = latest_record(engine_output)
    latest_date = latest_engine.get("date")
    factor_rows: list[dict[str, Any]] = []
    if latest_date is not None and not factors.empty:
        factor_frame = factors.copy()
        factor_frame["date"] = pd.to_datetime(factor_frame["date"]).dt.strftime("%Y-%m-%d")
        if "data_date" in factor_frame.columns:
            factor_frame["data_date"] = pd.to_datetime(factor_frame["data_date"]).dt.strftime("%Y-%m-%d")
        factor_rows = factor_frame[factor_frame["date"] == latest_date].to_dict(orient="records")

    return {
        "latest": latest_engine,
        "latest_factors": factor_rows,
        "latest_label": latest_record(labels) if labels is not None else {},
        "metrics": metrics or {},
    }
