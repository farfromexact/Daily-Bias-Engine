from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from daily_bias_engine.weight_optimizer import (
    ETF_MARGIN_FACTORS,
    RATES_FACTOR,
    YIELD_CURVE_FACTOR,
    WeightOptimizerConfig,
    generate_weight_diagnostic_report,
    save_weight_diagnostic_report,
)


FACTOR_NAMES = [
    "equity_index_futures_basis",
    "futures_open_interest_momentum",
    RATES_FACTOR,
    YIELD_CURVE_FACTOR,
    "etf_flow_proxy",
    "margin_balance_momentum",
    "overseas_market_momentum",
    "overseas_volatility_pressure",
    "ashare_breadth_proxy",
    "ashare_turnover_momentum",
]

GROUPS = {
    "equity_index_futures_basis": "equity_index_futures",
    "futures_open_interest_momentum": "equity_index_futures",
    RATES_FACTOR: "rates_and_bond_futures",
    YIELD_CURVE_FACTOR: "rates_and_bond_futures",
    "etf_flow_proxy": "etf_and_margin_flow",
    "margin_balance_momentum": "etf_and_margin_flow",
    "overseas_market_momentum": "overseas_market",
    "overseas_volatility_pressure": "overseas_market",
    "ashare_breadth_proxy": "ashare_market_structure",
    "ashare_turnover_momentum": "ashare_market_structure",
}

CURRENT_WEIGHTS = {factor: 0.10 for factor in FACTOR_NAMES}


def test_weight_optimizer_reports_return_and_risk_walk_forward_metrics() -> None:
    factors, labels = _synthetic_factor_data()
    report = generate_weight_diagnostic_report(factors, labels, CURRENT_WEIGHTS, GROUPS, _test_config())

    first = report["walk_forward_folds"][0]
    assert pd.Timestamp(first["train_end"]) < pd.Timestamp(first["test_start"])
    assert {
        "sample_count",
        "return_weights",
        "risk_weights",
        "return_score_test_ic",
        "direction_hit_rate",
        "strong_signal_count",
        "strong_signal_hit_rate",
        "big_loss_count",
        "TP",
        "FP",
        "TN",
        "FN",
        "big_loss_capture_rate",
        "big_loss_precision_rate",
        "big_loss_avoidance_rate",
        "max_drawdown_proxy",
    }.issubset(first)
    assert first["sample_count"] == 10


def test_constrained_blended_weights_are_projected_after_raw_blend() -> None:
    factors, labels = _synthetic_factor_data()
    report = generate_weight_diagnostic_report(factors, labels, CURRENT_WEIGHTS, GROUPS, _test_config())

    raw = report["raw_blended_weights"]
    constrained = report["constrained_blended_weights"]

    assert report["constraint_checks"]["raw_blended_weights"]["violations"]
    assert report["constraint_checks"]["constrained_blended_weights"]["pass"]
    assert math.isclose(sum(constrained.values()), 1.0, abs_tol=1e-9)
    assert constrained[RATES_FACTOR] <= 0.05 + 1e-9
    assert sum(constrained[factor] for factor in ETF_MARGIN_FACTORS) <= 0.15 + 1e-9
    assert constrained != raw


def test_yield_curve_without_real_data_is_not_allowed_in_optimizer() -> None:
    factors, labels = _synthetic_factor_data(yield_curve_real_data=False)
    report = generate_weight_diagnostic_report(factors, labels, CURRENT_WEIGHTS, GROUPS, _test_config())

    availability = {row["factor_name"]: row for row in report["factor_availability"]}
    assert availability[YIELD_CURVE_FACTOR]["data_available"] is False
    assert availability[YIELD_CURVE_FACTOR]["allowed_in_optimizer"] is False
    assert report["optimized_return_weights"][YIELD_CURVE_FACTOR] == 0.0
    assert report["optimized_risk_weights"][YIELD_CURVE_FACTOR] == 0.0
    assert report["constrained_blended_weights"][YIELD_CURVE_FACTOR] == 0.0


def test_negative_return_ic_does_not_get_positive_return_predictive_rank_bonus() -> None:
    factors, labels = _synthetic_factor_data(yield_curve_real_data=True, invert_yield_return_signal=True)
    report = generate_weight_diagnostic_report(factors, labels, CURRENT_WEIGHTS, GROUPS, _test_config())
    stability = {row["factor_name"]: row for row in report["factor_stability"]}

    assert stability[YIELD_CURVE_FACTOR]["return_ic_mean"] <= 0
    assert stability[YIELD_CURVE_FACTOR]["return_predictive_score"] == 0.0
    assert stability[YIELD_CURVE_FACTOR]["abs_stability_score"] >= 0.0


