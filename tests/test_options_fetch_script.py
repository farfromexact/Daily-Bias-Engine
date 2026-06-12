from pathlib import Path

import pandas as pd
import pytest

from daily_bias_engine.options.data.wind_client import OptionDataError, WindPyOptionClient
from scripts.fetch_wind_options_snapshot import _filter_active_chain, _normalized_chain_path, _resolve_trade_dates


class CalendarClient:
    def get_trading_calendar(self, start: str, end: str) -> pd.DatetimeIndex:
        assert start == "2026-01-01"
        assert end == "2026-01-05"
        return pd.DatetimeIndex(["2026-01-02", "2026-01-05"])


def test_resolve_single_option_fetch_date() -> None:
    assert _resolve_trade_dates(CalendarClient(), "2026-06-05", None, None) == ["2026-06-05"]


def test_resolve_option_fetch_range_uses_trading_calendar() -> None:
    assert _resolve_trade_dates(CalendarClient(), None, "2026-01-01", "2026-01-05") == ["2026-01-02", "2026-01-05"]


def test_resolve_option_fetch_rejects_mixed_modes() -> None:
    with pytest.raises(ValueError, match="either --date or --start-date"):
        _resolve_trade_dates(CalendarClient(), "2026-06-05", "2026-01-01", None)


def test_normalized_chain_path() -> None:
    path = _normalized_chain_path(Path("data/options"), "csi300", "2026-06-05")

    assert path == Path("data/options/normalized_chain/product_group=CSI300/trade_date=2026-06-05/data.parquet")


def test_filter_active_chain_removes_zero_price_zero_interest_rows() -> None:
    chain = pd.DataFrame(
        [
            {"option_code": "active", "close": 1.0, "settle": 0.0, "open_interest": 0.0, "volume": 0.0},
            {"option_code": "position", "close": 0.0, "settle": 0.0, "open_interest": 2.0, "volume": 0.0},
            {"option_code": "zero", "close": 0.0, "settle": 0.0, "open_interest": 0.0, "volume": 0.0},
        ]
    )

    active = _filter_active_chain(chain)

    assert active["option_code"].tolist() == ["active", "position"]


def test_wind_wsd_quota_error_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    client = WindPyOptionClient()

    class Result:
        ErrorCode = -40522017
        Data = [["CWSDService:: quota exceeded."]]

    class FakeWind:
        def wsd(self, *_args: object) -> Result:
            return Result()

    monkeypatch.setattr(client, "_wind", lambda: FakeWind())

    with pytest.raises(OptionDataError, match="quota exceeded"):
        client._wsd_frame(["000300.SH"], ["close"], "2026-03-06")
