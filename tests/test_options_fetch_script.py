from pathlib import Path

import pandas as pd
import pytest

from scripts.fetch_ifind_options_snapshot import _normalized_chain_path, _resolve_trade_dates


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
    path = _normalized_chain_path(Path("data/options_ifind"), "csi300", "2026-06-05")

    assert path == Path("data/options_ifind/normalized_chain/product_group=CSI300/trade_date=2026-06-05/data.parquet")
