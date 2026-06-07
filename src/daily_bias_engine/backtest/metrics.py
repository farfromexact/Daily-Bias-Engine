"""Evaluation metrics for Daily Bias Engine outputs."""

from __future__ import annotations

from typing import Any

import pandas as pd


def evaluate_bias_predictions(
    engine_output: pd.DataFrame,
    labels: pd.DataFrame,
    predicted_trend_probability: float = 60.0,
    neutral_return_abs_max: float = 0.003,
) -> dict[str, Any]:
    """Evaluate bias predictions against realized market labels."""

    required_engine = {"date", "bias_label", "trend_day_probability"}
    required_labels = {
        "date",
        "market_return",
        "trend_day_flag",
        "big_loss_day_flag",
    }
    if not required_engine.issubset(engine_output.columns):
        raise ValueError(f"Engine output is missing: {sorted(required_engine - set(engine_output.columns))}")
    if not required_labels.issubset(labels.columns):
        raise ValueError(f"Labels are missing: {sorted(required_labels - set(labels.columns))}")

    scored = engine_output.copy()
    realized = labels.copy()
    scored["date"] = pd.to_datetime(scored["date"]).dt.normalize()
    realized["date"] = pd.to_datetime(realized["date"]).dt.normalize()
    joined = scored.merge(realized, on="date", how="inner")
    if joined.empty:
        return _empty_metrics()

    correct_bias = (
        ((joined["bias_label"] == "Risk-On") & (joined["market_return"] > neutral_return_abs_max))
        | ((joined["bias_label"] == "Risk-Off") & (joined["market_return"] < -neutral_return_abs_max))
        | ((joined["bias_label"] == "Neutral") & (joined["market_return"].abs() <= neutral_return_abs_max))
    )

    predicted_trend = joined["trend_day_probability"] >= predicted_trend_probability
    actual_trend = joined["trend_day_flag"].astype(bool)
    actual_big_loss = joined["big_loss_day_flag"].astype(bool)
    non_big_loss = ~actual_big_loss

    return {
        "observations": int(len(joined)),
        "bias_accuracy": _safe_div(int(correct_bias.sum()), len(joined)),
        "trend_day_precision": _safe_div(int((predicted_trend & actual_trend).sum()), int(predicted_trend.sum())),
        "trend_day_recall": _safe_div(int((predicted_trend & actual_trend).sum()), int(actual_trend.sum())),
        "big_loss_day_filter_rate": _safe_div(int((actual_big_loss & (joined["bias_label"] != "Risk-On")).sum()), int(actual_big_loss.sum())),
        "false_risk_off_rate": _safe_div(int((non_big_loss & (joined["bias_label"] == "Risk-Off")).sum()), int(non_big_loss.sum())),
    }


def _safe_div(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return float(numerator / denominator)


def _empty_metrics() -> dict[str, Any]:
    return {
        "observations": 0,
        "bias_accuracy": 0.0,
        "trend_day_precision": 0.0,
        "trend_day_recall": 0.0,
        "big_loss_day_filter_rate": 0.0,
        "false_risk_off_rate": 0.0,
    }
