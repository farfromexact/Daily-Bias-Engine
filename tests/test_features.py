import pandas as pd
import pytest

from daily_bias_engine.features import calculate_all_features, calculate_overseas_market, calculate_rates_and_bond_futures
from daily_bias_engine.features.base import FACTOR_COLUMNS
from tests.fixtures import raw_wind_like_inputs


def test_all_feature_calculators_emit_required_schema() -> None:
    raw = raw_wind_like_inputs()

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


def test_overseas_market_uses_per_symbol_returns_before_averaging() -> None:
    frame = pd.DataFrame(
        [
            {"date": "2026-06-10", "symbol": "SPX.GI", "close": 6000.0, "high": 6060.0, "low": 5940.0},
            {"date": "2026-06-11", "symbol": "SPX.GI", "close": 6060.0, "high": 6120.0, "low": 6000.0},
            {"date": "2026-06-10", "symbol": "HSI.HI", "close": 20000.0, "high": 20200.0, "low": 19800.0},
            {"date": "2026-06-11", "symbol": "HSI.HI", "close": 20200.0, "high": 20400.0, "low": 20000.0},
            {"date": "2026-06-12", "symbol": "HSI.HI", "close": 20402.0, "high": 20600.0, "low": 20200.0},
        ]
    )

    factors = calculate_overseas_market(frame)
    momentum = factors[factors["factor_name"] == "overseas_market_momentum"].set_index("data_date")["raw_value"]

    assert momentum.loc[pd.Timestamp("2026-06-11")] == pytest.approx(0.01)
    assert momentum.loc[pd.Timestamp("2026-06-12")] == pytest.approx(0.01)


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
