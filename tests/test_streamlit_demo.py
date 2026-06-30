import pandas as pd
import pytest
import numpy as np

from apps.streamlit_app import (
    CONFIG_DIR,
    _available_option_snapshots,
    _constraint_check_table,
    _date_options,
    _drivers_table,
    _engine_summary_table,
    _factor_contribution_table,
    _liquidity_chart_data,
    _liquidity_summary,
    _load_liquidity_data,
    _risk_flags_table,
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


def test_streamlit_pipeline_prefers_precomputed_outputs(tmp_path, monkeypatch) -> None:
    import apps.streamlit_app as streamlit_app

    result = run_pipeline_from_raw(raw_ifind_like_inputs("2024-01-01", "2024-02-29"), config_dir=CONFIG_DIR, data_mode="snapshot")
    snapshot_dir = save_snapshot(result, tmp_path, source="ifind_fixture", start_date="2024-01-01", end_date="2024-02-29")

    def fail_recalculation(*_args, **_kwargs):
        raise AssertionError("Streamlit should not recalculate when snapshot outputs exist.")

    monkeypatch.setattr(streamlit_app, "run_pipeline_from_snapshot", fail_recalculation)

    loaded = streamlit_app.run_dashboard_pipeline(snapshot_dir=snapshot_dir)

    assert loaded["snapshot_load_mode"] == "outputs"
    assert loaded["raw"] == {}
    assert not loaded["scores"].empty


def test_streamlit_pipeline_falls_back_to_raw_when_outputs_are_missing(tmp_path) -> None:
    result = run_pipeline_from_raw(raw_ifind_like_inputs("2024-01-01", "2024-02-29"), config_dir=CONFIG_DIR, data_mode="snapshot")
    snapshot_dir = save_snapshot(result, tmp_path, source="ifind_fixture", start_date="2024-01-01", end_date="2024-02-29")
    (snapshot_dir / "outputs" / "bias_daily.parquet").unlink()

    loaded = run_dashboard_pipeline(snapshot_dir=snapshot_dir)

    assert loaded["snapshot_load_mode"] == "raw_fallback"
    assert "Precomputed snapshot outputs" in loaded["snapshot_load_warning"]
    assert not loaded["scores"].empty


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


def test_nested_parquet_arrays_render_as_record_tables() -> None:
    records = np.array(
        [
            {
                "factor_name": "equity_index_futures_basis",
                "group": "equity_index_futures",
                "factor_score": 100.0,
                "contribution": 15.0,
                "raw_value": 1.0,
                "zscore_value": 2.0,
                "directional_score": 1.0,
                "weight": 0.15,
                "data_date": "2026-06-12",
            }
        ],
        dtype=object,
    )

    assert _drivers_table(records).shape[0] == 1
    assert _factor_contribution_table(records).shape[0] == 1
    assert _risk_flags_table(np.array([], dtype=object)).empty


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


def test_liquidity_loader_reads_committed_local_csvs(tmp_path) -> None:
    availability_path = tmp_path / "liquidity_data_availability.csv"
    panel_path = tmp_path / "liquidity_raw_panel.csv"
    availability_path.write_text(
        "indicator_name,actual_source_found,ticker_or_code,success / fail,latest_value\n"
        "ON RRP,FRED/public_csv,RRPONTSYD,success,3.5\n"
        "Dollar liquidity proxy / Fed Net Liquidity proxy,derived_proxy,Fed Total Assets - TGA - ON RRP,success,1000\n",
        encoding="utf-8",
    )
    panel_path.write_text(
        "date,ON RRP,Dollar liquidity proxy / Fed Net Liquidity proxy,DXY\n"
        "2026-06-28,5,990,101\n"
        "2026-06-29,3.5,1000,102\n",
        encoding="utf-8",
    )

    availability, panel = _load_liquidity_data(availability_path, panel_path)
    summary = _liquidity_summary(availability, panel)

    assert summary["success_count"] == "2"
    assert summary["latest_date"] == "2026-06-29"
    assert summary["net_liquidity"] == "1,000.000"


def test_liquidity_chart_data_can_normalize_local_panel() -> None:
    panel = pd.DataFrame(
        {
            "date": ["2026-06-28", "2026-06-29"],
            "ON RRP": [5.0, 10.0],
            "DXY": [100.0, 101.0],
        }
    )

    chart_data = _liquidity_chart_data(panel, ["ON RRP", "DXY"], normalize=True)

    assert chart_data.loc[pd.Timestamp("2026-06-28"), "ON RRP"] == 100.0
    assert chart_data.loc[pd.Timestamp("2026-06-29"), "ON RRP"] == 200.0
