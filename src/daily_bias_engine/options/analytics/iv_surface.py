"""Simple standardized IV surface factor extraction."""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

from daily_bias_engine.options.analytics.greeks import calculate_greeks_frame

TENORS = (7, 14, 30, 60, 90)


def build_iv_surface_factors(chain: pd.DataFrame) -> dict[str, float]:
    """Build nearest-neighbor standardized tenor and delta IV factors."""

    if chain.empty:
        return {}
    frame = chain.copy()
    if "delta" not in frame.columns:
        frame = calculate_greeks_frame(frame)
    factors: dict[str, float] = {}
    for tenor in TENORS:
        factors[f"atm_iv_{tenor}d"] = _nearest_atm_iv(frame, tenor)
    factors["iv_7d"] = factors.get("atm_iv_7d", np.nan)
    factors["iv_14d"] = factors.get("atm_iv_14d", np.nan)
    factors["iv_30d"] = factors.get("atm_iv_30d", np.nan)
    factors["iv_60d"] = factors.get("atm_iv_60d", np.nan)
    factors["iv_90d"] = factors.get("atm_iv_90d", np.nan)
    factors["put_25d_iv"] = _nearest_delta_iv(frame, "put", 0.25, target_dte=30)
    factors["call_25d_iv"] = _nearest_delta_iv(frame, "call", 0.25, target_dte=30)
    factors["put_10d_iv"] = _nearest_delta_iv(frame, "put", 0.10, target_dte=30)
    factors["call_10d_iv"] = _nearest_delta_iv(frame, "call", 0.10, target_dte=30)
    factors["risk_reversal_25d"] = _nan_sub(factors["call_25d_iv"], factors["put_25d_iv"])
    factors["put_skew_25d"] = _nan_sub(factors["put_25d_iv"], factors["iv_30d"])
    factors["call_skew_25d"] = _nan_sub(factors["call_25d_iv"], factors["iv_30d"])
    factors["term_structure_60d_30d"] = _nan_sub(factors["iv_60d"], factors["iv_30d"])
    factors["term_structure_30d_7d"] = _nan_sub(factors["iv_30d"], factors["iv_7d"])
    return {key: _finite_or_nan(value) for key, value in factors.items()}


def realized_volatility(close: pd.Series | Iterable[float], window: int) -> float:
    series = pd.to_numeric(pd.Series(close), errors="coerce").dropna()
    if len(series) < max(window, 2):
        return float("nan")
    returns = series.pct_change().dropna().tail(window)
    if returns.empty:
        return float("nan")
    return float(returns.std(ddof=0) * math.sqrt(252.0))


def realized_vol_factors(underlying_history: pd.DataFrame | None) -> dict[str, float]:
    if underlying_history is None or underlying_history.empty or "close" not in underlying_history.columns:
        return {f"rv_{window}d": float("nan") for window in (5, 10, 20, 60)}
    close = underlying_history.sort_values("date")["close"] if "date" in underlying_history.columns else underlying_history["close"]
    return {f"rv_{window}d": realized_volatility(close, window) for window in (5, 10, 20, 60)}


def _nearest_atm_iv(frame: pd.DataFrame, target_dte: int) -> float:
    clean = frame.dropna(subset=["implied_vol", "strike", "underlying_price", "dte_calendar"]).copy()
    if clean.empty:
        return float("nan")
    clean["distance"] = (clean["dte_calendar"] - target_dte).abs() / max(target_dte, 1) + (
        np.log(clean["strike"] / clean["underlying_price"]).abs()
    )
    return float(clean.loc[clean["distance"].idxmin(), "implied_vol"])


def _nearest_delta_iv(frame: pd.DataFrame, option_type: str, target_delta_abs: float, target_dte: int) -> float:
    clean = frame[(frame["option_type"] == option_type)].dropna(subset=["implied_vol", "delta", "dte_calendar"]).copy()
    if clean.empty:
        return float("nan")
    clean["distance"] = (clean["dte_calendar"] - target_dte).abs() / max(target_dte, 1) + (
        clean["delta"].abs() - target_delta_abs
    ).abs()
    return float(clean.loc[clean["distance"].idxmin(), "implied_vol"])


def _nan_sub(left: float, right: float) -> float:
    if not np.isfinite(left) or not np.isfinite(right):
        return float("nan")
    return float(left - right)


def _finite_or_nan(value: float) -> float:
    return float(value) if np.isfinite(value) else float("nan")
