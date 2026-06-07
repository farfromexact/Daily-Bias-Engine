"""Gamma grids and option key level extraction."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from daily_bias_engine.options.analytics.exposure import ExposureMode, compute_contract_exposures
from daily_bias_engine.options.analytics.greeks import GREEK_COLUMNS


def simulate_spot_grid_gamma(
    chain: pd.DataFrame,
    mode: ExposureMode | str = ExposureMode.DEALER_SHORT_OPTIONS,
    *,
    pct_width: float = 0.10,
    steps: int = 101,
) -> pd.DataFrame:
    """Recalculate aggregate GEX over a sticky-strike spot grid."""

    if chain.empty:
        return pd.DataFrame(columns=["spot", "gamma_exposure_1pct"])
    spot_now = _reference_spot(chain)
    spots = np.linspace(spot_now * (1.0 - pct_width), spot_now * (1.0 + pct_width), steps)
    base_underlying = pd.to_numeric(chain["underlying_price"], errors="coerce")
    base_reference = _reference_level_series(chain).replace(0.0, np.nan)
    rows = []
    for spot in spots:
        scenario = chain.drop(columns=GREEK_COLUMNS, errors="ignore").copy()
        scenario["underlying_price"] = (base_underlying * (float(spot) / base_reference)).fillna(float(spot))
        scenario["reference_index_level"] = float(spot)
        exposures = compute_contract_exposures(scenario, mode=mode, recalculate_greeks=True)
        rows.append({"spot": float(spot), "gamma_exposure_1pct": float(exposures["gamma_exposure_1pct"].sum())})
    return pd.DataFrame(rows)


def zero_gamma_level(grid: pd.DataFrame) -> float | None:
    if grid.empty or "gamma_exposure_1pct" not in grid.columns:
        return None
    values = pd.to_numeric(grid["gamma_exposure_1pct"], errors="coerce")
    spots = pd.to_numeric(grid["spot"], errors="coerce")
    clean = pd.DataFrame({"spot": spots, "gamma": values}).dropna().sort_values("spot")
    if clean.empty:
        return None
    exact = clean.loc[clean["gamma"].abs() <= 1e-9]
    if not exact.empty:
        return float(exact.iloc[0]["spot"])
    prior_spot = float(clean.iloc[0]["spot"])
    prior_gamma = float(clean.iloc[0]["gamma"])
    for _, row in clean.iloc[1:].iterrows():
        spot = float(row["spot"])
        gamma = float(row["gamma"])
        if prior_gamma * gamma < 0:
            return float(prior_spot - prior_gamma * (spot - prior_spot) / (gamma - prior_gamma))
        prior_spot = spot
        prior_gamma = gamma
    return None


def calculate_key_levels(
    chain: pd.DataFrame,
    mode: ExposureMode | str = ExposureMode.DEALER_SHORT_OPTIONS,
) -> dict[str, Any]:
    """Return walls, zero gamma, and strike concentration tables."""

    exposures = compute_contract_exposures(chain, mode=mode)
    exposures = _with_reference_strike(exposures)
    spot = _reference_spot(exposures)
    strike_group = (
        exposures.groupby(["strike_level", "option_type"], sort=True)
        .agg(
            open_interest=("open_interest", "sum"),
            open_interest_notional=("open_interest_notional", "sum"),
            gamma_exposure_1pct=("gamma_exposure_1pct", "sum"),
            vanna_exposure_1vol=("vanna_exposure_1vol", "sum"),
        )
        .reset_index()
        .rename(columns={"strike_level": "strike"})
    )
    put_wall = _wall(strike_group, "put")
    call_wall = _wall(strike_group, "call")
    gamma_by_strike = strike_group.groupby("strike", sort=True)["gamma_exposure_1pct"].sum().reset_index()
    max_gamma_strike = None
    if not gamma_by_strike.empty:
        max_gamma_strike = float(gamma_by_strike.loc[gamma_by_strike["gamma_exposure_1pct"].abs().idxmax(), "strike"])

    grid = simulate_spot_grid_gamma(chain, mode=mode)
    zero_gamma = zero_gamma_level(grid)
    top_concentrations = top_strike_concentrations(exposures)
    return {
        "spot": spot,
        "zero_gamma": zero_gamma,
        "put_wall": put_wall,
        "call_wall": call_wall,
        "max_gamma_strike": max_gamma_strike,
        "spot_to_zero_gamma_pct": _distance_pct(spot, zero_gamma),
        "spot_to_put_wall_pct": _distance_pct(spot, put_wall),
        "spot_to_call_wall_pct": _distance_pct(spot, call_wall),
        "spot_to_max_gamma_pct": _distance_pct(spot, max_gamma_strike),
        "gamma_by_strike": gamma_by_strike,
        "spot_grid_gamma": grid,
        "top_strike_concentrations": top_concentrations,
    }


def top_strike_concentrations(exposures: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    prepared = _with_reference_strike(exposures)
    grouped = (
        prepared.groupby("strike_level", sort=True)
        .agg(
            open_interest=("open_interest", "sum"),
            open_interest_notional=("open_interest_notional", "sum"),
            gamma_exposure_1pct=("gamma_exposure_1pct", "sum"),
            put_open_interest=("open_interest", lambda values: float(values[prepared.loc[values.index, "option_type"] == "put"].sum())),
            call_open_interest=("open_interest", lambda values: float(values[prepared.loc[values.index, "option_type"] == "call"].sum())),
        )
        .reset_index()
        .rename(columns={"strike_level": "strike"})
    )
    grouped["rank_score"] = grouped["open_interest_notional"].abs() + grouped["gamma_exposure_1pct"].abs()
    return grouped.sort_values("rank_score", ascending=False).head(limit).drop(columns=["rank_score"]).reset_index(drop=True)


def _wall(strike_group: pd.DataFrame, option_type: str) -> float | None:
    subset = strike_group[strike_group["option_type"] == option_type]
    if subset.empty:
        return None
    return float(subset.loc[subset["open_interest_notional"].idxmax(), "strike"])


def _distance_pct(spot: float, level: float | None) -> float | None:
    if level is None or spot <= 0.0:
        return None
    return float(level / spot - 1.0)


def _reference_spot(frame: pd.DataFrame) -> float:
    levels = _reference_level_series(frame)
    clean = pd.to_numeric(levels, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return float(pd.to_numeric(frame["underlying_price"], errors="coerce").dropna().median())
    return float(clean.median())


def _reference_level_series(frame: pd.DataFrame) -> pd.Series:
    if "reference_index_level" in frame.columns:
        reference = pd.to_numeric(frame["reference_index_level"], errors="coerce")
        underlying = pd.to_numeric(frame["underlying_price"], errors="coerce")
        return reference.fillna(underlying)
    return pd.to_numeric(frame["underlying_price"], errors="coerce")


def _with_reference_strike(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    strike = pd.to_numeric(output["strike"], errors="coerce")
    underlying = pd.to_numeric(output["underlying_price"], errors="coerce").replace(0.0, np.nan)
    reference = _reference_level_series(output)
    output["strike_level"] = (strike * reference / underlying).replace([np.inf, -np.inf], np.nan).fillna(strike)
    return output
