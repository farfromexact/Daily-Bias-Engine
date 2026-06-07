from apps.streamlit_app import run_demo_pipeline
from daily_bias_engine.pipeline import save_snapshot


def test_streamlit_demo_pipeline_runs_without_launching_ui() -> None:
    result = run_demo_pipeline("2024-01-01", "2024-02-29")

    assert not result["factors"].empty
    assert not result["scores"].empty
    assert not result["labels"].empty
    assert result["metrics"]["observations"] > 0
    assert result["report"]["latest"]["bias_label"] in {"Risk-On", "Neutral", "Risk-Off"}


def test_streamlit_pipeline_can_read_local_snapshot(tmp_path) -> None:
    result = run_demo_pipeline("2024-01-01", "2024-02-29")
    snapshot_dir = save_snapshot(result, tmp_path, source="mock", start_date="2024-01-01", end_date="2024-02-29")

    loaded = run_demo_pipeline(data_mode="snapshot", snapshot_dir=snapshot_dir)

    assert not loaded["factors"].empty
    assert loaded["data_mode"] == "snapshot"
    assert loaded["report"]["latest"]["date"] == result["report"]["latest"]["date"]
