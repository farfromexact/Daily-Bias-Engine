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
