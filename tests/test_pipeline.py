import pandas as pd

from daily_bias_engine.pipeline import fetch_raw_inputs, default_history_range


def test_default_history_range_uses_latest_weekday_for_three_year_snapshot() -> None:
    start_date, end_date = default_history_range(years=3, end_date="2026-06-07")

    assert start_date == "2023-06-05"
    assert end_date == "2026-06-05"


def test_fetch_raw_inputs_uses_requested_market_universe() -> None:
    client = RecordingClient()

    fetch_raw_inputs(client, "2026-06-10", "2026-06-12")

    assert client.rate_calls == ["DR007.IB", "CGB10Y", "CGB30Y"]
    assert client.daily_calls["overseas_ohlcv"] == ["SPX.GI", "N225.GI", "KS11.GI"]
    assert client.daily_calls["ashare_ohlcv"] == ["000016.SH", "000300.SH", "000688.SH", "399006.SZ"]


class RecordingClient:
    def __init__(self) -> None:
        self.daily_calls: dict[str, list[str]] = {}
        self.rate_calls: list[str] = []

    def get_daily_ohlcv(self, symbols: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        if symbols == ["SPX.GI", "N225.GI", "KS11.GI"]:
            self.daily_calls["overseas_ohlcv"] = symbols
        elif symbols == ["000016.SH", "000300.SH", "000688.SH", "399006.SZ"]:
            self.daily_calls["ashare_ohlcv"] = symbols
        return pd.DataFrame(
            {
                "date": pd.to_datetime([start_date]),
                "symbol": [symbols[0]],
                "open": [1.0],
                "high": [1.1],
                "low": [0.9],
                "close": [1.0],
                "volume": [100.0],
                "amount": [100.0],
            }
        )

    def get_futures_open_interest(self, symbols: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": pd.to_datetime([start_date]),
                "symbol": [symbols[0]],
                "open_interest": [100.0],
                "volume": [100.0],
            }
        )

    def get_interest_rates(self, series: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        self.rate_calls = series
        return pd.DataFrame(
            {
                "date": pd.to_datetime([start_date]),
                "series": [series[0]],
                "rate": [1.5],
            }
        )
