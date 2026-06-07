"""Calendar helpers for option analytics."""

from __future__ import annotations

from typing import Sequence

import pandas as pd


def calendar_days_to_expiry(trade_date: str | pd.Timestamp, expiry_date: str | pd.Timestamp) -> int:
    trade_ts = pd.Timestamp(trade_date).normalize()
    expiry_ts = pd.Timestamp(expiry_date).normalize()
    return max(int((expiry_ts - trade_ts).days), 0)


def trading_days_to_expiry(
    trade_date: str | pd.Timestamp,
    expiry_date: str | pd.Timestamp,
    trading_calendar: Sequence[pd.Timestamp] | pd.DatetimeIndex | None = None,
) -> int:
    trade_ts = pd.Timestamp(trade_date).normalize()
    expiry_ts = pd.Timestamp(expiry_date).normalize()
    if expiry_ts <= trade_ts:
        return 0
    if trading_calendar is None:
        dates = pd.bdate_range(trade_ts, expiry_ts)
    else:
        dates = pd.DatetimeIndex(pd.to_datetime(list(trading_calendar))).normalize()
    return int(((dates > trade_ts) & (dates <= expiry_ts)).sum())


def year_fraction(dte_calendar: int | float, basis: float = 365.0) -> float:
    return max(float(dte_calendar), 0.0) / basis


def next_trading_day(
    trade_date: str | pd.Timestamp,
    trading_calendar: Sequence[pd.Timestamp] | pd.DatetimeIndex | None = None,
) -> pd.Timestamp:
    trade_ts = pd.Timestamp(trade_date).normalize()
    if trading_calendar is None:
        return (trade_ts + pd.offsets.BDay(1)).normalize()
    dates = pd.DatetimeIndex(pd.to_datetime(list(trading_calendar))).normalize()
    future_dates = dates[dates > trade_ts]
    if future_dates.empty:
        return (trade_ts + pd.offsets.BDay(1)).normalize()
    return pd.Timestamp(future_dates[0]).normalize()
