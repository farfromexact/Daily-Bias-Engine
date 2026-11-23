from types import SimpleNamespace

import pandas as pd
import pytest

from daily_bias_engine.options.data.wind_client import OptionDataError, WindPyOptionClient


def test_wset_chain_uses_official_expiry_and_multiplier(monkeypatch):
    def wset(name, options):
        assert name == "optionchain"
        assert options == "date=2026-11-20;us_code=000852.SH;option_var=all;call_put=all"
        return SimpleNamespace(ErrorCode=0,
                               Fields=["option_code", "us_code", "call_put", "strike_price", "first_tradedate",
                                       "last_tradedate", "expiredate", "multiplier"],
                               Data=[["MO2612-P-5500.CFE"], ["000852.SH"], ["认沽"], [5500.0],
                                     ["2026-09-01"], ["2026-12-18"], [28.0], [100.0]])

    monkeypatch.setattr("daily_bias_engine.options.data.wind_client.get_wind_session", lambda: SimpleNamespace(wset=wset))
    chain = WindPyOptionClient().get_option_contracts("CSI1000", "2026-11-20")
    row = chain.iloc[0]
    assert (row.option_type, row.expiry_date, row.multiplier_or_contract_unit) == ("put", pd.Timestamp("2026-12-18"), 100)


def test_wss_aligns_quotes_by_returned_code_and_rejects_partial_batch(monkeypatch):
    def wss(codes, fields, options):
        assert "tradeDate=20261120" in options
        return SimpleNamespace(ErrorCode=0, Codes=["B", "A"], Fields=fields.upper().split(","),
                               Data=[[2, 1]] * len(fields.split(",")))

    monkeypatch.setattr("daily_bias_engine.options.data.wind_client.get_wind_session", lambda: SimpleNamespace(wss=wss))
    client = WindPyOptionClient()
    result = client.get_option_eod(["A", "B"], "2026-11-20")
    assert result.set_index("option_code")["open_interest"].to_dict() == {"A": 1, "B": 2}
    with pytest.raises(OptionDataError, match="Incomplete Wind WSS"):
        client.get_option_eod(["A", "B", "C"], "2026-11-20")


def test_wind_quota_error_is_reported_without_partial_chain(monkeypatch):
    error = SimpleNamespace(ErrorCode=-40522017, Data=[["quota exceeded"]])
    wind = SimpleNamespace(wset=lambda *args: error)
    monkeypatch.setattr("daily_bias_engine.options.data.wind_client.get_wind_session", lambda: wind)
    with pytest.raises(OptionDataError, match="-40522017"):
        WindPyOptionClient().get_option_contracts("CSI300", "2026-11-20")
