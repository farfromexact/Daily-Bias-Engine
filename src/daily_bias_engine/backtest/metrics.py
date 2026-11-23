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
    joined = scored.merge(realized, on="date", how="inner", validate="one_to_one")
    joined = joined.dropna(subset=["market_return", "trend_day_flag", "big_loss_day_flag", "bias_label"])
    bias = joined["bias_label"]
    close_return = joined["market_return"]
    correct_bias = _correct_bias(bias, close_return, neutral_return_abs_max)
    intraday = joined.get("composite_open_to_close_return", pd.Series(index=joined.index, dtype=float)).dropna()
    intraday_hits = _correct_bias(bias.loc[intraday.index], intraday, neutral_return_abs_max)

    predicted_trend = joined["trend_day_probability"] >= predicted_trend_probability
    actual_trend = joined["trend_day_flag"].astype(bool)
    actual_big_loss = joined["big_loss_day_flag"].astype(bool)
    non_big_loss = ~actual_big_loss
    risk_off = bias.eq("Risk-Off")
    loss_alerts = int((actual_big_loss & risk_off).sum())

    return {
        "observations": int(len(joined)),
        "bias_accuracy": _safe_div(int(correct_bias.sum()), len(joined)),
        "neutral_baseline_accuracy": _rate(close_return.abs().le(neutral_return_abs_max)),
        "intraday_observations": len(intraday),
        "intraday_bias_accuracy": _rate(intraday_hits),
        "intraday_neutral_baseline": _rate(intraday.abs().le(neutral_return_abs_max)),
        "directional_call_coverage": _rate(bias.ne("Neutral")),
        "big_loss_days": int(actual_big_loss.sum()),
        "risk_off_days": int(risk_off.sum()),
        "big_loss_risk_off_days": loss_alerts,
        "big_loss_risk_off_recall": _rate(risk_off[actual_big_loss]),
        "risk_off_big_loss_precision": _rate(actual_big_loss[risk_off]),
        "trend_day_precision": _safe_div(int((predicted_trend & actual_trend).sum()), int(predicted_trend.sum())),
        "trend_day_recall": _safe_div(int((predicted_trend & actual_trend).sum()), int(actual_trend.sum())),
        "big_loss_day_filter_rate": _safe_div(int((actual_big_loss & (joined["bias_label"] != "Risk-On")).sum()), int(actual_big_loss.sum())),
        "false_risk_off_rate": _safe_div(int((non_big_loss & (joined["bias_label"] == "Risk-Off")).sum()), int(non_big_loss.sum())),
    }


def _safe_div(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return float(numerator / denominator)


def _correct_bias(bias: pd.Series, returns: pd.Series, threshold: float) -> pd.Series:
    return (
        (bias.eq("Risk-On") & returns.gt(threshold))
        | (bias.eq("Risk-Off") & returns.lt(-threshold))
        | (bias.eq("Neutral") & returns.abs().le(threshold))
    )


def _rate(events: pd.Series) -> float | None:
    return float(events.mean()) if not events.empty else None
