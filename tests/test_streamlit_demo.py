import pandas as pd
import pytest

from apps.streamlit_app import (
    CONFIG_DIR,
    _available_option_snapshots,
    _constraint_check_table,
    _date_options,
    _engine_summary_table,
    _weight_comparison_table,
    _weight_fold_table,
    run_dashboard_pipeline,
)
from daily_bias_engine.pipeline import run_pipeline_from_raw, save_snapshot
from tests.fixtures import raw_ifind_like_inputs


def test_streamlit_pipeline_reads_local_snapshot_without_launching_ui(tmp_path) -> None:
    result = run_pipeline_from_raw(raw_ifind_like_inputs("2024-01-01", "2024-02-29"), config_dir=CONFIG_DIR, data_mode="snapshot")
    snapshot_dir = save_snapshot(result, tmp_path, source="ifind_fixture", start_date="2024-01-01", end_date="2024-02-29")
    loaded = run_dashboard_pipeline(snapshot_dir=snapshot_dir)

    assert not loaded["factors"].empty
    assert not loaded["scores"].empty
    assert not loaded["labels"].empty
    assert loaded["metrics"]["observations"] > 0
    assert loaded["report"]["latest"]["bias_label"] in {"Risk-On", "Neutral", "Risk-Off"}


def test_streamlit_pipeline_requires_local_snapshot(tmp_path, monkeypatch) -> None:
    import apps.streamlit_app as streamlit_app

    monkeypatch.setattr(streamlit_app, "SNAPSHOT_ROOT", tmp_path)

    with pytest.raises(FileNotFoundError, match="No local market snapshot"):
        streamlit_app.run_dashboard_pipeline()


def test_streamlit_lists_local_option_snapshots(tmp_path) -> None:
    snapshot_file = tmp_path / "normalized_chain" / "product_group=CSI300" / "trade_date=2026-06-05" / "data.parquet"
    snapshot_file.parent.mkdir(parents=True)
    snapshot_file.write_bytes(b"local parquet marker")

    assert _available_option_snapshots(tmp_path) == {"CSI300": ["2026-06-05"]}


def test_engine_summary_table_shows_latest_signal_first() -> None:
    scores = pd.DataFrame(
        [
            {"date": "2023-06-13", "bias_label": "Neutral", "total_score": 0, "confidence": 0, "trend_day_probability": 35, "trend_direction_bias": "unclear"},
            {"date": "2026-06-15", "bias_label": "Risk-On", "total_score": 42, "confidence": 42, "trend_day_probability": 58, "trend_direction_bias": "up"},
        ]
    )

    table = _engine_summary_table(scores)

    assert table.loc[0, "信号日期"] == "2026-06-15"


def test_signal_date_options_are_sorted_unique() -> None:
    scores = pd.DataFrame(
        {
            "date": ["2026-06-15", "2026-06-08", "2026-06-15", "2026-06-12"],
        }
    )

    assert _date_options(scores) == ["2026-06-08", "2026-06-12", "2026-06-15"]


def test_weight_diagnostics_tables_render_shadow_report() -> None:
    report = {
        "current_weights": {"factor_a": 0.6, "factor_b": 0.4},
        "optimized_return_weights": {"factor_a": 0.4, "factor_b": 0.6},
        "optimized_risk_weights": {"factor_a": 0.2, "factor_b": 0.8},
        "constrained_blended_weights": {"factor_a": 0.52, "factor_b": 0.48},
        "constraint_checks": {
            "constrained_blended_weights": {"pass": True, "weight_sum": 1.0, "violations": []},
            "raw_blended_weights": {"pass": False, "weight_sum": 1.1, "violations": ["weights_sum=1.1"]},
        },
        "walk_forward_folds": [
            {
                "fold": 0,
                "train_start": "2024-01-01",
                "train_end": "2024-02-01",
                "test_start": "2024-02-02",
                "test_end": "2024-02-09",
                "sample_count": 5,
                "direction_hit_rate": 0.6,
                "strong_signal_count": 2,
            }
        ],
    }

    assert "constrained_blended_weights" in _weight_comparison_table(report).columns
    assert _constraint_check_table(report["constraint_checks"]).loc[0, "pass"] in {True, False}
    assert _weight_fold_table(report["walk_forward_folds"]).loc[0, "sample_count"] == 5
