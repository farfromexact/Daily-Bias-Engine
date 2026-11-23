from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from daily_bias_engine.data import WindPyDataClient, RawDataCache


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


def test_wind_history_maps_turnover_and_omits_unpublished_closes(monkeypatch) -> None:
    def wsd(code, fields, start, end, options):
        assert code == "IF.CFE"
        assert fields == "open,high,low,close,volume,amt"
        assert "Fill=Blank" in options
        return SimpleNamespace(ErrorCode=0, Codes=[code], Fields=fields.upper().split(","),
                               Times=[start, end], Data=[[3, None], [4, None], [2, None], [3.5, 3.5], [100, None], [350, None]])

    monkeypatch.setattr("daily_bias_engine.data.client.get_wind_session", lambda: SimpleNamespace(wsd=wsd))
    bars = WindPyDataClient().get_daily_ohlcv(["IF.CFE"], "2026-11-20", "2026-11-23")
    assert list(bars["date"]) == [pd.Timestamp("2026-11-20")]
    assert bars.iloc[0][["symbol", "amount", "close", "source"]].tolist() == ["IF.CFE", 350, 3.5, "wind"]


def test_wind_edb_yields_keep_tenors_and_requested_dates(monkeypatch) -> None:
    def edb(code, start, end, options):
        return SimpleNamespace(ErrorCode=0, Codes=[code], Fields=["close"], Times=["2010-07-30", start],
                               Data=[[None, {"S0059749": 1.7402, "S0059752": 2.2555}[code]]])

    monkeypatch.setattr("daily_bias_engine.data.client.get_wind_session", lambda: SimpleNamespace(edb=edb))
    frame = WindPyDataClient().get_interest_rates(["CGB30Y", "CGB10Y"], "2026-07-14", "2026-07-14")
    assert frame.set_index("series")["rate"].to_dict() == {"CGB10Y": 1.7402, "CGB30Y": 2.2555}
    assert frame["source"].eq("wind_edb").all()


def test_global_bars_include_actual_local_sessions_during_mainland_holidays(monkeypatch):
    def wsd(code, fields, start, end, options):
        assert code == "SPX.GI" and "Days=Alldays" in options and "Days=Trading" not in options
        return SimpleNamespace(ErrorCode=0, Fields=fields.upper().split(","), Times=[start, end],
                               Data=[[1, None], [2, None], [1, None], [2, 2], [100, None], [200, None]])
    monkeypatch.setattr("daily_bias_engine.data.client.get_wind_session", lambda: SimpleNamespace(wsd=wsd))
    frame = WindPyDataClient().get_daily_ohlcv(["SPX.GI"], "2026-10-02", "2026-10-03")
    assert frame.date.tolist() == [pd.Timestamp("2026-10-02")]


def test_liquidity_proxy_converts_billions_and_only_fills_forward():
    from scripts.test_liquidity_data_availability import INDICATORS, build_net_liquidity_proxy

    spec = next(item for item in INDICATORS if item.is_proxy)
    assets, tga, rrp = spec.proxy_components
    dates = pd.date_range("2026-06-23", periods=3)
    values = {assets: pd.Series([10000], index=dates[:1]), tga: pd.Series([1500], index=dates[1:2]),
              rrp: pd.Series([2.5, 3.0], index=dates[1:])}
    result = build_net_liquidity_proxy(spec, values)
    assert result.success
    assert result.series.to_dict() == {dates[1]: 6000.0, dates[2]: 5500.0}
