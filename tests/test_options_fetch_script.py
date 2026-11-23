from pathlib import Path

import pandas as pd
import pytest

from daily_bias_engine.options.data import OptionMarketDataStore
from scripts.fetch_wind_options_snapshot import _resolve_trade_dates
from scripts.update_wind_data import latest_option_date


class CalendarClient:
    def get_trading_calendar(self, start: str, end: str) -> pd.DatetimeIndex:
        if start == end:
            return pd.bdate_range(start, end)
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
    path = OptionMarketDataStore().chain_path("csi300", "2026-06-05")

    assert path == Path("data/options_wind/normalized_chain/product_group=CSI300/trade_date=2026-06-05/data.parquet")


def test_latest_option_date_reads_local_product_partitions(tmp_path: Path) -> None:
    for trade_date in ["2026-06-05", "2026-06-12"]:
        path = tmp_path / "normalized_chain" / "product_group=CSI300" / f"trade_date={trade_date}" / "data.parquet"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"local parquet marker")

    assert latest_option_date(tmp_path, "CSI300") == pd.Timestamp("2026-06-12")
    assert latest_option_date(tmp_path, "SSE50") is None


def test_single_option_fetch_rejects_weekend():
    with pytest.raises(ValueError, match="not a Wind trading day"):
        _resolve_trade_dates(CalendarClient(), "2026-11-22", None, None)
