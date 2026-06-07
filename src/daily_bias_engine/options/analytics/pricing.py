"""Black-Scholes pricing utilities with robust IV inversion."""

from __future__ import annotations

import math

import numpy as np

SQRT_2PI = math.sqrt(2.0 * math.pi)


def normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / SQRT_2PI


def normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def bs_d1_d2(
    spot: float,
    strike: float,
    year_fraction: float,
    rate: float,
    volatility: float,
    dividend_yield: float = 0.0,
) -> tuple[float, float]:
    _validate_market_inputs(spot, strike)
    t = max(float(year_fraction), 0.0)
    vol = max(float(volatility), 0.0)
    if t <= 0.0 or vol <= 0.0:
        inf = math.inf if spot >= strike else -math.inf
        return inf, inf
    sigma_root_t = vol * math.sqrt(t)
    carry = float(rate) - float(dividend_yield)
    d1 = (math.log(float(spot) / float(strike)) + (carry + 0.5 * vol * vol) * t) / sigma_root_t
    d2 = d1 - sigma_root_t
    return d1, d2


def black_scholes_price(
    spot: float,
    strike: float,
    year_fraction: float,
    rate: float,
    volatility: float,
    option_type: str,
    dividend_yield: float = 0.0,
) -> float:
    """Generalized Black-Scholes price for European calls and puts."""

    _validate_market_inputs(spot, strike)
    t = max(float(year_fraction), 0.0)
    cp = _option_sign(option_type)
    if t <= 0.0 or volatility <= 0.0:
        forward = float(spot) * math.exp((float(rate) - float(dividend_yield)) * t)
        return math.exp(-float(rate) * t) * max(cp * (forward - float(strike)), 0.0)
    d1, d2 = bs_d1_d2(spot, strike, t, rate, volatility, dividend_yield)
    df_r = math.exp(-float(rate) * t)
    df_q = math.exp(-float(dividend_yield) * t)
    return cp * (float(spot) * df_q * normal_cdf(cp * d1) - float(strike) * df_r * normal_cdf(cp * d2))


def implied_volatility(
    price: float,
    spot: float,
    strike: float,
    year_fraction: float,
    rate: float,
    option_type: str,
    dividend_yield: float = 0.0,
    *,
    min_vol: float = 1e-6,
    max_vol: float = 5.0,
    tolerance: float = 1e-8,
    max_iterations: int = 120,
) -> float:
    """Invert Black-Scholes volatility using bracketed bisection."""

    _validate_market_inputs(spot, strike)
    target = float(price)
    if target <= 0.0 or year_fraction <= 0.0:
        return float("nan")
    low_price = black_scholes_price(spot, strike, year_fraction, rate, min_vol, option_type, dividend_yield)
    if target < low_price - 1e-8:
        return float("nan")
    high = float(max_vol)
    high_price = black_scholes_price(spot, strike, year_fraction, rate, high, option_type, dividend_yield)
    while high_price < target and high < 10.0:
        high *= 1.5
        high_price = black_scholes_price(spot, strike, year_fraction, rate, high, option_type, dividend_yield)
    if high_price < target:
        return float("nan")

    low = float(min_vol)
    for _ in range(max_iterations):
        mid = (low + high) / 2.0
        value = black_scholes_price(spot, strike, year_fraction, rate, mid, option_type, dividend_yield)
        if abs(value - target) <= tolerance:
            return mid
        if value < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def synthetic_forward_from_put_call(
    call_mid: float,
    put_mid: float,
    strike: float,
    year_fraction: float,
    rate: float,
) -> float:
    """Return forward level implied by put-call parity."""

    return float(strike) + (float(call_mid) - float(put_mid)) * math.exp(float(rate) * max(float(year_fraction), 0.0))


def implied_spot_from_put_call(
    call_mid: float,
    put_mid: float,
    strike: float,
    year_fraction: float,
    rate: float,
    dividend_yield: float = 0.0,
) -> float:
    """Return spot level implied by generalized put-call parity."""

    t = max(float(year_fraction), 0.0)
    return (float(call_mid) - float(put_mid) + float(strike) * math.exp(-float(rate) * t)) * math.exp(float(dividend_yield) * t)


def _option_sign(option_type: str) -> int:
    text = str(option_type).lower()
    if text == "call":
        return 1
    if text == "put":
        return -1
    raise ValueError(f"option_type must be call or put, got {option_type!r}.")


def _validate_market_inputs(spot: float, strike: float) -> None:
    if not np.isfinite(spot) or float(spot) <= 0.0:
        raise ValueError("spot must be positive.")
    if not np.isfinite(strike) or float(strike) <= 0.0:
        raise ValueError("strike must be positive.")
