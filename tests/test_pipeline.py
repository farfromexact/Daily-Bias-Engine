import pandas as pd

from apps.streamlit_app import CONFIG_DIR
from daily_bias_engine.pipeline import (
    fetch_raw_inputs,
    default_history_range,
    latest_raw_data_date,
    load_snapshot_outputs,
    load_snapshot_raw,
    merge_raw_inputs,
    run_pipeline_from_raw,
    save_snapshot,
)
from scripts import fetch_ifind_snapshot
from tests.fixtures import raw_ifind_like_inputs


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


def test_merge_raw_inputs_dedupes_with_new_values_and_trims_history() -> None:
    base = {
        "index_ohlcv": pd.DataFrame(
            [
                {"date": "2026-06-01", "symbol": "000300.SH", "close": 1.0},
                {"date": "2026-06-02", "symbol": "000300.SH", "close": 2.0},
            ]
        ),
        "rates": pd.DataFrame(
            [
                {"date": "2026-06-01", "series": "CGB10Y", "rate": 1.7},
                {"date": "2026-06-02", "series": "CGB10Y", "rate": 1.8},
            ]
        ),
        "etf_flow": pd.DataFrame(
            [
                {"date": "2026-06-01", "symbol": "510300.SH", "amount": 100.0, "margin_balance": 999.0},
                {"date": "2026-06-02", "symbol": "510300.SH", "amount": 200.0, "margin_balance": 999.0},
            ]
        ),
    }
    incoming = {
        "index_ohlcv": pd.DataFrame(
            [
                {"date": "2026-06-02", "symbol": "000300.SH", "close": 20.0},
                {"date": "2026-06-03", "symbol": "000300.SH", "close": 3.0},
            ]
        ),
        "rates": pd.DataFrame(
            [
                {"date": "2026-06-02", "series": "CGB10Y", "rate": 1.85},
                {"date": "2026-06-03", "series": "CGB10Y", "rate": 1.9},
            ]
        ),
        "etf_flow": pd.DataFrame(
            [
                {"date": "2026-06-03", "symbol": "510300.SH", "amount": 300.0, "margin_balance": 999.0},
            ]
        ),
    }

    merged = merge_raw_inputs(base, incoming, start_date="2026-06-02")

    index_close = merged["index_ohlcv"].set_index("date")["close"].to_dict()
    rates = merged["rates"].set_index("date")["rate"].to_dict()

    assert list(index_close) == [pd.Timestamp("2026-06-02"), pd.Timestamp("2026-06-03")]
    assert index_close[pd.Timestamp("2026-06-02")] == 20.0
    assert rates[pd.Timestamp("2026-06-02")] == 1.85
    assert merged["etf_flow"]["margin_balance"].tolist() != [999.0, 999.0]
    assert latest_raw_data_date(merged) == pd.Timestamp("2026-06-03")


def test_load_snapshot_outputs_reads_precomputed_tables(tmp_path) -> None:
    result = run_pipeline_from_raw(raw_ifind_like_inputs("2024-01-01", "2024-02-29"), config_dir=CONFIG_DIR, data_mode="ifind")
    snapshot_dir = save_snapshot(result, tmp_path, source="ifind", start_date="2024-01-01", end_date="2024-02-29")

    loaded = load_snapshot_outputs(snapshot_dir)

    assert loaded["snapshot_load_mode"] == "outputs"
    assert loaded["raw"] == {}
    assert len(loaded["factors"]) == len(result["factors"])
    assert len(loaded["scores"]) == len(result["scores"])
    assert len(loaded["labels"]) == len(result["labels"])
    assert loaded["metrics"]["observations"] == result["metrics"]["observations"]
    assert loaded["report"]["latest"]["date"] == result["report"]["latest"]["date"]


def test_ifind_snapshot_update_skips_when_base_already_covers_target(tmp_path) -> None:
    result = run_pipeline_from_raw(raw_ifind_like_inputs("2024-01-01", "2024-02-29"), config_dir=CONFIG_DIR, data_mode="ifind")
    save_snapshot(result, tmp_path, source="ifind", start_date="2024-01-01", end_date="2024-02-29")

    snapshot_dir = fetch_ifind_snapshot.update_ifind_snapshot(snapshot_root=tmp_path, end="2024-02-29")

    assert snapshot_dir is None


def test_ifind_snapshot_update_fetches_only_new_dates(monkeypatch, tmp_path) -> None:
    result = run_pipeline_from_raw(raw_ifind_like_inputs("2024-01-01", "2024-02-29"), config_dir=CONFIG_DIR, data_mode="ifind")
    save_snapshot(result, tmp_path, source="ifind", start_date="2024-01-01", end_date="2024-02-29")
    calls: list[tuple[str, str]] = []

    def fake_fetch_raw_inputs(_client: object, start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
        calls.append((start_date, end_date))
        return raw_ifind_like_inputs(start_date, end_date)

    monkeypatch.setattr(fetch_ifind_snapshot, "fetch_raw_inputs", fake_fetch_raw_inputs)

    snapshot_dir = fetch_ifind_snapshot.update_ifind_snapshot(snapshot_root=tmp_path, end="2024-03-01")

    assert calls == [("2024-03-01", "2024-03-01")]
    assert snapshot_dir is not None
    raw = load_snapshot_raw(snapshot_dir)
    assert latest_raw_data_date(raw) == pd.Timestamp("2024-03-01")


def test_ifind_snapshot_update_initializes_when_no_base(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, str]] = []

    def fake_full_refresh(snapshot_root, start_date: str, end_date: str, years: int):
        calls.append((start_date, end_date))
        return snapshot_root / "fake_snapshot"

    monkeypatch.setattr(fetch_ifind_snapshot, "_full_refresh", fake_full_refresh)

    snapshot_dir = fetch_ifind_snapshot.update_ifind_snapshot(snapshot_root=tmp_path, end="2026-06-12", years=3)

    assert snapshot_dir == tmp_path / "fake_snapshot"
    assert calls == [("2023-06-12", "2026-06-12")]


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
