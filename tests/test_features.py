import pandas as pd

from daily_bias_engine.features import calculate_all_features
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
