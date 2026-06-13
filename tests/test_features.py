import pandas as pd
import pytest

from daily_bias_engine.features import (
    calculate_all_features,
    calculate_ashare_market_structure,
    calculate_overseas_market,
    calculate_rates_and_bond_futures,
)
from daily_bias_engine.features.base import FACTOR_COLUMNS
from tests.fixtures import raw_ifind_like_inputs


def test_all_feature_calculators_emit_required_schema() -> None:
    raw = raw_ifind_like_inputs()

    factors = calculate_all_features(
        index_ohlcv=raw["index_ohlcv"],
        futures_ohlcv=raw["futures_ohlcv"],
        open_interest=raw["open_interest"],
        rates=raw["rates"],
        etf_flow=raw["etf_flow"],
        overseas_ohlcv=raw["overseas_ohlcv"],
        ashare_ohlcv=raw["ashare_ohlcv"],
    )

    assert list(factors.columns) == FACTOR_COLUMNS
    assert factors["factor_name"].nunique() == 10
    assert factors["directional_score"].between(-1.0, 1.0).all()
    assert pd.api.types.is_datetime64_any_dtype(factors["date"])
    assert pd.api.types.is_datetime64_any_dtype(factors["data_date"])
    assert (factors["data_date"] < factors["date"]).all()


def test_overseas_market_uses_configured_country_weights() -> None:
    frame = pd.DataFrame(
        [
            {"date": "2026-06-10", "symbol": "SPX.GI", "close": 6000.0, "high": 6060.0, "low": 5940.0},
            {"date": "2026-06-11", "symbol": "SPX.GI", "close": 6060.0, "high": 6120.0, "low": 6000.0},
            {"date": "2026-06-10", "symbol": "N225.GI", "close": 40000.0, "high": 40400.0, "low": 39600.0},
            {"date": "2026-06-11", "symbol": "N225.GI", "close": 40800.0, "high": 41200.0, "low": 40400.0},
            {"date": "2026-06-10", "symbol": "KS11.GI", "close": 3000.0, "high": 3030.0, "low": 2970.0},
            {"date": "2026-06-11", "symbol": "KS11.GI", "close": 2970.0, "high": 3000.0, "low": 2940.0},
        ]
    )

    factors = calculate_overseas_market(frame)
    momentum = factors[factors["factor_name"] == "overseas_market_momentum"].set_index("data_date")["raw_value"]

    assert momentum.loc[pd.Timestamp("2026-06-11")] == pytest.approx(0.009)


def test_overseas_market_renormalizes_weights_when_a_market_is_missing() -> None:
    frame = pd.DataFrame(
        [
            {"date": "2026-06-10", "symbol": "N225.GI", "close": 40000.0, "high": 40400.0, "low": 39600.0},
            {"date": "2026-06-11", "symbol": "N225.GI", "close": 40800.0, "high": 41200.0, "low": 40400.0},
            {"date": "2026-06-10", "symbol": "KS11.GI", "close": 3000.0, "high": 3030.0, "low": 2970.0},
            {"date": "2026-06-11", "symbol": "KS11.GI", "close": 2970.0, "high": 3000.0, "low": 2940.0},
        ]
    )

    factors = calculate_overseas_market(frame)
    momentum = factors[factors["factor_name"] == "overseas_market_momentum"].set_index("data_date")["raw_value"]

    assert momentum.loc[pd.Timestamp("2026-06-11")] == pytest.approx(0.005)


def test_rates_ignore_weekend_observations_for_premarket_contract() -> None:
    frame = pd.DataFrame(
        [
            {"date": "2026-06-05", "series": "DR007.IB", "rate": 1.5},
            {"date": "2026-06-06", "series": "DR007.IB", "rate": 1.6},
            {"date": "2026-06-07", "series": "DR007.IB", "rate": 1.7},
            {"date": "2026-06-08", "series": "DR007.IB", "rate": 1.8},
        ]
    )

    factors = calculate_rates_and_bond_futures(frame)

    assert set(factors["data_date"]) == {pd.Timestamp("2026-06-05"), pd.Timestamp("2026-06-08")}


def test_yield_curve_slope_uses_30y_minus_10y_edb_series() -> None:
    frame = pd.DataFrame(
        [
            {"date": "2026-06-10", "series": "DR007.IB", "rate": 1.4},
            {"date": "2026-06-11", "series": "DR007.IB", "rate": 1.5},
            {"date": "2026-06-12", "series": "DR007.IB", "rate": 1.6},
            {"date": "2026-06-10", "series": "CGB10Y", "rate": 1.70},
            {"date": "2026-06-11", "series": "CGB10Y", "rate": 1.72},
            {"date": "2026-06-12", "series": "CGB10Y", "rate": 1.7427},
            {"date": "2026-06-10", "series": "CGB30Y", "rate": 2.20},
            {"date": "2026-06-11", "series": "CGB30Y", "rate": 2.21},
            {"date": "2026-06-12", "series": "CGB30Y", "rate": 2.2215},
        ]
    )

    factors = calculate_rates_and_bond_futures(frame)
    slope = factors[factors["factor_name"] == "yield_curve_slope"].set_index("data_date")["raw_value"]

    assert slope.loc[pd.Timestamp("2026-06-12")] == pytest.approx(0.4788)


def test_ashare_breadth_uses_configured_index_sample_only() -> None:
    frame = pd.DataFrame(
        [
            {"date": "2026-06-12", "symbol": "000016.SH", "open": 10.0, "close": 11.0, "volume": 100.0},
            {"date": "2026-06-12", "symbol": "000300.SH", "open": 10.0, "close": 9.0, "volume": 100.0},
            {"date": "2026-06-12", "symbol": "000688.SH", "open": 10.0, "close": 11.0, "volume": 100.0},
            {"date": "2026-06-12", "symbol": "399006.SZ", "open": 10.0, "close": 9.0, "volume": 100.0},
            {"date": "2026-06-12", "symbol": "000905.SH", "open": 10.0, "close": 11.0, "volume": 100.0},
        ]
    )

    factors = calculate_ashare_market_structure(frame)
    breadth = factors[factors["factor_name"] == "ashare_breadth_proxy"].set_index("data_date")["raw_value"]

    assert breadth.loc[pd.Timestamp("2026-06-12")] == pytest.approx(0.0)
