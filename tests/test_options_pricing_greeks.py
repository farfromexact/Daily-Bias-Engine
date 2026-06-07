import pytest

from daily_bias_engine.options.analytics.greeks import calculate_greeks
from daily_bias_engine.options.analytics.pricing import black_scholes_price, implied_volatility


def test_put_call_parity_and_implied_vol_inversion() -> None:
    spot = 100.0
    strike = 100.0
    t = 30 / 365
    rate = 0.02
    vol = 0.22

    call = black_scholes_price(spot, strike, t, rate, vol, "call")
    put = black_scholes_price(spot, strike, t, rate, vol, "put")

    assert call - put == pytest.approx(spot - strike * (2.718281828459045 ** (-rate * t)), rel=1e-6)
    assert implied_volatility(call, spot, strike, t, rate, "call") == pytest.approx(vol, rel=1e-5)
    assert implied_volatility(put, spot, strike, t, rate, "put") == pytest.approx(vol, rel=1e-5)


def test_gamma_matches_finite_difference() -> None:
    spot = 100.0
    strike = 103.0
    t = 45 / 365
    rate = 0.018
    vol = 0.24
    h = 0.05

    greeks = calculate_greeks(spot, strike, t, rate, vol, "call")
    up = black_scholes_price(spot + h, strike, t, rate, vol, "call")
    mid = black_scholes_price(spot, strike, t, rate, vol, "call")
    down = black_scholes_price(spot - h, strike, t, rate, vol, "call")
    gamma_fd = (up - 2.0 * mid + down) / (h * h)

    assert greeks.gamma == pytest.approx(gamma_fd, rel=1e-4)
    assert greeks.vega > 0.0
