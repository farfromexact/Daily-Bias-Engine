"""Shared feature-calculation helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd

FACTOR_COLUMNS = [
    "date",
    "data_date",
    "factor_name",
    "raw_value",
    "zscore_value",
    "directional_score",
    "asof_time",
]


def rolling_zscore(
    values: pd.Series,
    window: int = 20,
    min_periods: int = 3,
) -> pd.Series:
    series = pd.to_numeric(values, errors="coerce")
    mean = series.rolling(window=window, min_periods=min_periods).mean()
    std = series.rolling(window=window, min_periods=min_periods).std(ddof=0)
    zscore = (series - mean) / std.replace(0.0, np.nan)
    return zscore.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def directional_score(
    zscore: pd.Series,
    polarity: float = 1.0,
    clip: float = 2.0,
) -> pd.Series:
    score = pd.to_numeric(zscore, errors="coerce").fillna(0.0) * polarity
    return score.clip(lower=-clip, upper=clip) / clip


def build_factor_frame(
    dates: pd.Series | pd.Index,
    factor_name: str,
    raw_value: pd.Series,
    zscore_value: pd.Series,
    score: pd.Series,
    asof_time: str | None,
    signal_dates: pd.Series | pd.Index | None = None,
) -> pd.DataFrame:
    data_dates = pd.DatetimeIndex(pd.to_datetime(dates)).normalize()
    if signal_dates is None:
        signal_index = data_dates + pd.offsets.BDay(1)
    else:
        signal_index = pd.DatetimeIndex(pd.to_datetime(signal_dates)).normalize()
    frame = pd.DataFrame(
        {
            "date": signal_index,
            "data_date": data_dates,
            "factor_name": factor_name,
            "raw_value": pd.to_numeric(raw_value, errors="coerce").fillna(0.0).to_numpy(),
            "zscore_value": pd.to_numeric(zscore_value, errors="coerce").fillna(0.0).to_numpy(),
            "directional_score": pd.to_numeric(score, errors="coerce").fillna(0.0).to_numpy(),
            "asof_time": asof_time or "16:30:00",
        }
    )
    return frame[FACTOR_COLUMNS]


def validate_factor_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in FACTOR_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Factor frame is missing columns: {missing}")
    clean = frame[FACTOR_COLUMNS].copy()
    clean["date"] = pd.to_datetime(clean["date"]).dt.normalize()
    clean["data_date"] = pd.to_datetime(clean["data_date"]).dt.normalize()
    clean["raw_value"] = pd.to_numeric(clean["raw_value"], errors="coerce").fillna(0.0)
    clean["zscore_value"] = pd.to_numeric(clean["zscore_value"], errors="coerce").fillna(0.0)
    clean["directional_score"] = (
        pd.to_numeric(clean["directional_score"], errors="coerce").fillna(0.0).clip(-1.0, 1.0)
    )
    if (clean["data_date"] >= clean["date"]).any():
        raise ValueError("Lookahead detected: data_date must be before signal date.")
    return clean


def daily_mean(frame: pd.DataFrame, value_column: str) -> pd.Series:
    if frame.empty:
        raise ValueError("Input frame is empty.")
    if "date" not in frame.columns or value_column not in frame.columns:
        raise ValueError(f"Input frame must include date and {value_column}.")
    prepared = frame.copy()
    prepared["date"] = pd.to_datetime(prepared["date"]).dt.normalize()
    return prepared.groupby("date", sort=True)[value_column].mean()
