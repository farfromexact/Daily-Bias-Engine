"""Rule-based Daily Bias Engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from daily_bias_engine.features.base import FACTOR_COLUMNS, validate_factor_frame


@dataclass(frozen=True)
class DailyBiasEngine:
    """Weighted rule engine for daily market bias scoring."""

    weights: Mapping[str, float]
    groups: Mapping[str, str]
    risk_on_threshold: float = 30.0
    risk_off_threshold: float = -30.0
    trend_probability_intercept: float = 35.0
    trend_probability_slope: float = 55.0
    trend_probability_min: float = 5.0
    trend_probability_max: float = 95.0
    hard_risk_off_min_flags: int = 1
    hard_risk_off_factors: Mapping[str, float] | None = None

    @classmethod
    def from_yaml(
        cls,
        factor_weights_path: str | Path,
        thresholds_path: str | Path,
    ) -> "DailyBiasEngine":
        with Path(factor_weights_path).open("r", encoding="utf-8") as handle:
            weight_config = yaml.safe_load(handle) or {}
        with Path(thresholds_path).open("r", encoding="utf-8") as handle:
            threshold_config = yaml.safe_load(handle) or {}

        bias = threshold_config.get("bias", {})
        trend = threshold_config.get("trend_day_probability", {})
        risk_flags = threshold_config.get("risk_flags", {})
        return cls(
            weights=weight_config.get("weights", {}),
            groups=weight_config.get("groups", {}),
            risk_on_threshold=float(bias.get("risk_on", 30.0)),
            risk_off_threshold=float(bias.get("risk_off", -30.0)),
            trend_probability_intercept=float(trend.get("intercept", 35.0)),
            trend_probability_slope=float(trend.get("score_slope", 55.0)),
            trend_probability_min=float(trend.get("min", 5.0)),
            trend_probability_max=float(trend.get("max", 95.0)),
            hard_risk_off_min_flags=int(risk_flags.get("hard_risk_off_min_flags", 1)),
            hard_risk_off_factors=risk_flags.get("hard_risk_off_factors", {}),
        )

    def score(self, factor_daily: pd.DataFrame) -> pd.DataFrame:
        factors = validate_factor_frame(factor_daily)
        rows: list[dict[str, Any]] = []
        for date, daily in factors.groupby("date", sort=True):
            scored = daily.copy()
            scored["weight"] = scored["factor_name"].map(self.weights).fillna(1.0).astype(float)
            scored["group"] = scored["factor_name"].map(self.groups).fillna("ungrouped")
            scored["factor_score"] = scored["directional_score"] * 100.0
            scored["contribution"] = scored["factor_score"] * scored["weight"]

            weight_sum = scored["weight"].abs().sum()
            total_score = 0.0 if weight_sum == 0 else scored["contribution"].sum() / weight_sum
            total_score = float(np.clip(total_score, -100.0, 100.0))
            risk_flags = self._risk_flags(scored)
            label = self._label(total_score, risk_flags)
            trend_probability = self._trend_probability(total_score, risk_flags)
            trend_direction_bias = self._trend_direction_bias(total_score, label)
            confidence = self._confidence(total_score, risk_flags)
            sub_scores = self._sub_scores(scored)
            explanation = self._explanation(
                date,
                label,
                total_score,
                confidence,
                trend_probability,
                trend_direction_bias,
                risk_flags,
                scored,
                sub_scores,
            )
            rows.append(
                {
                    "date": pd.Timestamp(date).normalize(),
                    "total_score": total_score,
                    "bias_label": label,
                    "confidence": confidence,
                    "sub_scores": sub_scores,
                    "trend_day_probability": trend_probability,
                    "trend_direction_bias": trend_direction_bias,
                    "risk_flags_json": risk_flags,
                    "explanation": explanation,
                }
            )
        return pd.DataFrame(rows)

    def _label(self, total_score: float, risk_flags: list[dict[str, Any]]) -> str:
        if len(risk_flags) >= self.hard_risk_off_min_flags:
            return "Risk-Off"
        if total_score >= self.risk_on_threshold:
            return "Risk-On"
        if total_score <= self.risk_off_threshold:
            return "Risk-Off"
        return "Neutral"

    def _trend_probability(self, total_score: float, risk_flags: list[dict[str, Any]]) -> float:
        probability = self.trend_probability_intercept + (abs(total_score) / 100.0) * self.trend_probability_slope
        probability += min(len(risk_flags), 3) * 3.0
        return float(np.clip(probability, self.trend_probability_min, self.trend_probability_max))

    def _trend_direction_bias(self, total_score: float, label: str) -> str:
        if label == "Risk-Off" and total_score <= 0:
            return "down"
        if total_score >= self.risk_on_threshold:
            return "up"
        if total_score <= self.risk_off_threshold:
            return "down"
        return "unclear"

    @staticmethod
    def _confidence(total_score: float, risk_flags: list[dict[str, Any]]) -> float:
        flag_severity = max((abs(float(flag["factor_score"])) for flag in risk_flags), default=0.0)
        return float(np.clip(max(abs(total_score), flag_severity), 0.0, 100.0))

    def _risk_flags(self, scored: pd.DataFrame) -> list[dict[str, Any]]:
        thresholds = self.hard_risk_off_factors or {}
        flags: list[dict[str, Any]] = []
        for _, row in scored.iterrows():
            factor_name = str(row["factor_name"])
            if factor_name not in thresholds:
                continue
            threshold = float(thresholds[factor_name])
            factor_score = float(row["factor_score"])
            if factor_score <= threshold:
                flags.append(
                    {
                        "type": "hard_risk_off",
                        "factor_name": factor_name,
                        "group": str(row["group"]),
                        "factor_score": factor_score,
                        "threshold": threshold,
                    }
                )
        return flags

    @staticmethod
    def _sub_scores(scored: pd.DataFrame) -> dict[str, float]:
        output: dict[str, float] = {}
        for group, group_frame in scored.groupby("group", sort=True):
            weight_sum = group_frame["weight"].abs().sum()
            score = 0.0 if weight_sum == 0 else group_frame["contribution"].sum() / weight_sum
            output[str(group)] = float(np.clip(score, -100.0, 100.0))
        return output

    @staticmethod
    def _drivers(scored: pd.DataFrame, ascending: bool) -> list[dict[str, Any]]:
        sorted_frame = scored.sort_values("contribution", ascending=ascending).head(3)
        drivers: list[dict[str, Any]] = []
        for _, row in sorted_frame.iterrows():
            drivers.append(
                {
                    "factor_name": str(row["factor_name"]),
                    "group": str(row["group"]),
                    "factor_score": float(row["factor_score"]),
                    "contribution": float(row["contribution"]),
                    "raw_value": float(row["raw_value"]),
                    "zscore_value": float(row["zscore_value"]),
                }
            )
        return drivers

    @classmethod
    def _explanation(
        cls,
        date: pd.Timestamp,
        label: str,
        total_score: float,
        confidence: float,
        trend_probability: float,
        trend_direction_bias: str,
        risk_flags: list[dict[str, Any]],
        scored: pd.DataFrame,
        sub_scores: Mapping[str, float],
    ) -> dict[str, Any]:
        factor_records = []
        for _, row in scored.sort_values("factor_name").iterrows():
            factor_records.append(
                {
                    "factor_name": str(row["factor_name"]),
                    "group": str(row["group"]),
                    "raw_value": float(row["raw_value"]),
                    "zscore_value": float(row["zscore_value"]),
                    "directional_score": float(row["directional_score"]),
                    "factor_score": float(row["factor_score"]),
                    "weight": float(row["weight"]),
                    "contribution": float(row["contribution"]),
                    "data_date": pd.Timestamp(row["data_date"]).strftime("%Y-%m-%d"),
                }
            )
        return {
            "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            "bias_label": label,
            "total_score": float(total_score),
            "confidence": float(confidence),
            "trend_day_probability": float(trend_probability),
            "trend_direction_bias": trend_direction_bias,
            "sub_scores": dict(sub_scores),
            "risk_flags": risk_flags,
            "positive_drivers": cls._drivers(scored, ascending=False),
            "negative_drivers": cls._drivers(scored, ascending=True),
            "factors": factor_records,
            "factor_schema": FACTOR_COLUMNS,
        }
