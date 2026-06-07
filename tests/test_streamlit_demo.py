from apps.streamlit_app import run_demo_pipeline


def test_streamlit_demo_pipeline_runs_without_launching_ui() -> None:
    result = run_demo_pipeline("2024-01-01", "2024-02-29")

    assert not result["factors"].empty
    assert not result["scores"].empty
    assert not result["labels"].empty
    assert result["metrics"]["observations"] > 0
    assert result["report"]["latest"]["bias_label"] in {"Risk-On", "Neutral", "Risk-Off"}
