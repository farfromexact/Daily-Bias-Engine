from pathlib import Path
import sys
import types

import pandas as pd

from daily_bias_engine.data import IFindDataClient, RawDataCache, WindDataError, WindPyDataClient


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


def test_windpy_client_reports_connection_errors() -> None:
    client = WindPyDataClient()

    try:
        frame = client.get_daily_ohlcv(["000300.SH"], "2024-04-29", "2024-04-30")
    except WindDataError as exc:
        assert "WindPy" in str(exc) or "Wind" in str(exc)
    else:
        assert set(["date", "symbol", "open", "high", "low", "close", "volume", "amount", "asof_time"]).issubset(frame.columns)


def test_ifind_client_maps_project_symbols(monkeypatch) -> None:
    calls: list[str] = []

    def login(username: str, password: str) -> int:
        return 0

    def logout() -> int:
        return 0

    def hq(thscode: str, *_args: object):
        calls.append(thscode)
        return types.SimpleNamespace(
            errorcode=0,
            errmsg="",
            data=pd.DataFrame(
                [
                    {
                        "time": "2026-06-12",
                        "thscode": thscode,
                        "open": 1.0,
                        "high": 1.2,
                        "low": 0.9,
                        "close": 1.1,
                        "volume": 100,
                        "amount": 110.0,
                    }
                ]
            ),
        )

    module = types.SimpleNamespace(
        THS_iFinDLogin=login,
        THS_iFinDLogout=logout,
        THS_GetErrorInfo=lambda code: f"error {code}",
        THS_HQ=hq,
    )
    monkeypatch.setitem(sys.modules, "iFinDPy", module)
    monkeypatch.setenv("IFIND_USERNAME", "user")
    monkeypatch.setenv("IFIND_PASSWORD", "password")

    client = IFindDataClient()
    frame = client.get_daily_ohlcv(["IF.CFE", "HSI.HI"], "2026-06-12", "2026-06-12")
    client.close()

    assert calls == ["IF00.CFE", "HSI.HK"]
    assert sorted(frame["symbol"].tolist()) == ["HSI.HI", "IF.CFE"]
    assert set(["date", "symbol", "open", "high", "low", "close", "volume", "amount", "asof_time", "source"]).issubset(
        frame.columns
    )
