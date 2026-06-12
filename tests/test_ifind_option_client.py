import pandas as pd

from daily_bias_engine.options.data.ifind_client import (
    IFindOptionClient,
    _cffex_active_contract_months,
    _has_positive_market_value,
    _strike_from_cffex_code,
)


def test_strike_from_cffex_code() -> None:
    assert _strike_from_cffex_code("IO2602-C-4000.CFE") == 4000.0
    assert _strike_from_cffex_code("MO2609-P-7200.CFE") == 7200.0
    assert _strike_from_cffex_code("000300.SH") is None


def test_has_positive_market_value() -> None:
    assert _has_positive_market_value(pd.Series({"close": 0.0, "settlement": 0.0, "openInterest": 1.0}))
    assert not _has_positive_market_value(pd.Series({"close": 0.0, "settlement": 0.0, "openInterest": 0.0}))


def test_cffex_active_contract_months() -> None:
    assert _cffex_active_contract_months(pd.Timestamp("2026-01-05")) == ["2601", "2602", "2603", "2606", "2609", "2612"]
    assert _cffex_active_contract_months(pd.Timestamp("2026-02-10")) == ["2602", "2603", "2604", "2606", "2609", "2612"]


def test_cffex_expiry_uses_next_trading_day_after_third_friday() -> None:
    client = IFindOptionClient(username="unused", password="unused")
    client._calendar_cache[("2026-02-01", "2026-02-28")] = pd.DatetimeIndex(
        ["2026-02-02", "2026-02-03", "2026-02-24", "2026-02-25"]
    )

    assert client._expiry_from_cffex_code("IO2602-C-4000.CFE") == pd.Timestamp("2026-02-24")
