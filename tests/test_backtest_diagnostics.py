import pandas as pd

from daily_bias_engine.backtest import (
    bias_return_diagnostics,
    factor_diagnostics,
    score_bucket_diagnostics,
    trend_probability_bucket_diagnostics,
)


def test_backtest_diagnostics_group_by_final_bias() -> None:
    scores, labels = _sample_scores_and_labels()

    diagnostics = bias_return_diagnostics(scores, labels)

    risk_off = diagnostics[diagnostics["final_bias"] == "Risk-Off"].iloc[0]
    assert risk_off["sample_count"] == 2
    assert risk_off["big_loss_day_rate"] == 0.5
    assert risk_off["max_loss"] == -0.03


def test_score_bucket_diagnostics_uses_requested_buckets() -> None:
    scores, labels = _sample_scores_and_labels()

    diagnostics = score_bucket_diagnostics(scores, labels)

    assert diagnostics["score_bucket"].astype(str).tolist() == ["<=-60", "-40~-20", "-20~0", "20~40", ">=60"]
    assert diagnostics["sample_count"].sum() == 5


def test_trend_probability_bucket_diagnostics_reports_actual_trend_rate() -> None:
    scores, labels = _sample_scores_and_labels()

    diagnostics = trend_probability_bucket_diagnostics(scores, labels)
    row = diagnostics[diagnostics["trend_probability_bucket"].astype(str) == "60-80"].iloc[0]

    assert row["sample_count"] == 2
    assert row["actual_trend_day_rate"] == 0.5


def test_factor_diagnostics_returns_summary_and_quintiles() -> None:
    dates = pd.bdate_range("2024-01-01", periods=10)
    factors = pd.DataFrame(
        {
            "date": list(dates) * 2,
            "data_date": list(dates - pd.offsets.BDay(1)) * 2,
            "factor_name": ["factor_a"] * 10 + ["factor_b"] * 10,
            "directional_score": [-0.9, -0.7, -0.5, -0.2, 0.0, 0.2, 0.5, 0.7, 0.8, 0.9] * 2,
            "raw_value": list(range(20)),
            "zscore_value": list(range(20)),
            "asof_time": ["16:30:00"] * 20,
        }
    )
    labels = pd.DataFrame(
        {
            "date": dates,
            "market_return": [-0.03, -0.02, -0.01, -0.005, 0.0, 0.002, 0.005, 0.01, 0.02, 0.03],
            "big_loss_day_flag": [True, True, False, False, False, False, False, False, False, False],
            "trend_day_flag": [True, True, False, False, False, False, False, False, True, True],
        }
    )

    diagnostics = factor_diagnostics(factors, labels)

    assert set(diagnostics) == {"summary", "quintiles"}
    assert set(diagnostics["summary"]["factor_name"]) == {"factor_a", "factor_b"}
    assert diagnostics["quintiles"]["factor_quintile"].nunique() == 5


def _sample_scores_and_labels() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    scores = pd.DataFrame(
        {
            "date": dates,
            "total_score": [-65, -35, -5, 35, 65],
            "raw_score_bias": ["Risk-Off", "Risk-Off", "Neutral", "Risk-On", "Risk-On"],
            "final_bias": ["Risk-Off", "Risk-Off", "Neutral", "Risk-On", "Risk-On"],
            "bias_label": ["Risk-Off", "Risk-Off", "Neutral", "Risk-On", "Risk-On"],
            "trend_day_probability": [15, 45, 55, 65, 75],
        }
    )
    labels = pd.DataFrame(
        {
            "date": dates,
            "market_return": [-0.03, 0.01, 0.0, 0.02, 0.04],
            "trend_day_flag": [True, False, False, True, False],
            "big_loss_day_flag": [True, False, False, False, False],
        }
    )
    return scores, labels
