from __future__ import annotations

import math

import numpy as np
import pandas as pd

from daily_bias_engine.weight_optimizer import (
    ETF_MARGIN_FACTORS,
    RATES_FACTOR,
    YIELD_CURVE_FACTOR,
    WeightOptimizerConfig,
    generate_weight_diagnostic_report,
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


def test_weight_optimizer_uses_chronological_walk_forward_and_reports_metrics() -> None:
    factors, labels = _synthetic_factor_data()
    report = generate_weight_diagnostic_report(factors, labels, CURRENT_WEIGHTS, GROUPS, _test_config())

    assert report["walk_forward_folds"]
    first = report["walk_forward_folds"][0]
    assert pd.Timestamp(first["train_end"]) < pd.Timestamp(first["test_start"])
    assert {
        "test_ic",
        "direction_hit_rate",
        "strong_signal_hit_rate",
        "big_loss_capture_rate",
        "big_loss_avoidance_rate",
        "max_drawdown_proxy",
        "sample_count",
        "weights",
    }.issubset(first)
    assert first["sample_count"] == 10


def test_weight_optimizer_applies_requested_constraints() -> None:
    factors, labels = _synthetic_factor_data()
    report = generate_weight_diagnostic_report(factors, labels, CURRENT_WEIGHTS, GROUPS, _test_config())
    weights = report["optimized_weights"]

    assert not report["constraint_checks"]["optimized_weights"]
    assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9)
    assert all(value >= 0 for value in weights.values())
    assert all(value <= 0.25 + 1e-9 for value in weights.values())
    assert weights[YIELD_CURVE_FACTOR] == 0.0
    assert weights[RATES_FACTOR] <= 0.05 + 1e-9
    assert sum(weights[factor] for factor in ETF_MARGIN_FACTORS) <= 0.15 + 1e-9
    for group in set(GROUPS.values()):
        assert sum(value for factor, value in weights.items() if GROUPS[factor] == group) <= 0.35 + 1e-9


def test_first_fold_weight_training_does_not_see_future_label_changes() -> None:
    factors, labels = _synthetic_factor_data()
    cfg = _test_config()
    baseline = generate_weight_diagnostic_report(factors, labels, CURRENT_WEIGHTS, GROUPS, cfg)

    mutated = labels.copy()
    mutated.loc[mutated["date"] >= pd.Timestamp("2024-02-12"), "market_return"] *= -25.0
    changed = generate_weight_diagnostic_report(factors, mutated, CURRENT_WEIGHTS, GROUPS, cfg)

    assert baseline["walk_forward_folds"][0]["train_end"] == "2024-02-09"
    assert baseline["walk_forward_folds"][0]["weights"] == changed["walk_forward_folds"][0]["weights"]


def test_weight_optimizer_outputs_current_optimized_and_formula_blended_weights() -> None:
    factors, labels = _synthetic_factor_data()
    report = generate_weight_diagnostic_report(factors, labels, CURRENT_WEIGHTS, GROUPS, _test_config())

    assert set(report["current_weights"]) == set(FACTOR_NAMES)
    assert set(report["optimized_weights"]) == set(FACTOR_NAMES)
    assert set(report["blended_weights"]) == set(FACTOR_NAMES)
    for factor in FACTOR_NAMES:
        expected = 0.6 * report["current_weights"][factor] + 0.4 * report["optimized_weights"][factor]
        assert math.isclose(report["blended_weights"][factor], expected, abs_tol=1e-12)
    assert {row["factor_name"] for row in report["factor_stability"]} == set(FACTOR_NAMES)
    assert {row["factor_name"] for row in report["rolling_ic"]} == set(FACTOR_NAMES)


def _test_config() -> WeightOptimizerConfig:
    return WeightOptimizerConfig(
        train_window=30,
        test_window=10,
        step=10,
        min_train_periods=30,
        rolling_ic_window=12,
        rolling_ic_min_periods=6,
        strong_signal_threshold=0.25,
    )


def _synthetic_factor_data() -> tuple[pd.DataFrame, pd.DataFrame]:
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
        if factor == YIELD_CURVE_FACTOR:
            signal = np.zeros(len(dates))
            raw = np.zeros(len(dates))
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
