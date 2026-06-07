"""Diagnostics for historical signal and factor behavior."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


SCORE_BUCKET_ORDER = ["<=-60", "-60~-40", "-40~-20", "-20~0", "0~20", "20~40", "40~60", ">=60"]
TREND_PROBABILITY_BUCKET_ORDER = ["0-20", "20-40", "40-60", "60-80", "80-100"]


def bias_return_diagnostics(
    engine_output: pd.DataFrame,
    labels: pd.DataFrame,
    big_up_threshold: float = 0.015,
) -> pd.DataFrame:
    """Group realized market results by final bias."""

    joined = prepare_signal_label_frame(engine_output, labels)
    if joined.empty:
        return _empty_return_stats("final_bias")
    return _return_stats(joined, "final_bias", big_up_threshold, bucket_order=None)


def score_bucket_diagnostics(
    engine_output: pd.DataFrame,
    labels: pd.DataFrame,
    big_up_threshold: float = 0.015,
) -> pd.DataFrame:
    """Bucket total score and summarize realized returns."""

    joined = prepare_signal_label_frame(engine_output, labels)
    if joined.empty:
        return _empty_return_stats("score_bucket")
    joined["score_bucket"] = joined["total_score"].map(_score_bucket)
    stats = _return_stats(joined, "score_bucket", big_up_threshold, SCORE_BUCKET_ORDER)
    return stats


def trend_probability_bucket_diagnostics(
    engine_output: pd.DataFrame,
    labels: pd.DataFrame,
) -> pd.DataFrame:
    """Bucket trend probability and compute realized trend-day rate."""

    joined = prepare_signal_label_frame(engine_output, labels)
    columns = ["trend_probability_bucket", "sample_count", "actual_trend_day_rate"]
    if joined.empty:
        return pd.DataFrame(columns=columns)
    joined["trend_probability_bucket"] = joined["trend_day_probability"].map(_trend_probability_bucket)
    grouped = joined.groupby("trend_probability_bucket", sort=False, observed=False)
    output = grouped.agg(
        sample_count=("market_return", "size"),
        actual_trend_day_rate=("trend_day_flag", "mean"),
    ).reset_index()
    return _ordered(output, "trend_probability_bucket", TREND_PROBABILITY_BUCKET_ORDER)[columns]


def factor_diagnostics(
    factors: pd.DataFrame,
    labels: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Compute per-factor diagnostics against realized market labels."""

    joined = prepare_factor_label_frame(factors, labels)
    if joined.empty:
        empty_summary = pd.DataFrame(
            columns=[
                "factor_name",
                "sample_count",
                "mean_directional_score",
                "corr_next_market_return",
                "corr_big_loss_day_flag",
                "corr_trend_day_flag",
                "big_loss_detection_score",
                "directional_relationship_strength",
                "recent_60d_corr_return",
                "recent_120d_corr_return",
            ]
        )
        empty_quintiles = pd.DataFrame(
            columns=["factor_name", "factor_quintile", "sample_count", "avg_next_market_return", "big_loss_day_rate"]
        )
        return {"summary": empty_summary, "quintiles": empty_quintiles}

    summary_rows: list[dict[str, Any]] = []
    quintile_frames: list[pd.DataFrame] = []
    for factor_name, frame in joined.groupby("factor_name", sort=True):
        ordered = frame.sort_values("date").copy()
        corr_return = _corr(ordered["directional_score"], ordered["market_return"])
        corr_big_loss = _corr(ordered["directional_score"], ordered["big_loss_day_flag"].astype(float))
        corr_trend = _corr(ordered["directional_score"], ordered["trend_day_flag"].astype(float))
        summary_rows.append(
            {
                "factor_name": factor_name,
                "sample_count": int(len(ordered)),
                "mean_directional_score": float(ordered["directional_score"].mean()),
                "corr_next_market_return": corr_return,
                "corr_big_loss_day_flag": corr_big_loss,
                "corr_trend_day_flag": corr_trend,
                "big_loss_detection_score": -corr_big_loss,
                "directional_relationship_strength": abs(corr_return),
                "recent_60d_corr_return": _recent_corr(ordered, 60),
                "recent_120d_corr_return": _recent_corr(ordered, 120),
            }
        )
        quintile_frames.append(_factor_quintiles(ordered, str(factor_name)))

    summary = pd.DataFrame(summary_rows).sort_values(
        ["big_loss_detection_score", "directional_relationship_strength"],
        ascending=[False, False],
    )
    quintiles = pd.concat(quintile_frames, ignore_index=True) if quintile_frames else pd.DataFrame()
    return {"summary": summary, "quintiles": quintiles}


