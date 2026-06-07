"""As-of validation for pre-open daily signals."""

from __future__ import annotations

import pandas as pd


def validate_premarket_asof(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate that pre-open signal dates do not use same-day close data."""

    required = {"date", "data_date", "asof_time"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Frame is missing as-of columns: {sorted(missing)}")

    clean = frame.copy()
    clean["date"] = pd.to_datetime(clean["date"]).dt.normalize()
    clean["data_date"] = pd.to_datetime(clean["data_date"]).dt.normalize()
    if (clean["data_date"] >= clean["date"]).any():
        bad_rows = clean.loc[clean["data_date"] >= clean["date"], ["date", "data_date"]].head(5)
        raise ValueError(f"Lookahead detected: data_date must be before signal date. Bad rows: {bad_rows.to_dict('records')}")
    if clean["asof_time"].isna().any() or (clean["asof_time"].astype(str).str.len() == 0).any():
        raise ValueError("Every factor row must declare asof_time.")
    return clean
