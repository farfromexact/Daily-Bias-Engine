"""Shared feature-calculation helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd

FACTOR_COLUMNS = [
    "date",
    "signal_date",
    "data_date",
    "available_time",
    "factor_name",
    "data_source",
    "raw_value",
    "zscore_value",
    "directional_score",
    "asof_time",
]

FACTOR_DATA_SOURCES = {
    "equity_index_futures_basis": "Wind daily close: IF.CFE and 000300.SH",
    "futures_open_interest_momentum": "Wind futures open interest: IF.CFE oi",
    "rates_change_5d": "Wind interest rate series: DR007.IB and CGB10Y.IB",
    "yield_curve_slope": "Wind interest rate series",
    "etf_flow_proxy": "Wind ETF daily amount: 510300.SH and 510500.SH",
    "margin_balance_momentum": "Derived proxy from ETF amount until real margin balance is connected",
    "overseas_market_momentum": "Wind overseas daily prices: SPX.GI and HSI.HI",
    "overseas_volatility_pressure": "Wind overseas high-low range proxy: SPX.GI and HSI.HI",
    "ashare_breadth_proxy": "Wind A-share index daily open and close prices",
    "ashare_turnover_momentum": "Wind A-share index daily volume",
}


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
    available_time = asof_time or "16:30:00"
    frame = pd.DataFrame(
        {
            "date": signal_index,
            "signal_date": signal_index,
            "data_date": data_dates,
            "available_time": available_time,
            "factor_name": factor_name,
            "data_source": FACTOR_DATA_SOURCES.get(factor_name, "unspecified"),
            "raw_value": pd.to_numeric(raw_value, errors="coerce").fillna(0.0).to_numpy(),
            "zscore_value": pd.to_numeric(zscore_value, errors="coerce").fillna(0.0).to_numpy(),
            "directional_score": pd.to_numeric(score, errors="coerce").fillna(0.0).to_numpy(),
            "asof_time": available_time,
        }
    )
    return frame[FACTOR_COLUMNS]


def validate_factor_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = ["date", "data_date", "factor_name", "raw_value", "zscore_value", "directional_score", "asof_time"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Factor frame is missing columns: {missing}")
    clean = frame.copy()
    if "signal_date" not in clean.columns:
        clean["signal_date"] = clean["date"]
    if "available_time" not in clean.columns:
        clean["available_time"] = clean["asof_time"]
    if "data_source" not in clean.columns:
        clean["data_source"] = clean["factor_name"].map(FACTOR_DATA_SOURCES).fillna("unspecified")
    clean = clean[FACTOR_COLUMNS].copy()
    clean["date"] = pd.to_datetime(clean["date"]).dt.normalize()
    clean["signal_date"] = pd.to_datetime(clean["signal_date"]).dt.normalize()
    clean["data_date"] = pd.to_datetime(clean["data_date"]).dt.normalize()
    clean["raw_value"] = pd.to_numeric(clean["raw_value"], errors="coerce").fillna(0.0)
    clean["zscore_value"] = pd.to_numeric(clean["zscore_value"], errors="coerce").fillna(0.0)
    clean["directional_score"] = (
        pd.to_numeric(clean["directional_score"], errors="coerce").fillna(0.0).clip(-1.0, 1.0)
    )
    clean["available_time"] = clean["available_time"].astype(str)
    clean["asof_time"] = clean["asof_time"].astype(str)
    if (clean["data_date"] >= clean["date"]).any():
        raise ValueError("Lookahead detected: data_date must be before signal date.")
    if not (clean["signal_date"] == clean["date"]).all():
        raise ValueError("Factor signal_date must match date.")
    return clean


def daily_mean(frame: pd.DataFrame, value_column: str) -> pd.Series:
    if frame.empty:
        raise ValueError("Input frame is empty.")
    if "date" not in frame.columns or value_column not in frame.columns:
        raise ValueError(f"Input frame must include date and {value_column}.")
    prepared = frame.copy()
    prepared["date"] = pd.to_datetime(prepared["date"]).dt.normalize()
    return prepared.groupby("date", sort=True)[value_column].mean()