def prepare_signal_label_frame(engine_output: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Join signal rows to same-date realized labels after validating dates."""

    required_scores = {"date", "total_score", "trend_day_probability"}
    required_labels = {"date", "market_return", "trend_day_flag", "big_loss_day_flag"}
    missing_scores = required_scores - set(engine_output.columns)
    missing_labels = required_labels - set(labels.columns)
    if missing_scores:
        raise ValueError(f"Engine output is missing: {sorted(missing_scores)}")
    if missing_labels:
        raise ValueError(f"Labels are missing: {sorted(missing_labels)}")

    scored = engine_output.copy()
    realized = labels.copy()
    scored["signal_date"] = pd.to_datetime(scored["date"]).dt.normalize()
    realized["market_result_date"] = pd.to_datetime(realized["date"]).dt.normalize()
    scored["final_bias"] = _final_bias(scored)
    joined = scored.merge(realized, left_on="signal_date", right_on="market_result_date", how="inner", suffixes=("", "_label"))
    if joined.empty:
        return joined
    if (joined["market_result_date"] < joined["signal_date"]).any():
        raise ValueError("Lookahead validation failed: market_result_date must be >= signal_date.")
    joined["date"] = joined["signal_date"]
    return joined


def prepare_factor_label_frame(factors: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    required_factors = {"date", "factor_name", "directional_score"}
    required_labels = {"date", "market_return", "trend_day_flag", "big_loss_day_flag"}
    missing_factors = required_factors - set(factors.columns)
    missing_labels = required_labels - set(labels.columns)
    if missing_factors:
        raise ValueError(f"Factors are missing: {sorted(missing_factors)}")
    if missing_labels:
        raise ValueError(f"Labels are missing: {sorted(missing_labels)}")

    prepared_factors = factors.copy()
    prepared_labels = labels.copy()
    prepared_factors["signal_date"] = pd.to_datetime(prepared_factors["date"]).dt.normalize()
    prepared_labels["market_result_date"] = pd.to_datetime(prepared_labels["date"]).dt.normalize()
    joined = prepared_factors.merge(
        prepared_labels,
        left_on="signal_date",
        right_on="market_result_date",
        how="inner",
        suffixes=("", "_label"),
    )
    if joined.empty:
        return joined
    if (joined["market_result_date"] < joined["signal_date"]).any():
        raise ValueError("Lookahead validation failed: factor diagnostics cannot use labels before the signal date.")
    joined["date"] = joined["signal_date"]
    return joined


def _return_stats(
    frame: pd.DataFrame,
    group_column: str,
    big_up_threshold: float,
    bucket_order: list[str] | None,
) -> pd.DataFrame:
    working = frame.copy()
    working["win"] = working["market_return"] > 0.0
    working["big_up_day"] = working["market_return"] >= big_up_threshold
    grouped = working.groupby(group_column, sort=False, observed=False)
    output = grouped.agg(
        sample_count=("market_return", "size"),
        mean_market_return=("market_return", "mean"),
        median_market_return=("market_return", "median"),
        win_rate=("win", "mean"),
        big_up_day_rate=("big_up_day", "mean"),
        big_loss_day_rate=("big_loss_day_flag", "mean"),
        trend_day_rate=("trend_day_flag", "mean"),
        max_loss=("market_return", "min"),
    ).reset_index()
    if bucket_order is not None:
        output = _ordered(output, group_column, bucket_order)
    return output


def _empty_return_stats(group_column: str) -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            group_column,
            "sample_count",
            "mean_market_return",
            "median_market_return",
            "win_rate",
            "big_up_day_rate",
            "big_loss_day_rate",
            "trend_day_rate",
            "max_loss",
        ]
    )


def _score_bucket(score: Any) -> str:
    value = float(score)
    if value <= -60:
        return "<=-60"
    if value <= -40:
        return "-60~-40"
    if value <= -20:
        return "-40~-20"
    if value <= 0:
        return "-20~0"
    if value < 20:
        return "0~20"
    if value < 40:
        return "20~40"
    if value < 60:
        return "40~60"
    return ">=60"


def _trend_probability_bucket(probability: Any) -> str:
    value = float(probability)
    if value < 20:
        return "0-20"
    if value < 40:
        return "20-40"
    if value < 60:
        return "40-60"
    if value < 80:
        return "60-80"
    return "80-100"


def _ordered(frame: pd.DataFrame, column: str, order: list[str]) -> pd.DataFrame:
    output = frame.copy()
    output[column] = pd.Categorical(output[column], categories=order, ordered=True)
    return output.sort_values(column).reset_index(drop=True)


def _final_bias(frame: pd.DataFrame) -> pd.Series:
    if "final_bias" in frame.columns:
        return frame["final_bias"].astype(str)
    if "bias_label" in frame.columns:
        return frame["bias_label"].astype(str)
    raise ValueError("Engine output must include final_bias or bias_label.")


def _corr(left: pd.Series, right: pd.Series) -> float:
    prepared = pd.DataFrame({"left": left, "right": right}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(prepared) < 3 or prepared["left"].nunique() < 2 or prepared["right"].nunique() < 2:
        return 0.0
    return float(prepared["left"].corr(prepared["right"]))


def _recent_corr(frame: pd.DataFrame, window: int) -> float:
    return _corr(frame.tail(window)["directional_score"], frame.tail(window)["market_return"])


def _factor_quintiles(frame: pd.DataFrame, factor_name: str) -> pd.DataFrame:
    working = frame.copy()
    if len(working) < 5:
        working["factor_quintile"] = "Q1"
    else:
        ranked = working["directional_score"].rank(method="first")
        working["factor_quintile"] = pd.qcut(ranked, q=5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
    output = (
        working.groupby("factor_quintile", sort=True, observed=False)
        .agg(
            sample_count=("market_return", "size"),
            avg_next_market_return=("market_return", "mean"),
            big_loss_day_rate=("big_loss_day_flag", "mean"),
        )
        .reset_index()
    )
    output.insert(0, "factor_name", factor_name)
    return output
