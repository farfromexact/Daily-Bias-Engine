import pandas as pd
import pytest

from daily_bias_engine.options.analytics.exposure import ExposureMode, compute_contract_exposures
from daily_bias_engine.options.analytics.levels import simulate_spot_grid_gamma, zero_gamma_level


def test_exposure_units_for_etf_and_index_options() -> None:
    chain = pd.DataFrame(
        [
            _known_greek_contract("etf_call", spot=4.0, multiplier=10_000, gamma=0.5, option_type="call"),
            _known_greek_contract("index_call", spot=4000.0, multiplier=100, gamma=0.0005, option_type="call"),
        ]
    )

    exposures = compute_contract_exposures(chain, mode=ExposureMode.DEALER_SHORT_OPTIONS)

    assert exposures.loc[0, "gamma_exposure_1pct"] == pytest.approx(-80_000.0)
    assert exposures.loc[1, "gamma_exposure_1pct"] == pytest.approx(-800_000.0)
    assert exposures.loc[0, "open_interest_notional"] == pytest.approx(4_000_000.0)
    assert exposures.loc[1, "open_interest_notional"] == pytest.approx(40_000_000.0)


def test_zero_gamma_on_controlled_calibrated_chain() -> None:
    chain = pd.DataFrame(
        [
            _bs_contract("pos_95", strike=95.0, calibrated_sign=1.0),
            _bs_contract("neg_105", strike=105.0, calibrated_sign=-1.0),
        ]
    )

    grid = simulate_spot_grid_gamma(chain, mode=ExposureMode.CALIBRATED, pct_width=0.12, steps=81)
    level = zero_gamma_level(grid)

    assert level is not None
    assert 95.0 < level < 105.0


@pytest.mark.parametrize("mode", list(ExposureMode))
def test_gamma_grid_matches_contract_repricing_for_mixed_underlyings(mode):
    index = _bs_contract("index", strike=100, calibrated_sign=-0.6)
    etf = dict(index, option_code="etf", option_type="put", underlying_price=4.0, strike=4.1,
               calibrated_sign=1.0, multiplier_or_contract_unit=10000, dividend_yield=0.013)
    chain = pd.DataFrame([index, etf, dict(etf, year_fraction=0), dict(index, implied_vol=float("nan"))])
    grid = simulate_spot_grid_gamma(chain, mode, steps=5)
    for row in grid.itertuples():
        scenario = chain.assign(underlying_price=chain.underlying_price * row.spot / chain.reference_index_level)
        expected = compute_contract_exposures(scenario, mode, recalculate_greeks=True).gamma_exposure_1pct.sum()
        assert row.gamma_exposure_1pct == pytest.approx(expected, rel=1e-12)
    assert zero_gamma_level(grid.assign(gamma_exposure_1pct=0.0)) is None


def _known_greek_contract(option_code: str, spot: float, multiplier: float, gamma: float, option_type: str) -> dict[str, object]:
    return {
        "option_code": option_code,
        "option_type": option_type,
        "strike": spot,
        "underlying_price": spot,
        "year_fraction": 30 / 365,
        "risk_free_rate": 0.02,
        "dividend_yield": 0.0,
        "implied_vol": 0.2,
        "open_interest": 100,
        "multiplier_or_contract_unit": multiplier,
        "delta": 0.5,
        "gamma": gamma,
        "vega": 10.0,
        "theta": -0.01,
        "vanna": 0.1,
        "charm": 0.001,
        "volga": 0.0,
    }


def _bs_contract(option_code: str, strike: float, calibrated_sign: float) -> dict[str, object]:
    return {
        "trade_date": pd.Timestamp("2024-01-02"),
        "option_code": option_code,
        "product_group": "TEST",
        "venue": "TEST",
        "underlying_code": "TEST",
        "reference_index_code": "TEST",
        "option_type": "call",
        "strike": strike,
        "expiry_date": pd.Timestamp("2024-02-01"),
        "dte_calendar": 30,
        "dte_trading": 22,
        "year_fraction": 30 / 365,
        "multiplier_or_contract_unit": 100.0,
        "settlement_type": "cash",
        "option_style": "European",
        "adjusted_contract_flag": False,
        "open": 1.0,
        "high": 1.0,
        "low": 1.0,
        "close": 1.0,
        "settle": 1.0,
        "volume": 10,
        "open_interest": 1000,
        "bid": 0.9,
        "ask": 1.1,
        "mid": 1.0,
        "underlying_price": 100.0,
        "reference_index_level": 100.0,
        "risk_free_rate": 0.02,
        "dividend_yield": 0.0,
        "implied_vol": 0.20,
        "implied_vol_source": "test",
        "asof_time": "16:30:00",
        "source": "test",
        "calibrated_sign": calibrated_sign,
    }