def test_first_fold_weight_training_does_not_see_future_label_changes() -> None:
    factors, labels = _synthetic_factor_data()
    cfg = _test_config()
    baseline = generate_weight_diagnostic_report(factors, labels, CURRENT_WEIGHTS, GROUPS, cfg)

    mutated = labels.copy()
    mutated.loc[mutated["date"] >= pd.Timestamp("2024-02-12"), "market_return"] *= -25.0
    changed = generate_weight_diagnostic_report(factors, mutated, CURRENT_WEIGHTS, GROUPS, cfg)

    assert baseline["walk_forward_folds"][0]["train_end"] == "2024-02-09"
    assert baseline["walk_forward_folds"][0]["return_weights"] == changed["walk_forward_folds"][0]["return_weights"]
    assert baseline["walk_forward_folds"][0]["risk_weights"] == changed["walk_forward_folds"][0]["risk_weights"]


def test_report_writer_creates_latest_json_markdown_and_csv_outputs(tmp_path) -> None:
    factors, labels = _synthetic_factor_data()
    report = generate_weight_diagnostic_report(factors, labels, CURRENT_WEIGHTS, GROUPS, _test_config())

    output = save_weight_diagnostic_report(report, tmp_path)

    expected = {
        "latest_weight_diagnostics.json",
        "latest_weight_diagnostics.md",
        "walk_forward_folds.csv",
        "factor_stability.csv",
        "bucket_analysis_return.csv",
        "bucket_analysis_risk.csv",
        "regime_factor_ic.csv",
        "recommended_weights.yaml",
    }
    assert expected.issubset({path.name for path in output.iterdir()})
    payload = json.loads((output / "latest_weight_diagnostics.json").read_text(encoding="utf-8"))
    assert payload["adoption_status"] == "not adopted until manually approved"
    assert "Executive Summary" in (output / "latest_weight_diagnostics.md").read_text(encoding="utf-8")


def _test_config() -> WeightOptimizerConfig:
    return WeightOptimizerConfig(
        train_window=30,
        test_window=10,
        step=10,
        min_train_periods=30,
        rolling_ic_window=12,
        rolling_ic_min_periods=6,
        strong_signal_threshold=0.25,
        risk_high_threshold=0.25,
        risk_extreme_threshold=0.70,
        permutation_count=3,
    )


def _synthetic_factor_data(
    *,
    yield_curve_real_data: bool = False,
    invert_yield_return_signal: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2024-01-01", periods=70)
    angle = np.arange(len(dates)) / 4.0
    returns = pd.Series(np.sin(angle) * 0.012, index=dates)
    returns.iloc[18] = -0.035
    returns.iloc[42] = -0.04
    labels = pd.DataFrame(
        {
            "date": dates,
            "market_return": returns.to_numpy(),
            "big_loss_day_flag": returns.to_numpy() <= -0.02,
        }
    )

    rows = []
    base_signal = np.sign(returns.to_numpy())
    for factor_index, factor in enumerate(FACTOR_NAMES):
        if factor == YIELD_CURVE_FACTOR and not yield_curve_real_data:
            signal = np.zeros(len(dates))
            raw = np.zeros(len(dates))
        elif factor == YIELD_CURVE_FACTOR and invert_yield_return_signal:
            signal = -base_signal * 0.7
            raw = signal * 0.01
        elif factor == RATES_FACTOR:
            signal = -base_signal * 0.4
            raw = signal
        else:
            signal = np.roll(base_signal, factor_index % 3) * (0.9 - factor_index * 0.04)
            signal[: factor_index % 3] = 0.0
            raw = signal
        for date, signal_value, raw_value in zip(dates, signal, raw):
            data_date = pd.Timestamp(date) - pd.offsets.BDay(1)
            rows.append(
                {
                    "date": date,
                    "signal_date": date,
                    "data_date": data_date,
                    "available_time": "16:30:00",
                    "factor_name": factor,
                    "data_source": "unit_test",
                    "raw_value": raw_value,
                    "zscore_value": signal_value * 2.0,
                    "directional_score": float(np.clip(signal_value, -1.0, 1.0)),
                    "asof_time": "16:30:00",
                }
            )
    return pd.DataFrame(rows), labels
