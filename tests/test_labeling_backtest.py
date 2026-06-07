import pandas as pd

from daily_bias_engine.backtest import evaluate_bias_predictions
from daily_bias_engine.labeling import label_market_results


def test_label_market_results_flags_requested_outcomes() -> None:
    ohlcv = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
            "symbol": ["000300.SH"] * 5,
            "open": [100.0, 100.0, 100.0, 105.5, 96.2],
            "high": [101.0, 101.0, 106.0, 106.0, 100.0],
            "low": [99.0, 99.0, 99.0, 96.0, 93.0],
            "close": [100.0, 100.2, 105.5, 96.2, 96.3],
            "volume": [1, 1, 1, 1, 1],
        }
    )

    labels = label_market_results(
        ohlcv,
        trend_body_ratio_threshold=0.60,
        trend_range_quantile=0.60,
        close_location_threshold=0.20,
        big_loss_threshold=-0.015,
        choppy_return_abs_max=0.003,
        choppy_range_min=0.01,
    )

    assert bool(labels.loc[2, "up_trend_day_flag"])
    assert bool(labels.loc[3, "down_trend_day_flag"])
    assert bool(labels.loc[3, "big_loss_day_flag"])
    assert bool(labels.loc[4, "choppy_day_flag"])
    assert "CSI300_return" in labels.columns


def test_evaluate_bias_predictions_returns_requested_metrics() -> None:
    engine_output = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
            "bias_label": ["Neutral", "Risk-On", "Risk-Off", "Risk-Off"],
            "trend_day_probability": [20, 80, 70, 10],
        }
    )
    labels = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
            "market_return": [0.0, 0.02, -0.03, 0.001],
            "trend_day_flag": [False, True, True, False],
            "big_loss_day_flag": [False, False, True, False],
        }
    )

    metrics = evaluate_bias_predictions(engine_output, labels)

    assert metrics["observations"] == 4
    assert metrics["bias_accuracy"] == 0.75
    assert metrics["trend_day_precision"] == 1.0
    assert metrics["trend_day_recall"] == 1.0
    assert metrics["big_loss_day_filter_rate"] == 1.0
    assert metrics["false_risk_off_rate"] == 1 / 3
