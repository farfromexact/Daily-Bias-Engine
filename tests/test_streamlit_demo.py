import pytest

from apps.streamlit_app import CONFIG_DIR, _available_option_snapshots, run_dashboard_pipeline
from daily_bias_engine.pipeline import run_pipeline_from_raw, save_snapshot
from tests.fixtures import raw_wind_like_inputs


def test_streamlit_pipeline_reads_local_snapshot_without_launching_ui(tmp_path) -> None:
    result = run_pipeline_from_raw(raw_wind_like_inputs("2024-01-01", "2024-02-29"), config_dir=CONFIG_DIR, data_mode="snapshot")
    snapshot_dir = save_snapshot(result, tmp_path, source="wind_fixture", start_date="2024-01-01", end_date="2024-02-29")
    loaded = run_dashboard_pipeline(snapshot_dir=snapshot_dir)

    assert not loaded["factors"].empty
    assert not loaded["scores"].empty
    assert not loaded["labels"].empty
    assert loaded["metrics"]["observations"] > 0
    assert loaded["report"]["latest"]["bias_label"] in {"Risk-On", "Neutral", "Risk-Off"}


def test_streamlit_pipeline_requires_local_snapshot(tmp_path, monkeypatch) -> None:
    import apps.streamlit_app as streamlit_app

    monkeypatch.setattr(streamlit_app, "SNAPSHOT_ROOT", tmp_path)

    with pytest.raises(FileNotFoundError, match="No local Wind snapshot"):
        streamlit_app.run_dashboard_pipeline()


def test_streamlit_lists_local_option_snapshots(tmp_path) -> None:
    snapshot_file = tmp_path / "normalized_chain" / "product_group=CSI300" / "trade_date=2026-06-05" / "data.parquet"
    snapshot_file.parent.mkdir(parents=True)
    snapshot_file.write_bytes(b"local parquet marker")

    assert _available_option_snapshots(tmp_path) == {"CSI300": ["2026-06-05"]}
