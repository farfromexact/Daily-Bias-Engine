from pathlib import Path

import pandas as pd

import pytest

from daily_bias_engine.data import MockWindDataClient, RawDataCache, WindDataError, WindPyDataClient


def test_mock_wind_client_daily_ohlcv_is_deterministic() -> None:
    client = MockWindDataClient()

    first = client.get_daily_ohlcv(["000300.SH"], "2024-01-01", "2024-01-10")
    second = client.get_daily_ohlcv(["000300.SH"], "2024-01-01", "2024-01-10")

    pd.testing.assert_frame_equal(first, second)
    assert set(["date", "symbol", "open", "high", "low", "close", "volume", "amount", "asof_time"]).issubset(first.columns)
    assert first["symbol"].unique().tolist() == ["000300.SH"]


def test_mock_wind_client_supports_open_interest_and_rates() -> None:
    client = MockWindDataClient()

    oi = client.get_futures_open_interest(["IF.CFE"], "2024-01-01", "2024-01-10")
    rates = client.get_interest_rates(["DR007.IB", "CGB10Y.IB"], "2024-01-01", "2024-01-10")

    assert set(["date", "symbol", "open_interest", "volume", "asof_time"]).issubset(oi.columns)
    assert set(["date", "series", "rate", "asof_time"]).issubset(rates.columns)
    assert rates["series"].nunique() == 2


def test_raw_data_cache_writes_append_only_snapshots(tmp_path: Path) -> None:
    cache = RawDataCache(tmp_path)
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01"]),
            "symbol": ["000300.SH"],
            "close": [100.0],
        }
    )
    request = {"dataset": "daily_ohlcv", "symbols": ["000300.SH"], "start": "2024-01-01"}

    first_path = cache.write_snapshot("daily_ohlcv", request, frame, asof_time="2024-01-02T08:30:00")
    second_path = cache.write_snapshot("daily_ohlcv", request, frame, asof_time="2024-01-02T08:30:00")

    assert first_path != second_path
    assert first_path.exists()
    assert second_path.exists()
    assert len(cache.list_snapshots("daily_ohlcv", request)) == 2
    pd.testing.assert_frame_equal(cache.read_snapshot(first_path), frame)


def test_mock_client_can_cache_raw_data(tmp_path: Path) -> None:
    cache = RawDataCache(tmp_path)
    client = MockWindDataClient(cache=cache)

    frame = client.get_daily_ohlcv(["000300.SH"], "2024-01-01", "2024-01-05")

    snapshots = cache.list_snapshots("daily_ohlcv")
    assert len(snapshots) == 1
    assert not frame.empty


def test_windpy_client_reports_connection_errors() -> None:
    client = WindPyDataClient()

    try:
        frame = client.get_daily_ohlcv(["000300.SH"], "2024-04-29", "2024-04-30")
    except WindDataError as exc:
        assert "WindPy" in str(exc) or "Wind" in str(exc)
    else:
        assert set(["date", "symbol", "open", "high", "low", "close", "volume", "amount", "asof_time"]).issubset(frame.columns)
