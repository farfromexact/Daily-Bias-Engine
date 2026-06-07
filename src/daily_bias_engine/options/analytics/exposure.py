"""Dealer-sign-aware option exposure calculations."""

from __future__ import annotations

from enum import Enum
from typing import Mapping

import numpy as np
import pandas as pd

from daily_bias_engine.options.analytics.greeks import GREEK_COLUMNS, calculate_greeks_frame


class ExposureMode(str, Enum):
    UNSIGNED = "unsigned"
    DEALER_SHORT_OPTIONS = "dealer_short_options"
    CALIBRATED = "calibrated"


EXPOSURE_COLUMNS = [
    "delta_notional",
    "gamma_exposure_1pct",
    "vanna_exposure_1vol",
    "charm_exposure_1day",
    "vega_notional_1vol",
    "theta_1day",
    "open_interest_notional",
]


def compute_contract_exposures(
    chain: pd.DataFrame,
    mode: ExposureMode | str = ExposureMode.DEALER_SHORT_OPTIONS,
    *,
    recalculate_greeks: bool = False,
) -> pd.DataFrame:
    """Append RMB-equivalent contract exposures for the selected sign mode."""

    exposure_mode = normalize_exposure_mode(mode)
    required = {"underlying_price", "multiplier_or_contract_unit", "open_interest", "implied_vol"}
    missing = required - set(chain.columns)
    if missing:
        raise ValueError(f"Option chain is missing exposure inputs: {sorted(missing)}")

    frame = chain.copy()
    if recalculate_greeks or not set(GREEK_COLUMNS).issubset(frame.columns):
        frame = calculate_greeks_frame(frame)

    sign = _position_sign(frame, exposure_mode)
    oi = pd.to_numeric(frame["open_interest"], errors="coerce").fillna(0.0).clip(lower=0.0)
    multiplier = pd.to_numeric(frame["multiplier_or_contract_unit"], errors="coerce").fillna(0.0)
    spot = pd.to_numeric(frame["underlying_price"], errors="coerce").fillna(0.0)

    if exposure_mode == ExposureMode.UNSIGNED:
        delta = frame["delta"].abs()
        gamma = frame["gamma"].abs()
        vanna = frame["vanna"].abs()
        charm = frame["charm"].abs()
        vega = frame["vega"].abs()
        theta = frame["theta"].abs()
    else:
        delta = frame["delta"]
        gamma = frame["gamma"]
        vanna = frame["vanna"]
        charm = frame["charm"]
        vega = frame["vega"]
        theta = frame["theta"]

    frame["exposure_mode"] = exposure_mode.value
    frame["position_sign"] = sign
    frame["delta_notional"] = sign * oi * multiplier * delta * spot
    frame["gamma_exposure_1pct"] = sign * oi * multiplier * gamma * spot * spot * 0.01
    frame["vanna_exposure_1vol"] = sign * oi * multiplier * vanna * spot * 0.01
    frame["charm_exposure_1day"] = sign * oi * multiplier * charm * spot
    frame["vega_notional_1vol"] = sign * oi * multiplier * vega * 0.01
    frame["theta_1day"] = sign * oi * multiplier * theta
    frame["open_interest_notional"] = oi * multiplier * spot
    return frame


def normalize_exposure_mode(mode: ExposureMode | str) -> ExposureMode:
    if isinstance(mode, ExposureMode):
        return mode
    return ExposureMode(str(mode))


def aggregate_exposures(exposures: pd.DataFrame) -> dict[str, float]:
    """Aggregate contract-level exposures into product-level RMB measures."""

    if exposures.empty:
        return _empty_exposure_totals()
    totals = {column: float(pd.to_numeric(exposures[column], errors="coerce").fillna(0.0).sum()) for column in EXPOSURE_COLUMNS}
    return {
        "delta_notional": totals["delta_notional"],
        "gex_1pct": totals["gamma_exposure_1pct"],
        "vanna_1vol": totals["vanna_exposure_1vol"],
        "charm_1day": totals["charm_exposure_1day"],
        "vega_1vol": totals["vega_notional_1vol"],
        "theta_1day": totals["theta_1day"],
        "open_interest_notional": totals["open_interest_notional"],
    }


def _position_sign(frame: pd.DataFrame, mode: ExposureMode) -> pd.Series:
    if mode == ExposureMode.UNSIGNED:
        return pd.Series(1.0, index=frame.index)
    if mode == ExposureMode.DEALER_SHORT_OPTIONS:
        return pd.Series(-1.0, index=frame.index)
    for column in ("calibrated_sign", "dealer_sign", "position_sign"):
        if column in frame.columns:
            values = pd.to_numeric(frame[column], errors="coerce").replace(0.0, np.nan).fillna(-1.0)
            return values.clip(lower=-1.0, upper=1.0)
    return pd.Series(-1.0, index=frame.index)


def _empty_exposure_totals() -> dict[str, float]:
    return {
        "delta_notional": 0.0,
        "gex_1pct": 0.0,
        "vanna_1vol": 0.0,
        "charm_1day": 0.0,
        "vega_1vol": 0.0,
        "theta_1day": 0.0,
        "open_interest_notional": 0.0,
    }
