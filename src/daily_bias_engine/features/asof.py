"""As-of validation for pre-open daily signals."""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

LABEL_COLUMNS = {
    "market_return",
    "market_composite_return",
    "intraday_range",
    "open_close_direction",
    "body_ratio",
    "close_location",
    "trend_day_flag",
    "up_trend_day_flag",
    "down_trend_day_flag",
    "big_loss_day_flag",
    "choppy_day_flag",
}


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


def validate_no_lookahead_contract(
    factors: pd.DataFrame,
    market_results: pd.DataFrame | None = None,
    decision_time: str = "09:20:00",
    overseas_markers: Iterable[str] = ("overseas", "SPX", "N225", "KS11", "A50", "VIX", "CNH", "USD", "US", "JP", "KR"),
) -> pd.DataFrame:
    """Validate the no-lookahead contract for factor tables.

    The function accepts both the project-native columns
    ``date``/``asof_time`` and the explicit contract aliases
    ``signal_date``/``available_time``.
    """

    if factors.empty:
        return factors.copy()

    signal_column = _first_existing(factors, ["signal_date", "date"])
    data_date_column = _first_existing(factors, ["data_date"])
    available_column = _first_existing(factors, ["available_time", "asof_time"])
    if signal_column is None or data_date_column is None or available_column is None:
        raise ValueError("Factor table must include signal_date/date, data_date, and available_time/asof_time.")

    forbidden = LABEL_COLUMNS.intersection(factors.columns)
    if forbidden:
        raise ValueError(f"Factor table must not include realized label columns: {sorted(forbidden)}")

    clean = factors.copy()
    clean["_signal_date"] = pd.to_datetime(clean[signal_column]).dt.normalize()
    clean["_data_date"] = pd.to_datetime(clean[data_date_column]).dt.normalize()
    clean["_available_time"] = clean[available_column].map(_parse_time)
    decision = _parse_time(decision_time)
    clean["_decision_datetime"] = clean["_signal_date"] + decision
    clean["_available_datetime"] = clean["_data_date"] + clean["_available_time"]
    clean["_previous_trading_day"] = clean["_signal_date"] - pd.offsets.BDay(1)
    clean["_is_overseas"] = clean.apply(lambda row: _is_overseas_factor(row, overseas_markers), axis=1)

    domestic_violation = clean.loc[
        ~clean["_is_overseas"] & (clean["_data_date"] > clean["_previous_trading_day"]),
        [signal_column, data_date_column, "factor_name"] if "factor_name" in clean.columns else [signal_column, data_date_column],
    ]
    if not domestic_violation.empty:
        raise ValueError(
            "Lookahead detected: domestic factor data_date must be <= previous_trading_day(signal_date). "
            f"Bad rows: {domestic_violation.head(5).to_dict('records')}"
        )

    overseas_date_violation = clean.loc[
        clean["_is_overseas"] & (clean["_data_date"] > clean["_signal_date"]),
        [signal_column, data_date_column, "factor_name"] if "factor_name" in clean.columns else [signal_column, data_date_column],
    ]
    if not overseas_date_violation.empty:
        raise ValueError(
            "Lookahead detected: overseas factor data_date must be <= signal_date. "
            f"Bad rows: {overseas_date_violation.head(5).to_dict('records')}"
        )

    time_violation = clean.loc[
        clean["_available_datetime"] > clean["_decision_datetime"],
        [signal_column, data_date_column, available_column, "factor_name"] if "factor_name" in clean.columns else [signal_column, data_date_column, available_column],
    ]
    if not time_violation.empty:
        raise ValueError(
            "Lookahead detected: available_time must be <= decision_time for the signal. "
            f"Bad rows: {time_violation.head(5).to_dict('records')}"
        )

    if market_results is not None:
        _validate_market_results_alignment(market_results)

    return clean.drop(
        columns=[
            "_signal_date",
            "_data_date",
            "_available_time",
            "_decision_datetime",
            "_available_datetime",
            "_previous_trading_day",
            "_is_overseas",
        ]
    )


def _validate_market_results_alignment(market_results: pd.DataFrame) -> None:
    forbidden_factor_columns = {"factor_name", "directional_score", "zscore_value", "raw_value"}
    overlap = forbidden_factor_columns.intersection(market_results.columns)
    if overlap:
        raise ValueError(f"Market result table must not include factor columns: {sorted(overlap)}")

    if "signal_date" in market_results.columns and "date" in market_results.columns:
        signal_date = pd.to_datetime(market_results["signal_date"]).dt.normalize()
        result_date = pd.to_datetime(market_results["date"]).dt.normalize()
        if (result_date < signal_date).any():
            bad_rows = market_results.loc[result_date < signal_date, ["signal_date", "date"]].head(5)
            raise ValueError(f"market_result rows must have date >= signal_date. Bad rows: {bad_rows.to_dict('records')}")


def _first_existing(frame: pd.DataFrame, columns: list[str]) -> str | None:
    for column in columns:
        if column in frame.columns:
            return column
    return None


def _parse_time(value: Any) -> pd.Timedelta:
    if isinstance(value, pd.Timedelta):
        return value
    text = str(value)
    if "days" in text:
        return pd.to_timedelta(text)
    parts = text.split(":")
    if len(parts) == 2:
        text = f"{text}:00"
    return pd.to_timedelta(text)


def _is_overseas_factor(row: pd.Series, overseas_markers: Iterable[str]) -> bool:
    fields = []
    for column in ("data_source", "factor_name"):
        if column in row.index and pd.notna(row[column]):
            fields.append(str(row[column]))
    text = " ".join(fields).lower()
    return any(marker.lower() in text for marker in overseas_markers)
