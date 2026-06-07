"""Black-Scholes Greeks and finite-difference higher-order flows."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from daily_bias_engine.options.analytics.pricing import black_scholes_price, bs_d1_d2, normal_cdf, normal_pdf


@dataclass(frozen=True)
class OptionGreeks:
    delta: float
    gamma: float
    vega: float
    theta: float
    vanna: float
    charm: float
    volga: float


GREEK_COLUMNS = ["delta", "gamma", "vega", "theta", "vanna", "charm", "volga"]


def calculate_greeks(
    spot: float,
    strike: float,
    year_fraction: float,
    rate: float,
    volatility: float,
    option_type: str,
    dividend_yield: float = 0.0,
) -> OptionGreeks:
    """Return Greeks for one contract.

    ``theta`` is one-calendar-day option price change from time decay.
    ``charm`` is one-calendar-day delta change, matching the exposure formula.
    ``vanna`` is delta change per 1.00 volatility unit.
    """

    spot = float(spot)
    strike = float(strike)
    t = max(float(year_fraction), 0.0)
    vol = float(volatility)
    if t <= 0.0 or vol <= 0.0 or not np.isfinite(vol):
        return OptionGreeks(delta=_expiry_delta(spot, strike, option_type), gamma=0.0, vega=0.0, theta=0.0, vanna=0.0, charm=0.0, volga=0.0)

    cp = 1.0 if option_type == "call" else -1.0
    d1, _ = bs_d1_d2(spot, strike, t, rate, vol, dividend_yield)
    df_q = math.exp(-float(dividend_yield) * t)
    delta = df_q * normal_cdf(cp * d1) if cp > 0 else df_q * (normal_cdf(d1) - 1.0)
    gamma = df_q * normal_pdf(d1) / (spot * vol * math.sqrt(t))
    vega = spot * df_q * normal_pdf(d1) * math.sqrt(t)

    day = min(1.0 / 365.0, t)
    price_now = black_scholes_price(spot, strike, t, rate, vol, option_type, dividend_yield)
    price_next = black_scholes_price(spot, strike, max(t - day, 0.0), rate, vol, option_type, dividend_yield)
    theta = price_next - price_now

    delta_next = _delta(spot, strike, max(t - day, 0.0), rate, vol, option_type, dividend_yield)
    charm = delta_next - delta

    vol_step = min(0.01, max(0.0001, vol * 0.01))
    low_vol = max(vol - vol_step, 1e-6)
    high_vol = vol + vol_step
    delta_low = _delta(spot, strike, t, rate, low_vol, option_type, dividend_yield)
    delta_high = _delta(spot, strike, t, rate, high_vol, option_type, dividend_yield)
    vanna = (delta_high - delta_low) / (high_vol - low_vol)
    vega_low = _vega(spot, strike, t, rate, low_vol, dividend_yield)
    vega_high = _vega(spot, strike, t, rate, high_vol, dividend_yield)
    volga = (vega_high - vega_low) / (high_vol - low_vol)

    return OptionGreeks(delta=delta, gamma=gamma, vega=vega, theta=theta, vanna=vanna, charm=charm, volga=volga)


def calculate_greeks_frame(chain: pd.DataFrame) -> pd.DataFrame:
    """Append Greek columns to a normalized option chain."""

    rows = []
    for _, row in chain.iterrows():
        greeks = calculate_greeks(
            spot=float(row["underlying_price"]),
            strike=float(row["strike"]),
            year_fraction=float(row["year_fraction"]),
            rate=float(row["risk_free_rate"]),
            volatility=float(row["implied_vol"]),
            option_type=str(row["option_type"]),
            dividend_yield=float(row.get("dividend_yield", 0.0)),
        )
        rows.append(greeks.__dict__)
    output = chain.copy()
    greek_frame = pd.DataFrame(rows, index=output.index)
    for column in GREEK_COLUMNS:
        output[column] = pd.to_numeric(greek_frame[column], errors="coerce").fillna(0.0)
    return output


def _delta(
    spot: float,
    strike: float,
    year_fraction: float,
    rate: float,
    volatility: float,
    option_type: str,
    dividend_yield: float,
) -> float:
    if year_fraction <= 0.0 or volatility <= 0.0:
        return _expiry_delta(spot, strike, option_type)
    cp = 1.0 if option_type == "call" else -1.0
    d1, _ = bs_d1_d2(spot, strike, year_fraction, rate, volatility, dividend_yield)
    df_q = math.exp(-float(dividend_yield) * year_fraction)
    return df_q * normal_cdf(cp * d1) if cp > 0 else df_q * (normal_cdf(d1) - 1.0)


def _vega(
    spot: float,
    strike: float,
    year_fraction: float,
    rate: float,
    volatility: float,
    dividend_yield: float,
) -> float:
    if year_fraction <= 0.0 or volatility <= 0.0:
        return 0.0
    d1, _ = bs_d1_d2(spot, strike, year_fraction, rate, volatility, dividend_yield)
    return spot * math.exp(-float(dividend_yield) * year_fraction) * normal_pdf(d1) * math.sqrt(year_fraction)


def _expiry_delta(spot: float, strike: float, option_type: str) -> float:
    if option_type == "call":
        return 1.0 if spot > strike else 0.0
    if option_type == "put":
        return -1.0 if spot < strike else 0.0
    raise ValueError(f"option_type must be call or put, got {option_type!r}.")
