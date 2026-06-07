"""Product-level option factor construction."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from daily_bias_engine.options.analytics.calendar import next_trading_day
from daily_bias_engine.options.analytics.exposure import ExposureMode, aggregate_exposures, compute_contract_exposures, normalize_exposure_mode
from daily_bias_engine.options.analytics.iv_surface import build_iv_surface_factors, realized_vol_factors
from daily_bias_engine.options.analytics.levels import calculate_key_levels


def build_option_factors(
    chain: pd.DataFrame,
    underlying_history: pd.DataFrame | None = None,
    historical_factors: pd.DataFrame | None = None,
    mode: ExposureMode | str = ExposureMode.DEALER_SHORT_OPTIONS,
) -> pd.DataFrame:
    """Build one wide product-level option factor row from a normalized chain."""

    if chain.empty:
        raise ValueError("Option chain is empty.")
    exposure_mode = normalize_exposure_mode(mode)
    exposures = compute_contract_exposures(chain, mode=exposure_mode)
    totals = aggregate_exposures(exposures)
    surface = build_iv_surface_factors(exposures)
    realized = realized_vol_factors(underlying_history)
    levels = calculate_key_levels(exposures, mode=mode)

    trade_date = pd.Timestamp(chain["trade_date"].iloc[0]).normalize()
    signal_date = next_trading_day(trade_date)
    product_group = str(chain["product_group"].iloc[0])

    call_volume = _sum_by_type(exposures, "call", "volume")
    put_volume = _sum_by_type(exposures, "put", "volume")
    call_oi = _sum_by_type(exposures, "call", "open_interest")
    put_oi = _sum_by_type(exposures, "put", "open_interest")
    total_oi = float(pd.to_numeric(exposures["open_interest"], errors="coerce").fillna(0.0).sum())
    oi_shares = pd.to_numeric(exposures["open_interest"], errors="coerce").fillna(0.0) / total_oi if total_oi > 0 else 0.0

    row: dict[str, Any] = {
        "date": signal_date,
        "signal_date": signal_date,
        "trade_date": trade_date,
        "data_date": trade_date,
        "available_time": str(chain.get("asof_time", pd.Series(["16:30:00"])).iloc[0]),
        "product_group": product_group,
        "exposure_mode": exposure_mode.value,
        "spot": levels["spot"],
        "zero_gamma": levels["zero_gamma"],
        "put_wall": levels["put_wall"],
        "call_wall": levels["call_wall"],
        "max_gamma_strike": levels["max_gamma_strike"],
        "spot_to_zero_gamma_pct": levels["spot_to_zero_gamma_pct"],
        "spot_to_put_wall_pct": levels["spot_to_put_wall_pct"],
        "spot_to_call_wall_pct": levels["spot_to_call_wall_pct"],
        "spot_to_max_gamma_pct": levels["spot_to_max_gamma_pct"],
        "pcr_volume": _safe_div(put_volume, call_volume),
        "pcr_open_interest": _safe_div(put_oi, call_oi),
        "oi_concentration_hhi": float(np.square(oi_shares).sum()) if total_oi > 0 else 0.0,
        "oi_change_by_moneyness": _oi_change_by_moneyness(exposures),
        "vanna_shock_up": totals["vanna_1vol"],
        "vanna_shock_down": -totals["vanna_1vol"],
        "charm_flow_1d": totals["charm_1day"],
        "charm_flow_3d": totals["charm_1day"] * 3.0,
        **totals,
        **surface,
        **realized,
    }
    row["vrp_30d"] = _nan_sub(row.get("iv_30d"), row.get("rv_20d"))
    _add_history_stats(row, historical_factors)
    return pd.DataFrame([row])


def _add_history_stats(row: dict[str, Any], history: pd.DataFrame | None) -> None:
    for source, output in [
        ("gex_1pct", "gex_z"),
        ("iv_30d", "iv_30d_z"),
        ("put_skew_25d", "put_skew_z"),
        ("call_skew_25d", "call_skew_z"),
    ]:
        row[output] = _z_from_history(row.get(source), history[source] if history is not None and source in history.columns else None)

    row["iv_percentile_252d"] = _percentile_from_history(
        row.get("iv_30d"),
        history["iv_30d"] if history is not None and "iv_30d" in history.columns else None,
    )
    row["iv_30d_change"] = _last_change(row.get("iv_30d"), history["iv_30d"] if history is not None and "iv_30d" in history.columns else None)
    row["put_skew_25d_change"] = _last_change(
        row.get("put_skew_25d"),
        history["put_skew_25d"] if history is not None and "put_skew_25d" in history.columns else None,
    )
    row["call_skew_25d_change"] = _last_change(
        row.get("call_skew_25d"),
        history["call_skew_25d"] if history is not None and "call_skew_25d" in history.columns else None,
    )


def _sum_by_type(frame: pd.DataFrame, option_type: str, column: str) -> float:
    subset = frame[frame["option_type"] == option_type]
    if subset.empty:
        return 0.0
    return float(pd.to_numeric(subset[column], errors="coerce").fillna(0.0).sum())


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0.0:
        return 0.0
    return float(numerator / denominator)


def _oi_change_by_moneyness(frame: pd.DataFrame) -> dict[str, float]:
    if "open_interest_change" not in frame.columns:
        return {"itm": 0.0, "atm": 0.0, "otm": 0.0}
    moneyness = frame["strike"] / frame["underlying_price"] - 1.0
    buckets = pd.cut(moneyness, bins=[-np.inf, -0.03, 0.03, np.inf], labels=["itm", "atm", "otm"])
    changes = frame.assign(bucket=buckets).groupby("bucket", observed=False)["open_interest_change"].sum()
    return {name: float(changes.get(name, 0.0)) for name in ("itm", "atm", "otm")}


def _z_from_history(value: Any, history: pd.Series | None) -> float:
    if history is None or history.dropna().empty or not np.isfinite(float(value)):
        return 0.0
    clean = pd.to_numeric(history, errors="coerce").dropna().tail(252)
    if len(clean) < 5:
        return 0.0
    std = float(clean.std(ddof=0))
    if std == 0.0:
        return 0.0
    return float((float(value) - float(clean.mean())) / std)


def _percentile_from_history(value: Any, history: pd.Series | None) -> float:
    if history is None or history.dropna().empty or not np.isfinite(float(value)):
        return float("nan")
    clean = pd.to_numeric(history, errors="coerce").dropna().tail(252)
    if clean.empty:
        return float("nan")
    return float((clean <= float(value)).mean())


def _last_change(value: Any, history: pd.Series | None) -> float:
    if history is None or history.dropna().empty or not np.isfinite(float(value)):
        return 0.0
    clean = pd.to_numeric(history, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    return float(float(value) - float(clean.iloc[-1]))


def _nan_sub(left: Any, right: Any) -> float:
    try:
        left_value = float(left)
        right_value = float(right)
    except (TypeError, ValueError):
        return float("nan")
    if not np.isfinite(left_value) or not np.isfinite(right_value):
        return float("nan")
    return float(left_value - right_value)
