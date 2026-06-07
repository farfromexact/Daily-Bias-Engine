import pandas as pd

from daily_bias_engine.data import MockWindDataClient
from daily_bias_engine.features import calculate_all_features
from daily_bias_engine.features.base import FACTOR_COLUMNS


def test_all_feature_calculators_emit_required_schema() -> None:
    client = MockWindDataClient()
    start = "2024-01-01"
    end = "2024-03-31"
    index_ohlcv = client.get_daily_ohlcv(["000300.SH"], start, end)
    futures_ohlcv = client.get_daily_ohlcv(["IF.CFE"], start, end)
    open_interest = client.get_futures_open_interest(["IF.CFE"], start, end)
    rates = client.get_interest_rates(["DR007.IB", "CGB10Y.IB"], start, end)
    etf_flow = client.get_daily_ohlcv(["510300.SH", "510500.SH"], start, end)
    etf_flow = etf_flow.assign(margin_balance=etf_flow["amount"] * 1.2)
    overseas = client.get_daily_ohlcv(["SPX.GI", "HSI.HI"], start, end)
    ashare = client.get_daily_ohlcv(["000300.SH", "000905.SH", "000852.SH"], start, end)

    factors = calculate_all_features(
        index_ohlcv=index_ohlcv,
        futures_ohlcv=futures_ohlcv,
        open_interest=open_interest,
        rates=rates,
        etf_flow=etf_flow,
        overseas_ohlcv=overseas,
        ashare_ohlcv=ashare,
    )

    assert list(factors.columns) == FACTOR_COLUMNS
    assert factors["factor_name"].nunique() == 10
    assert factors["directional_score"].between(-1.0, 1.0).all()
    assert pd.api.types.is_datetime64_any_dtype(factors["date"])
    assert pd.api.types.is_datetime64_any_dtype(factors["data_date"])
    assert (factors["data_date"] < factors["date"]).all()
