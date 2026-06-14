"""Walk-forward factor weight diagnostics.

This module intentionally does not update ``configs/factor_weights.yaml``. It
generates shadow-mode diagnostics and recommendations that require manual
approval before any production change.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

from daily_bias_engine.features import validate_no_lookahead_contract
from daily_bias_engine.features.base import validate_factor_frame
from daily_bias_engine.pipeline import list_snapshots, run_pipeline_from_snapshot


ETF_MARGIN_FACTORS = ("etf_flow_proxy", "margin_balance_momentum")
RATES_FACTOR = "rates_change_5d"
YIELD_CURVE_FACTOR = "yield_curve_slope"
OVERSEAS_MOMENTUM_FACTOR = "overseas_market_momentum"
OVERSEAS_VOL_FACTOR = "overseas_volatility_pressure"


@dataclass(frozen=True)
class WeightOptimizerConfig:
    """Configuration for walk-forward weight diagnostics."""

    train_window: int = 252
    test_window: int = 21
    step: int = 21
    min_train_periods: int = 126
    rolling_ic_window: int = 60
    rolling_ic_min_periods: int = 20
    strong_signal_threshold: float = 0.35
    risk_high_threshold: float = 0.35
    risk_extreme_threshold: float = 0.70
    max_factor_weight: float = 0.25
    max_group_weight: float = 0.35
    rates_change_5d_max_weight: float = 0.05
    etf_margin_combined_max_weight: float = 0.15
    blended_current_weight: float = 0.60
    blended_optimized_weight: float = 0.40
    permutation_count: int = 30
    permutation_seed: int = 20260613
    stress_drawdown_threshold: float = -0.05


def load_weight_config(config_dir: Path | str) -> tuple[dict[str, float], dict[str, str]]:
    """Load current weights and factor groups from the project config."""

    path = Path(config_dir) / "factor_weights.yaml"
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    weights = {str(key): float(value) for key, value in (payload.get("weights") or {}).items()}
    groups = {str(key): str(value) for key, value in (payload.get("groups") or {}).items()}
    return weights, groups


def generate_weight_diagnostic_report(
    factors: pd.DataFrame,
    labels: pd.DataFrame,
    current_weights: Mapping[str, float],
    groups: Mapping[str, str],
    config: WeightOptimizerConfig | None = None,
    index_ohlcv: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Generate a no-overwrite, shadow-mode weight diagnostic report."""

    cfg = config or WeightOptimizerConfig()
    factor_daily = validate_no_lookahead_contract(validate_factor_frame(factors))
    factor_names = _ordered_factor_names(current_weights, factor_daily)
    availability = _factor_availability(factor_daily, factor_names)
    model = _prepare_model_frame(factor_daily, labels, factor_names)
    if len(model) < cfg.min_train_periods + 1:
        raise ValueError(
            f"Need at least {cfg.min_train_periods + 1} aligned observations for walk-forward diagnostics; "
            f"got {len(model)}."
        )

    current = _complete_weights(current_weights, factor_names)
    folds, oos_predictions, return_fold_weights, risk_fold_weights = _run_walk_forward(
        model=model,
        factor_daily=factor_daily,
        factor_names=factor_names,
        current_weights=current,
        groups=groups,
        availability=availability,
        cfg=cfg,
    )

    optimized_return = _fit_constrained_weights(
        train=model,
        train_factor_rows=factor_daily,
        factor_names=factor_names,
        current_weights=current,
        groups=groups,
        availability=availability,
        cfg=cfg,
        objective="return",
    )
    optimized_risk = _fit_constrained_weights(
        train=model,
        train_factor_rows=factor_daily,
        factor_names=factor_names,
        current_weights=current,
        groups=groups,
        availability=availability,
        cfg=cfg,
        objective="risk",
    )
    raw_blended = {
        factor: cfg.blended_current_weight * current.get(factor, 0.0)
        + cfg.blended_optimized_weight * optimized_return.get(factor, 0.0)
        for factor in factor_names
    }
    constrained_blended = _project_weights(raw_blended, factor_names, groups, cfg, availability)

    rolling_ic = _rolling_factor_ic(model, factor_names, cfg)
    factor_stability = _factor_stability(
        model=model,
        rolling_ic=rolling_ic,
        return_fold_weights=return_fold_weights,
        risk_fold_weights=risk_fold_weights,
        factor_names=factor_names,
        current_weights=current,
        optimized_return_weights=optimized_return,
        optimized_risk_weights=optimized_risk,
        constrained_blended_weights=constrained_blended,
    )

    oos = pd.DataFrame(oos_predictions).sort_values("date").reset_index(drop=True)
    full_return_score = _composite_score(model, optimized_return, factor_names)
    full_risk_score = _risk_score(model, optimized_risk, factor_names)
    model_with_full_scores = model.assign(return_score=full_return_score, risk_score=full_risk_score)
    oos_metrics = _aggregate_oos_metrics(oos, cfg)
    return_bucket = _return_bucket_analysis(oos, cfg)
    risk_bucket = _risk_bucket_analysis(oos, cfg)
    regime_diag, regime_factor_ic = _regime_diagnostics(
        model=model_with_full_scores,
        factor_names=factor_names,
        cfg=cfg,
        index_ohlcv=index_ohlcv,
    )
    leakage_checks = _leakage_checks(factor_daily, model, folds)
    permutation = _permutation_sanity_check(
        model,
        factor_daily,
        factor_names,
        current,
        groups,
        availability,
        cfg,
        real_folds=folds,
    )

    constraint_checks = {
        "current_weights": _constraint_check(current, groups, cfg, availability),
        "optimized_return_weights": _constraint_check(optimized_return, groups, cfg, availability),
        "optimized_risk_weights": _constraint_check(optimized_risk, groups, cfg, availability),
        "raw_blended_weights": _constraint_check(raw_blended, groups, cfg, availability),
        "constrained_blended_weights": _constraint_check(constrained_blended, groups, cfg, availability),
    }
    recommendation = _build_recommendation(
        oos_metrics=oos_metrics,
        factor_stability=factor_stability,
        constraint_checks=constraint_checks,
        cfg=cfg,
    )

    report = {
        "created_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "objective": "Shadow-mode walk-forward diagnostics; does not overwrite factor_weights.yaml.",
        "adoption_status": "not adopted until manually approved",
        "methodology": {
            "split": "strict chronological walk-forward",
            "normalization": "uses existing as-of directional_score; optimizer does not refit full-sample normalization",
            "return_score_target": "next-day market_return direction and magnitude",
            "risk_score_target": "big_loss_day_flag and risk-filter behavior",
            "full_history_note": "optimized weights fit on all visible history are full-history diagnostic only, not out-of-sample verified",
        },
        "config": _json_ready(cfg.__dict__),
        "constraints": _constraint_description(cfg),
        "factor_availability": _records_from_frame(availability),
        "current_weights": _json_ready(current),
        "optimized_return_weights": _json_ready(optimized_return),
        "optimized_risk_weights": _json_ready(optimized_risk),
        "optimized_weights": _json_ready(optimized_return),
        "raw_blended_weights": _json_ready(raw_blended),
        "constrained_blended_weights": _json_ready(constrained_blended),
        "blended_weights": _json_ready(constrained_blended),
        "constraint_checks": _json_ready(constraint_checks),
        "oos_summary": _json_ready(oos_metrics),
        "walk_forward_folds": _json_ready(folds),
        "factor_stability": _records_from_frame(factor_stability),
        "rolling_ic": _records_from_frame(rolling_ic),
        "bucket_analysis_return": _records_from_frame(return_bucket),
        "bucket_analysis_risk": _records_from_frame(risk_bucket),
        "regime_diagnostics": _json_ready(regime_diag),
        "regime_factor_ic": _records_from_frame(regime_factor_ic),
        "leakage_checks": _json_ready(leakage_checks),
        "permutation_sanity_check": _json_ready(permutation),
        "recommendation": _json_ready(recommendation),
    }
    return report


def save_weight_diagnostic_report(report: Mapping[str, Any], output_dir: Path | str) -> Path:
    """Write latest JSON/Markdown/CSV diagnostics."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    report_payload = _json_ready(dict(report))
    (root / "latest_weight_diagnostics.json").write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    (root / "latest_weight_diagnostics.md").write_text(_markdown_report(report_payload), encoding="utf-8")

    _write_csv(root / "walk_forward_folds.csv", _fold_rows(report_payload.get("walk_forward_folds", [])))
    _write_csv(root / "factor_stability.csv", report_payload.get("factor_stability", []))
    _write_csv(root / "bucket_analysis_return.csv", report_payload.get("bucket_analysis_return", []))
    _write_csv(root / "bucket_analysis_risk.csv", report_payload.get("bucket_analysis_risk", []))
    _write_csv(root / "regime_factor_ic.csv", report_payload.get("regime_factor_ic", []))

    recommendation = {
        "note": "Review only. Do not copy blindly; this file is not loaded by the engine.",
        "adoption_status": report_payload.get("adoption_status"),
        "current_weights": report_payload.get("current_weights", {}),
        "optimized_return_weights": report_payload.get("optimized_return_weights", {}),
        "optimized_risk_weights": report_payload.get("optimized_risk_weights", {}),
        "raw_blended_weights": report_payload.get("raw_blended_weights", {}),
        "constrained_blended_weights": report_payload.get("constrained_blended_weights", {}),
        "constraint_checks": report_payload.get("constraint_checks", {}),
        "recommendation": report_payload.get("recommendation", {}),
    }
    (root / "recommended_weights.yaml").write_text(
        yaml.safe_dump(_json_ready(recommendation), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return root


def _run_walk_forward(
    model: pd.DataFrame,
    factor_daily: pd.DataFrame,
    factor_names: Sequence[str],
    current_weights: Mapping[str, float],
    groups: Mapping[str, str],
    availability: pd.DataFrame,
    cfg: WeightOptimizerConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    folds: list[dict[str, Any]] = []
    predictions: list[dict[str, Any]] = []
    return_fold_weights: list[dict[str, Any]] = []
    risk_fold_weights: list[dict[str, Any]] = []

    for fold_index, split in enumerate(_walk_forward_splits(model, cfg)):
        train = model.iloc[split["train_start_idx"] : split["train_end_idx"] + 1].copy()
        test = model.iloc[split["test_start_idx"] : split["test_end_idx"] + 1].copy()
        train_factor_rows = _factor_rows_for_dates(factor_daily, train["date"])
        return_weights = _fit_constrained_weights(
            train,
            train_factor_rows,
            factor_names,
            current_weights,
            groups,
            availability,
            cfg,
            objective="return",
        )
        risk_weights = _fit_constrained_weights(
            train,
            train_factor_rows,
            factor_names,
            current_weights,
            groups,
            availability,
            cfg,
            objective="risk",
        )
        return_score = _composite_score(test, return_weights, factor_names)
        risk_score = _risk_score(test, risk_weights, factor_names)
        metrics = _fold_metrics(test, return_score, risk_score, cfg)
        fold = {
            "fold": fold_index,
            "train_start": _date_text(train["date"].iloc[0]),
            "train_end": _date_text(train["date"].iloc[-1]),
            "test_start": _date_text(test["date"].iloc[0]),
            "test_end": _date_text(test["date"].iloc[-1]),
            "sample_count": int(len(test)),
            "return_weights": return_weights,
            "risk_weights": risk_weights,
            **metrics,
        }
        folds.append(fold)
        return_fold_weights.append({"fold": fold_index, **return_weights})
        risk_fold_weights.append({"fold": fold_index, **risk_weights})
        for row_index, row in test.reset_index(drop=True).iterrows():
            predictions.append(
                {
                    "fold": fold_index,
                    "date": row["date"],
                    "market_return": float(row["market_return"]),
                    "big_loss_day_flag": bool(row["big_loss_day_flag"]),
                    "return_score": float(return_score.iloc[row_index]),
                    "risk_score": float(risk_score.iloc[row_index]),
                }
            )
    return folds, predictions, return_fold_weights, risk_fold_weights


def _prepare_model_frame(factors: pd.DataFrame, labels: pd.DataFrame, factor_names: Sequence[str]) -> pd.DataFrame:
    labels_required = {"date", "market_return"}
    missing = labels_required - set(labels.columns)
    if missing:
        raise ValueError(f"Labels frame is missing columns: {sorted(missing)}")

    factor_pivot = (
        factors.pivot_table(index="date", columns="factor_name", values="directional_score", aggfunc="mean")
        .sort_index()
        .copy()
    )
    for factor in factor_names:
        if factor not in factor_pivot.columns:
            factor_pivot[factor] = 0.0
    factor_pivot = factor_pivot[list(factor_names)].fillna(0.0)

    target = labels.copy()
    target["date"] = pd.to_datetime(target["date"]).dt.normalize()
    target["market_return"] = pd.to_numeric(target["market_return"], errors="coerce")
    if "big_loss_day_flag" not in target.columns:
        target["big_loss_day_flag"] = False
    target["big_loss_day_flag"] = target["big_loss_day_flag"].fillna(False).astype(bool)
    target = target[["date", "market_return", "big_loss_day_flag"]].dropna(subset=["market_return"])

    model = factor_pivot.reset_index().merge(target, on="date", how="inner").sort_values("date")
    model["cum_return_proxy"] = (1.0 + model["market_return"].fillna(0.0)).cumprod()
    return model.reset_index(drop=True)


def _walk_forward_splits(model: pd.DataFrame, cfg: WeightOptimizerConfig) -> list[dict[str, int]]:
    n_obs = len(model)
    splits: list[dict[str, int]] = []
    test_start = cfg.min_train_periods
    while test_start < n_obs:
        train_start = max(0, test_start - cfg.train_window)
        train_end = test_start - 1
        test_end = min(n_obs - 1, test_start + cfg.test_window - 1)
        if train_end >= train_start and test_end >= test_start:
            splits.append(
                {
                    "train_start_idx": train_start,
                    "train_end_idx": train_end,
                    "test_start_idx": test_start,
                    "test_end_idx": test_end,
                }
            )
        test_start += cfg.step
    if not splits:
        raise ValueError("No walk-forward folds could be created with the requested windows.")
    return splits


def _fit_constrained_weights(
    train: pd.DataFrame,
    train_factor_rows: pd.DataFrame,
    factor_names: Sequence[str],
    current_weights: Mapping[str, float],
    groups: Mapping[str, str],
    availability: pd.DataFrame,
    cfg: WeightOptimizerConfig,
    objective: str,
) -> dict[str, float]:
    if objective == "risk":
        scores = _training_risk_scores(train, factor_names, cfg)
    else:
        scores = _training_return_scores(train, factor_names, cfg)
    local_availability = _availability_with_train_window(availability, train_factor_rows, factor_names)
    if not any(value > 0 for value in scores.values()):
        if objective == "risk":
            scores = {factor: 1.0 for factor in factor_names}
        else:
            scores = {factor: max(float(current_weights.get(factor, 0.0)), 0.0) for factor in factor_names}
    return _project_weights(scores, factor_names, groups, cfg, local_availability)


def _training_return_scores(train: pd.DataFrame, factor_names: Sequence[str], cfg: WeightOptimizerConfig) -> dict[str, float]:
    target = pd.to_numeric(train["market_return"], errors="coerce").fillna(0.0)
    scores: dict[str, float] = {}
    for factor in factor_names:
        signal = pd.to_numeric(train[factor], errors="coerce").fillna(0.0)
        ic = _safe_corr(signal, target)
        hit_rate = _direction_hit_rate(signal, target)
        strong = signal.abs() >= cfg.strong_signal_threshold
        strong_hit = _direction_hit_rate(signal[strong], target[strong]) if strong.any() else None
        ic_component = max(ic or 0.0, 0.0)
        hit_component = 0.0 if hit_rate is None else max(hit_rate - 0.5, 0.0) * 2.0
        strong_component = 0.0 if strong_hit is None else max(strong_hit - 0.5, 0.0) * 2.0
        scores[factor] = float(max(0.65 * ic_component + 0.25 * hit_component + 0.10 * strong_component, 0.0))
    return scores


def _training_risk_scores(train: pd.DataFrame, factor_names: Sequence[str], cfg: WeightOptimizerConfig) -> dict[str, float]:
    big_loss = train["big_loss_day_flag"].astype(bool)
    target = big_loss.astype(float)
    scores: dict[str, float] = {}
    for factor in factor_names:
        risk_signal = -pd.to_numeric(train[factor], errors="coerce").fillna(0.0)
        corr = _safe_corr(risk_signal, target)
        high_risk = risk_signal >= cfg.risk_high_threshold
        if big_loss.any():
            recall = float((high_risk & big_loss).sum() / big_loss.sum())
        else:
            recall = 0.0
        precision = float((high_risk & big_loss).sum() / high_risk.sum()) if high_risk.any() else 0.0
        negative_return_component = max(-(train.loc[high_risk, "market_return"].mean() if high_risk.any() else 0.0), 0.0)
        scores[factor] = float(max(0.45 * max(corr or 0.0, 0.0) + 0.35 * recall + 0.15 * precision + 0.05 * negative_return_component, 0.0))
    return scores


def _project_weights(
    raw_scores: Mapping[str, float],
    factor_names: Sequence[str],
    groups: Mapping[str, str],
    cfg: WeightOptimizerConfig,
    availability: pd.DataFrame,
) -> dict[str, float]:
    allowed = _allowed_map(availability, factor_names)
    weights = {factor: 0.0 for factor in factor_names}
    desired = {factor: max(float(raw_scores.get(factor, 0.0)), 0.0) if allowed.get(factor, True) else 0.0 for factor in factor_names}
    remaining = 1.0

    for _ in range(800):
        if remaining <= 1e-12:
            break
        capacities = {factor: _capacity_for_factor(factor, weights, groups, cfg, allowed) for factor in factor_names}
        eligible = [factor for factor in factor_names if capacities[factor] > 1e-12]
        if not eligible:
            break
        preference_sum = sum(desired[factor] for factor in eligible)
        if preference_sum <= 1e-12:
            preference = {factor: capacities[factor] for factor in eligible}
            preference_sum = sum(preference.values())
        else:
            preference = {factor: desired[factor] for factor in eligible}

        added = 0.0
        for factor in sorted(eligible, key=lambda item: preference[item], reverse=True):
            capacity = _capacity_for_factor(factor, weights, groups, cfg, allowed)
            if capacity <= 1e-12 or remaining <= 1e-12:
                continue
            addition = min(capacity, remaining * preference[factor] / preference_sum)
            if addition <= 1e-14:
                continue
            weights[factor] += addition
            remaining -= addition
            added += addition
        if added <= 1e-14:
            capacities = {factor: _capacity_for_factor(factor, weights, groups, cfg, allowed) for factor in factor_names}
            eligible = [factor for factor in factor_names if capacities[factor] > 1e-12]
            if not eligible:
                break
            factor = max(eligible, key=lambda item: capacities[item])
            addition = min(remaining, capacities[factor])
            weights[factor] += addition
            remaining -= addition

    total = sum(weights.values())
    if abs(total - 1.0) > 1e-8:
        capacities = {factor: _capacity_for_factor(factor, weights, groups, cfg, allowed) for factor in factor_names}
        for factor in sorted(factor_names, key=lambda item: capacities[item], reverse=True):
            if remaining <= 1e-10:
                break
            addition = min(remaining, capacities[factor])
            if addition > 0:
                weights[factor] += addition
                remaining -= addition
    return {factor: float(0.0 if abs(value) < 1e-12 else value) for factor, value in weights.items()}


def _capacity_for_factor(
    factor: str,
    weights: Mapping[str, float],
    groups: Mapping[str, str],
    cfg: WeightOptimizerConfig,
    allowed: Mapping[str, bool],
) -> float:
    if not allowed.get(factor, True):
        return 0.0
    factor_cap = cfg.max_factor_weight
    if factor == RATES_FACTOR:
        factor_cap = min(factor_cap, cfg.rates_change_5d_max_weight)
    capacity = factor_cap - float(weights.get(factor, 0.0))

    group = groups.get(factor, "ungrouped")
    group_sum = sum(float(value) for item, value in weights.items() if groups.get(item, "ungrouped") == group)
    capacity = min(capacity, cfg.max_group_weight - group_sum)

    if factor in ETF_MARGIN_FACTORS:
        basket_sum = sum(float(weights.get(item, 0.0)) for item in ETF_MARGIN_FACTORS)
        capacity = min(capacity, cfg.etf_margin_combined_max_weight - basket_sum)
    return max(float(capacity), 0.0)


def _fold_metrics(test: pd.DataFrame, return_score: pd.Series, risk_score: pd.Series, cfg: WeightOptimizerConfig) -> dict[str, Any]:
    target = pd.to_numeric(test["market_return"], errors="coerce").fillna(0.0)
    big_loss = test["big_loss_day_flag"].astype(bool)
    strong = return_score.abs() >= cfg.strong_signal_threshold
    strong_count = int(strong.sum())
    strong_hit = _direction_hit_rate(return_score[strong], target[strong]) if strong_count else None
    high_risk = risk_score >= cfg.risk_high_threshold
    tp = int((high_risk & big_loss).sum())
    fp = int((high_risk & ~big_loss).sum())
    tn = int((~high_risk & ~big_loss).sum())
    fn = int((~high_risk & big_loss).sum())
    return {
        "return_score_test_ic": _safe_corr(return_score, target),
        "direction_hit_rate": _direction_hit_rate(return_score, target),
        "direction_hit_rate_ci": _binomial_ci_from_hits(return_score, target),
        "strong_signal_count": strong_count,
        "strong_signal_hit_rate": strong_hit,
        "strong_signal_hit_rate_ci": _binomial_ci_from_hits(return_score[strong], target[strong]) if strong_count else None,
        "strong_signal_avg_return": float(target[strong].mean()) if strong_count else None,
        "big_loss_count": int(big_loss.sum()),
        "TP": tp,
        "FP": fp,
        "TN": tn,
        "FN": fn,
        "big_loss_capture_rate": _safe_div(tp, tp + fn),
        "big_loss_capture_rate_ci": _wilson_ci(tp, tp + fn) if (tp + fn) else None,
        "big_loss_precision_rate": _safe_div(tp, tp + fp),
        "false_positive_rate": _safe_div(fp, fp + tn),
        "big_loss_avoidance_rate": _safe_div(tn, tn + fp),
        "missed_big_loss_count": fn,
        "average_next_day_return_when_risk_score_high": float(target[high_risk].mean()) if high_risk.any() else None,
        "max_next_day_loss_when_risk_score_low": float(target[~high_risk].min()) if (~high_risk).any() else None,
        "max_drawdown_proxy": _max_drawdown_proxy(return_score, target, cfg),
    }


def _aggregate_oos_metrics(oos: pd.DataFrame, cfg: WeightOptimizerConfig) -> dict[str, Any]:
    if oos.empty:
        return {}
    return_score = pd.to_numeric(oos["return_score"], errors="coerce").fillna(0.0)
    risk_score = pd.to_numeric(oos["risk_score"], errors="coerce").fillna(0.0)
    target = pd.to_numeric(oos["market_return"], errors="coerce").fillna(0.0)
    big_loss = oos["big_loss_day_flag"].astype(bool)
    strong = return_score.abs() >= cfg.strong_signal_threshold
    high_risk = risk_score >= cfg.risk_high_threshold
    tp = int((high_risk & big_loss).sum())
    fp = int((high_risk & ~big_loss).sum())
    tn = int((~high_risk & ~big_loss).sum())
    fn = int((~high_risk & big_loss).sum())
    ic_series = _fold_ic_series(oos)
    return {
        "sample_count": int(len(oos)),
        "return_score_test_ic": _safe_corr(return_score, target),
        "return_score_ic_mean": float(ic_series.mean()) if not ic_series.empty else None,
        "return_score_ic_std": float(ic_series.std(ddof=0)) if len(ic_series) > 1 else 0.0,
        "return_score_ic_t_stat": _t_stat(ic_series),
        "direction_hit_rate": _direction_hit_rate(return_score, target),
        "direction_hit_rate_ci": _binomial_ci_from_hits(return_score, target),
        "long_side_avg_return": float(target[return_score > cfg.strong_signal_threshold].mean()) if (return_score > cfg.strong_signal_threshold).any() else None,
        "short_risk_off_avg_return": float(target[return_score < -cfg.strong_signal_threshold].mean()) if (return_score < -cfg.strong_signal_threshold).any() else None,
        "strong_signal_count": int(strong.sum()),
        "strong_signal_hit_rate": _direction_hit_rate(return_score[strong], target[strong]) if strong.any() else None,
        "strong_signal_hit_rate_ci": _binomial_ci_from_hits(return_score[strong], target[strong]) if strong.any() else None,
        "strong_signal_avg_return": float(target[strong].mean()) if strong.any() else None,
        "max_drawdown_proxy": _max_drawdown_proxy(return_score, target, cfg),
        "TP": tp,
        "FP": fp,
        "TN": tn,
        "FN": fn,
        "big_loss_count": int(big_loss.sum()),
        "big_loss_capture_rate": _safe_div(tp, tp + fn),
        "big_loss_capture_rate_ci": _wilson_ci(tp, tp + fn) if (tp + fn) else None,
        "big_loss_precision_rate": _safe_div(tp, tp + fp),
        "false_positive_rate": _safe_div(fp, fp + tn),
        "big_loss_avoidance_rate": _safe_div(tn, tn + fp),
        "missed_big_loss_count": fn,
        "average_next_day_return_when_risk_score_high": float(target[high_risk].mean()) if high_risk.any() else None,
        "max_next_day_loss_when_risk_score_low": float(target[~high_risk].min()) if (~high_risk).any() else None,
    }


def _composite_score(frame: pd.DataFrame, weights: Mapping[str, float], factor_names: Sequence[str]) -> pd.Series:
    weight_values = pd.Series({factor: float(weights.get(factor, 0.0)) for factor in factor_names})
    weight_sum = weight_values.abs().sum()
    if weight_sum <= 0:
        return pd.Series(0.0, index=frame.index)
    matrix = frame[list(factor_names)].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    return matrix.dot(weight_values) / weight_sum


def _risk_score(frame: pd.DataFrame, weights: Mapping[str, float], factor_names: Sequence[str]) -> pd.Series:
    return -_composite_score(frame, weights, factor_names)


def _return_bucket_analysis(oos: pd.DataFrame, cfg: WeightOptimizerConfig) -> pd.DataFrame:
    if oos.empty:
        return pd.DataFrame()
    frame = oos.copy()
    frame["return_bucket"] = pd.cut(
        frame["return_score"],
        bins=[-np.inf, -0.70, -0.35, 0.35, 0.70, np.inf],
        labels=["score <= -0.70", "-0.70 < score <= -0.35", "-0.35 < score < 0.35", "0.35 <= score < 0.70", "score >= 0.70"],
        right=True,
    )
    rows: list[dict[str, Any]] = []
    for bucket, group in frame.groupby("return_bucket", observed=False, sort=True):
        returns = pd.to_numeric(group["market_return"], errors="coerce").fillna(0.0)
        rows.append(
            {
                "bucket": str(bucket),
                "sample_count": int(len(group)),
                "next_day_avg_return": float(returns.mean()) if len(group) else None,
                "next_day_median_return": float(returns.median()) if len(group) else None,
                "direction_hit_rate": _direction_hit_rate(group["return_score"], returns),
                "direction_hit_rate_ci": _binomial_ci_from_hits(group["return_score"], returns),
                "worst_next_day_return": float(returns.min()) if len(group) else None,
                "best_next_day_return": float(returns.max()) if len(group) else None,
                "big_loss_rate": float(group["big_loss_day_flag"].mean()) if len(group) else None,
            }
        )
    return pd.DataFrame(rows)


def _risk_bucket_analysis(oos: pd.DataFrame, cfg: WeightOptimizerConfig) -> pd.DataFrame:
    if oos.empty:
        return pd.DataFrame()
    frame = oos.copy()
    frame["risk_bucket"] = pd.cut(
        frame["risk_score"],
        bins=[-np.inf, 0.0, cfg.risk_high_threshold, cfg.risk_extreme_threshold, np.inf],
        labels=["low risk", "neutral risk", "high risk", "extreme risk"],
        right=False,
    )
    rows: list[dict[str, Any]] = []
    for bucket, group in frame.groupby("risk_bucket", observed=False, sort=True):
        returns = pd.to_numeric(group["market_return"], errors="coerce").fillna(0.0)
        big_loss = group["big_loss_day_flag"].astype(bool)
        is_alarm = str(bucket) in {"high risk", "extreme risk"}
        rows.append(
            {
                "bucket": str(bucket),
                "sample_count": int(len(group)),
                "big_loss_rate": float(big_loss.mean()) if len(group) else None,
                "avg_next_day_return": float(returns.mean()) if len(group) else None,
                "worst_next_day_return": float(returns.min()) if len(group) else None,
                "false_alarm_count": int((~big_loss).sum()) if is_alarm else 0,
                "missed_big_loss_count": int(big_loss.sum()) if not is_alarm else 0,
            }
        )
    return pd.DataFrame(rows)


def _regime_diagnostics(
    model: pd.DataFrame,
    factor_names: Sequence[str],
    cfg: WeightOptimizerConfig,
    index_ohlcv: pd.DataFrame | None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    frame = model.copy()
    frame = frame.merge(_regime_frame(frame, cfg, index_ohlcv), on="date", how="left")
    regime_columns = ["trend_regime", "volatility_regime", "stress_regime", "overseas_regime"]
    factor_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for column in regime_columns:
        summary[column] = []
        for regime, group in frame.groupby(column, dropna=False, sort=True):
            if group.empty:
                continue
            return_perf = _score_performance(group["return_score"], group["market_return"], cfg)
            risk_perf = _risk_performance(group["risk_score"], group["market_return"], group["big_loss_day_flag"], cfg)
            factor_stats = []
            for factor in factor_names:
                ic = _safe_corr(group[factor], group["market_return"])
                hit = _direction_hit_rate(group[factor], group["market_return"])
                failed = ic is None or ic <= 0 or hit is None or hit <= 0.50
                effective = ic is not None and ic > 0.03 and hit is not None and hit > 0.52
                item = {
                    "regime_type": column,
                    "regime": str(regime),
                    "factor_name": factor,
                    "sample_count": int(len(group)),
                    "ic": ic,
                    "hit_rate": hit,
                    "failed_in_regime": failed,
                    "effective_in_regime": effective,
                }
                factor_rows.append(item)
                factor_stats.append(item)
            summary[column].append(
                {
                    "regime": str(regime),
                    "sample_count": int(len(group)),
                    "return_score_performance": return_perf,
                    "risk_score_performance": risk_perf,
                    "failed_factors": [item["factor_name"] for item in factor_stats if item["failed_in_regime"]],
                    "regime_effective_factors": [item["factor_name"] for item in factor_stats if item["effective_in_regime"]],
                }
            )
    return summary, pd.DataFrame(factor_rows)


def _regime_frame(model: pd.DataFrame, cfg: WeightOptimizerConfig, index_ohlcv: pd.DataFrame | None) -> pd.DataFrame:
    if index_ohlcv is not None and not index_ohlcv.empty and {"date", "close"}.issubset(index_ohlcv.columns):
        price = index_ohlcv.copy()
        price["date"] = pd.to_datetime(price["date"]).dt.normalize()
        if "symbol" in price.columns:
            price = price.sort_values(["symbol", "date"]).groupby("date", sort=True)["close"].mean().reset_index()
        else:
            price = price.groupby("date", sort=True)["close"].mean().reset_index()
        close = pd.to_numeric(price["close"], errors="coerce").ffill()
        regimes = pd.DataFrame({"date": price["date"], "close": close})
        regimes = model[["date"]].merge(regimes, on="date", how="left")
        regimes["close"] = regimes["close"].ffill().fillna(model["cum_return_proxy"])
    else:
        regimes = model[["date", "cum_return_proxy"]].rename(columns={"cum_return_proxy": "close"}).copy()

    close = pd.to_numeric(regimes["close"], errors="coerce").ffill().fillna(1.0)
    ma20 = close.rolling(20, min_periods=5).mean()
    ma60 = close.rolling(60, min_periods=10).mean()
    regimes["trend_regime"] = np.select(
        [close > ma20, close < ma60],
        ["uptrend", "downtrend"],
        default="sideways",
    )
    returns = close.pct_change().fillna(0.0)
    rv20 = returns.rolling(20, min_periods=5).std(ddof=0) * math.sqrt(252)
    low_q = rv20.expanding(min_periods=20).quantile(0.33)
    high_q = rv20.expanding(min_periods=20).quantile(0.67)
    regimes["volatility_regime"] = np.select(
        [rv20 <= low_q, rv20 >= high_q],
        ["low realized volatility", "high realized volatility"],
        default="normal realized volatility",
    )
    drawdown = close / close.rolling(60, min_periods=5).max() - 1.0
    regimes["stress_regime"] = np.where(drawdown <= cfg.stress_drawdown_threshold, "drawdown > threshold", "no stress")

    overseas_signal = pd.to_numeric(model.get(OVERSEAS_MOMENTUM_FACTOR, 0.0), errors="coerce").fillna(0.0) - pd.to_numeric(
        model.get(OVERSEAS_VOL_FACTOR, 0.0), errors="coerce"
    ).fillna(0.0) * 0.5
    regimes["overseas_regime"] = np.select(
        [overseas_signal >= 0.35, overseas_signal <= -0.35],
        ["overseas risk-on", "overseas risk-off"],
        default="neutral",
    )
    return regimes[["date", "trend_regime", "volatility_regime", "stress_regime", "overseas_regime"]]


def _score_performance(score: pd.Series, returns: pd.Series, cfg: WeightOptimizerConfig) -> dict[str, Any]:
    strong = score.abs() >= cfg.strong_signal_threshold
    return {
        "sample_count": int(len(score)),
        "ic": _safe_corr(score, returns),
        "direction_hit_rate": _direction_hit_rate(score, returns),
        "strong_signal_count": int(strong.sum()),
        "strong_signal_hit_rate": _direction_hit_rate(score[strong], returns[strong]) if strong.any() else None,
        "avg_return": float(pd.to_numeric(returns, errors="coerce").mean()) if len(score) else None,
    }


def _risk_performance(score: pd.Series, returns: pd.Series, big_loss: pd.Series, cfg: WeightOptimizerConfig) -> dict[str, Any]:
    high = score >= cfg.risk_high_threshold
    big_loss_bool = big_loss.astype(bool)
    tp = int((high & big_loss_bool).sum())
    fp = int((high & ~big_loss_bool).sum())
    tn = int((~high & ~big_loss_bool).sum())
    fn = int((~high & big_loss_bool).sum())
    return {
        "TP": tp,
        "FP": fp,
        "TN": tn,
        "FN": fn,
        "big_loss_capture_rate": _safe_div(tp, tp + fn),
        "precision": _safe_div(tp, tp + fp),
        "false_positive_rate": _safe_div(fp, fp + tn),
        "big_loss_avoidance_rate": _safe_div(tn, tn + fp),
        "avg_return_when_high_risk": float(pd.to_numeric(returns[high], errors="coerce").mean()) if high.any() else None,
    }


def _rolling_factor_ic(model: pd.DataFrame, factor_names: Sequence[str], cfg: WeightOptimizerConfig) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    target = pd.to_numeric(model["market_return"], errors="coerce").fillna(0.0)
    risk_target = model["big_loss_day_flag"].astype(float)
    for factor in factor_names:
        signal = pd.to_numeric(model[factor], errors="coerce").fillna(0.0)
        risk_signal = -signal
        for end_idx in range(len(model)):
            start_idx = max(0, end_idx - cfg.rolling_ic_window + 1)
            sample_count = end_idx - start_idx + 1
            return_ic = None
            risk_ic = None
            if sample_count >= cfg.rolling_ic_min_periods:
                return_ic = _safe_corr(signal.iloc[start_idx : end_idx + 1], target.iloc[start_idx : end_idx + 1])
                risk_ic = _safe_corr(risk_signal.iloc[start_idx : end_idx + 1], risk_target.iloc[start_idx : end_idx + 1])
            rows.append(
                {
                    "date": model["date"].iloc[end_idx],
                    "factor_name": factor,
                    "return_rolling_ic": return_ic,
                    "risk_rolling_ic": risk_ic,
                    "sample_count": sample_count,
                }
            )
    return pd.DataFrame(rows)


def _factor_stability(
    model: pd.DataFrame,
    rolling_ic: pd.DataFrame,
    return_fold_weights: Sequence[Mapping[str, Any]],
    risk_fold_weights: Sequence[Mapping[str, Any]],
    factor_names: Sequence[str],
    current_weights: Mapping[str, float],
    optimized_return_weights: Mapping[str, float],
    optimized_risk_weights: Mapping[str, float],
    constrained_blended_weights: Mapping[str, float],
) -> pd.DataFrame:
    return_weight_frame = pd.DataFrame(return_fold_weights)
    risk_weight_frame = pd.DataFrame(risk_fold_weights)
    rows: list[dict[str, Any]] = []
    risk_target = model["big_loss_day_flag"].astype(float)
    for factor in factor_names:
        return_ic_values = pd.to_numeric(
            rolling_ic.loc[rolling_ic["factor_name"] == factor, "return_rolling_ic"], errors="coerce"
        ).dropna()
        risk_ic_values = pd.to_numeric(
            rolling_ic.loc[rolling_ic["factor_name"] == factor, "risk_rolling_ic"], errors="coerce"
        ).dropna()
        return_ic_mean = float(return_ic_values.mean()) if not return_ic_values.empty else None
        return_ic_abs_mean = float(return_ic_values.abs().mean()) if not return_ic_values.empty else None
        return_ic_vol = float(return_ic_values.std(ddof=0)) if len(return_ic_values) > 1 else 0.0
        risk_ic_mean = float(risk_ic_values.mean()) if not risk_ic_values.empty else None
        risk_ic_vol = float(risk_ic_values.std(ddof=0)) if len(risk_ic_values) > 1 else 0.0
        return_predictive = 0.0 if return_ic_mean is None or return_ic_mean <= 0 else return_ic_mean / (return_ic_vol + 1e-9)
        risk_predictive = 0.0 if risk_ic_mean is None or risk_ic_mean <= 0 else risk_ic_mean / (risk_ic_vol + 1e-9)
        return_weight_values = (
            pd.to_numeric(return_weight_frame[factor], errors="coerce").dropna()
            if factor in return_weight_frame.columns
            else pd.Series(dtype=float)
        )
        risk_weight_values = (
            pd.to_numeric(risk_weight_frame[factor], errors="coerce").dropna()
            if factor in risk_weight_frame.columns
            else pd.Series(dtype=float)
        )
        rows.append(
            {
                "factor_name": factor,
                "return_ic_mean": return_ic_mean,
                "return_ic_abs_mean": return_ic_abs_mean,
                "return_ic_volatility": return_ic_vol,
                "return_ic_t_stat": _t_stat(return_ic_values),
                "abs_stability_score": (return_ic_abs_mean or 0.0) / (return_ic_vol + 1e-9),
                "return_predictive_score": return_predictive,
                "risk_predictive_score": risk_predictive,
                "risk_ic_mean": risk_ic_mean,
                "risk_ic_volatility": risk_ic_vol,
                "weight_volatility": float(return_weight_values.std(ddof=0)) if len(return_weight_values) > 1 else 0.0,
                "risk_weight_volatility": float(risk_weight_values.std(ddof=0)) if len(risk_weight_values) > 1 else 0.0,
                "average_return_fold_weight": float(return_weight_values.mean()) if not return_weight_values.empty else 0.0,
                "average_risk_fold_weight": float(risk_weight_values.mean()) if not risk_weight_values.empty else 0.0,
                "current_weight": float(current_weights.get(factor, 0.0)),
                "optimized_return_weight": float(optimized_return_weights.get(factor, 0.0)),
                "optimized_risk_weight": float(optimized_risk_weights.get(factor, 0.0)),
                "constrained_blended_weight": float(constrained_blended_weights.get(factor, 0.0)),
                "data_big_loss_corr": _safe_corr(-pd.to_numeric(model[factor], errors="coerce").fillna(0.0), risk_target),
            }
        )
    output = pd.DataFrame(rows)
    output["final_stability_rank"] = (
        (output["return_predictive_score"].fillna(0.0) * 0.65 + output["risk_predictive_score"].fillna(0.0) * 0.35)
        .rank(method="min", ascending=False)
        .astype(int)
    )
    return output.sort_values(["final_stability_rank", "factor_name"]).reset_index(drop=True)


def _factor_availability(factors: pd.DataFrame, factor_names: Sequence[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for factor in factor_names:
        subset = factors[factors["factor_name"] == factor]
        raw_values = pd.to_numeric(subset.get("raw_value", pd.Series(dtype=float)), errors="coerce").dropna()
        data_available = not subset.empty and not raw_values.empty
        if factor == YIELD_CURVE_FACTOR:
            data_available = data_available and bool((raw_values.abs() > 1e-12).any())
        rows.append(
            {
                "factor_name": factor,
                "data_available": bool(data_available),
                "data_source": str(subset["data_source"].dropna().iloc[-1]) if not subset.empty and "data_source" in subset.columns else "missing",
                "observation_count": int(len(subset)),
                "nonzero_raw_count": int((raw_values.abs() > 1e-12).sum()) if not raw_values.empty else 0,
                "allowed_in_optimizer": bool(data_available),
                "availability_reason": "available" if data_available else "missing or zero real data",
            }
        )
    return pd.DataFrame(rows)


def _availability_with_train_window(availability: pd.DataFrame, train_factor_rows: pd.DataFrame, factor_names: Sequence[str]) -> pd.DataFrame:
    base = availability.copy()
    if train_factor_rows.empty:
        base["allowed_in_optimizer"] = False
        base["availability_reason"] = "not present in train window"
        return base
    train_availability = _factor_availability(train_factor_rows, factor_names)
    allowed = train_availability.set_index("factor_name")["allowed_in_optimizer"].to_dict()
    reason = train_availability.set_index("factor_name")["availability_reason"].to_dict()
    base["allowed_in_optimizer"] = base["factor_name"].map(allowed).fillna(False).astype(bool)
    base["availability_reason"] = base["factor_name"].map(reason).fillna("not present in train window")
    return base


def _allowed_map(availability: pd.DataFrame, factor_names: Sequence[str]) -> dict[str, bool]:
    if availability.empty:
        return {factor: True for factor in factor_names}
    mapping = availability.set_index("factor_name")["allowed_in_optimizer"].to_dict()
    return {factor: bool(mapping.get(factor, True)) for factor in factor_names}


def _constraint_check(
    weights: Mapping[str, float],
    groups: Mapping[str, str],
    cfg: WeightOptimizerConfig,
    availability: pd.DataFrame,
) -> dict[str, Any]:
    violations: list[str] = []
    allowed = _allowed_map(availability, list(weights.keys()))
    total = sum(float(value) for value in weights.values())
    if abs(total - 1.0) > 1e-6:
        violations.append(f"weights_sum={total:.8f}")
    for factor, value in weights.items():
        weight = float(value)
        cap = cfg.rates_change_5d_max_weight if factor == RATES_FACTOR else cfg.max_factor_weight
        if weight < -1e-9:
            violations.append(f"{factor} is negative")
        if weight > cap + 1e-9:
            violations.append(f"{factor} exceeds cap {cap:.2%}")
        if not allowed.get(factor, True) and weight > 1e-9:
            violations.append(f"{factor} has weight before data is available")
    for group in sorted({groups.get(factor, "ungrouped") for factor in weights}):
        group_weight = sum(float(value) for factor, value in weights.items() if groups.get(factor, "ungrouped") == group)
        if group_weight > cfg.max_group_weight + 1e-9:
            violations.append(f"group {group} exceeds cap {cfg.max_group_weight:.2%}")
    etf_margin_weight = sum(float(weights.get(factor, 0.0)) for factor in ETF_MARGIN_FACTORS)
    if etf_margin_weight > cfg.etf_margin_combined_max_weight + 1e-9:
        violations.append(f"ETF flow + margin proxy exceeds cap {cfg.etf_margin_combined_max_weight:.2%}")
    return {
        "pass": not violations,
        "violations": violations,
        "weight_sum": total,
    }


def _constraint_description(cfg: WeightOptimizerConfig) -> dict[str, Any]:
    return {
        "max_factor_weight": cfg.max_factor_weight,
        "max_group_weight": cfg.max_group_weight,
        "nonnegative_weights": True,
        "yield_curve_slope_zero_until_real_data": True,
        "rates_change_5d_max_weight": cfg.rates_change_5d_max_weight,
        "etf_flow_plus_margin_proxy_max_weight": cfg.etf_margin_combined_max_weight,
        "projection": "capacity-aware redistribution, not simple clipping",
    }


def _leakage_checks(factors: pd.DataFrame, model: pd.DataFrame, folds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []
    data_before_signal = bool((pd.to_datetime(factors["data_date"]) < pd.to_datetime(factors["date"])).all())
    checks.append({"name": "factor_data_date_before_signal_date", "pass": data_before_signal})
    if not data_before_signal:
        warnings.append("Some factor rows have data_date >= signal date.")
    target_alignment = (
        "market_return is the realized return on signal date; because factors require data_date < signal date, "
        "this is equivalent to a next-day target from the factor data date."
    )
    checks.append({"name": "next_day_return_shift_minus_one_contract", "pass": True, "note": target_alignment})
    checks.append({"name": "rolling_zscore_no_full_sample_refit_in_optimizer", "pass": True, "note": "optimizer consumes as-of directional_score only"})
    walk_forward_ok = all(pd.Timestamp(fold["train_end"]) < pd.Timestamp(fold["test_start"]) for fold in folds)
    checks.append({"name": "walk_forward_train_before_test", "pass": walk_forward_ok})
    if not walk_forward_ok:
        warnings.append("At least one fold has train_end >= test_start.")
    checks.append(
        {
            "name": "full_history_optimized_weights_warning",
            "pass": True,
            "warning": "optimized weights are full-history diagnostic only, not out-of-sample verified",
        }
    )
    warnings.append("optimized weights fit on all visible history are full-history diagnostic only, not out-of-sample verified")
    return {
        "pass": all(item.get("pass", False) for item in checks if "pass" in item),
        "checks": checks,
        "warnings": warnings,
    }


def _permutation_sanity_check(
    model: pd.DataFrame,
    factor_daily: pd.DataFrame,
    factor_names: Sequence[str],
    current_weights: Mapping[str, float],
    groups: Mapping[str, str],
    availability: pd.DataFrame,
    cfg: WeightOptimizerConfig,
    real_folds: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if real_folds is None:
        real_folds, _, _, _ = _run_walk_forward(
            model,
            factor_daily,
            factor_names,
            current_weights,
            groups,
            availability,
            cfg,
        )
    real_hit = _mean_metric(real_folds, "direction_hit_rate")
    real_capture = _mean_metric(real_folds, "big_loss_capture_rate")
    rng = np.random.default_rng(cfg.permutation_seed)
    hit_values: list[float] = []
    capture_values: list[float] = []
    for _ in range(max(int(cfg.permutation_count), 0)):
        permuted = model.copy()
        permuted["market_return"] = rng.permutation(permuted["market_return"].to_numpy())
        permuted["big_loss_day_flag"] = rng.permutation(permuted["big_loss_day_flag"].to_numpy())
        try:
            folds, _, _, _ = _run_walk_forward(permuted, factor_daily, factor_names, current_weights, groups, availability, cfg)
        except ValueError:
            continue
        hit = _mean_metric(folds, "direction_hit_rate")
        capture = _mean_metric(folds, "big_loss_capture_rate")
        if hit is not None:
            hit_values.append(hit)
        if capture is not None:
            capture_values.append(capture)
    return {
        "permutation_count": len(hit_values),
        "real_direction_hit_rate": real_hit,
        "permuted_direction_hit_rate_mean": float(np.mean(hit_values)) if hit_values else None,
        "direction_hit_rate_percentile": _percentile_rank(hit_values, real_hit),
        "direction_hit_rate_p_value": _right_tail_p_value(hit_values, real_hit),
        "real_big_loss_capture_rate": real_capture,
        "permuted_big_loss_capture_mean": float(np.mean(capture_values)) if capture_values else None,
        "big_loss_capture_percentile": _percentile_rank(capture_values, real_capture),
        "big_loss_capture_p_value": _right_tail_p_value(capture_values, real_capture),
    }


def _build_recommendation(
    oos_metrics: Mapping[str, Any],
    factor_stability: pd.DataFrame,
    constraint_checks: Mapping[str, Mapping[str, Any]],
    cfg: WeightOptimizerConfig,
) -> dict[str, Any]:
    direction_hit = oos_metrics.get("direction_hit_rate")
    strong_count = int(oos_metrics.get("strong_signal_count") or 0)
    capture = oos_metrics.get("big_loss_capture_rate")
    avoidance = oos_metrics.get("big_loss_avoidance_rate")
    blended_pass = bool(constraint_checks.get("constrained_blended_weights", {}).get("pass"))
    if not blended_pass:
        recommendation = "reject"
    elif direction_hit is not None and direction_hit <= 0.52:
        recommendation = "shadow_only"
    elif strong_count < 50:
        recommendation = "preliminary_shadow_only"
    else:
        recommendation = "review_required"

    negative_return_factors = []
    risk_only_candidates = []
    if not factor_stability.empty:
        negative_return_factors = factor_stability.loc[
            pd.to_numeric(factor_stability["return_ic_mean"], errors="coerce").fillna(0.0) < 0,
            "factor_name",
        ].tolist()
        risk_only_candidates = factor_stability.loc[
            (pd.to_numeric(factor_stability["risk_predictive_score"], errors="coerce").fillna(0.0) > 0)
            & (pd.to_numeric(factor_stability["return_predictive_score"], errors="coerce").fillna(0.0) <= 0),
            "factor_name",
        ].tolist()

    risk_filter_note = ""
    if capture is not None and avoidance is not None and capture < 0.50 and avoidance >= 0.70:
        risk_filter_note = "Model behaves more like a broad risk filter than a crash predictor."

    can_return = (
        "No. Out-of-sample direction hit rate is not above 52%."
        if direction_hit is None or direction_hit <= 0.52
        else "Possibly, but only as shadow diagnostics until manually approved."
    )
    can_risk = (
        "Inconclusive."
        if capture is None
        else (
            "Yes, risk filtering is useful, but crash prediction is limited."
            if capture < 0.50 and avoidance is not None and avoidance >= 0.70
            else "Possibly; review precision, recall, and false positives together."
        )
    )
    adopt = "No. Nothing should be adopted into production automatically."

    return {
        "recommendation": recommendation,
        "can_this_optimizer_improve_return_prediction": can_return,
        "can_this_optimizer_improve_risk_filtering": can_risk,
        "should_any_weight_be_adopted_into_production_now": adopt,
        "strong_signal_status": "preliminary" if strong_count < 50 else "sufficient_sample_review_needed",
        "risk_filter_note": risk_filter_note,
        "negative_return_ic_factors_do_not_raise_return_weight": negative_return_factors,
        "risk_score_only_candidates": risk_only_candidates,
        "do": [
            "Use constrained_blended_weights only as a shadow candidate.",
            "Review risk_score separately from return_score.",
            "Require manual approval before editing configs/factor_weights.yaml.",
        ],
        "do_not": [
            "Do not deploy optimized_return_weights directly.",
            "Do not interpret high abs IC with negative mean IC as return predictive power.",
            "Do not treat small-sample strong signal hit rates as stable.",
        ],
    }


def _fold_rows(folds: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fold in folds:
        row = {key: value for key, value in fold.items() if key not in {"return_weights", "risk_weights"}}
        for factor, weight in dict(fold.get("return_weights", {})).items():
            row[f"return_weight__{factor}"] = weight
        for factor, weight in dict(fold.get("risk_weights", {})).items():
            row[f"risk_weight__{factor}"] = weight
        rows.append(row)
    return rows


def _markdown_report(report: Mapping[str, Any]) -> str:
    oos = report.get("oos_summary", {})
    recommendation = report.get("recommendation", {})
    constraint_checks = report.get("constraint_checks", {})
    lines = [
        "# Weight Diagnostics",
        "",
        "## Executive Summary",
        "",
        f"- Adoption status: `{report.get('adoption_status', 'not adopted')}`.",
        f"- OOS direction hit rate: {_format_metric(oos.get('direction_hit_rate'))}.",
        f"- OOS big loss capture rate: {_format_metric(oos.get('big_loss_capture_rate'))}.",
        f"- Strong signal count: `{oos.get('strong_signal_count', 0)}`.",
        "",
        "## What changed from current weights",
        "",
        _weights_markdown_table(report.get("current_weights", {}), report.get("optimized_return_weights", {}), report.get("optimized_risk_weights", {}), report.get("constrained_blended_weights", {})),
        "",
        "## Constraint checks",
        "",
        _constraint_markdown(constraint_checks),
        "",
        "## Return score diagnostics",
        "",
        f"- Test IC: {_format_metric(oos.get('return_score_test_ic'))}.",
        f"- Direction hit rate CI: `{oos.get('direction_hit_rate_ci')}`.",
        f"- Long-side average return: {_format_metric(oos.get('long_side_avg_return'))}.",
        f"- Short/risk-off average return: {_format_metric(oos.get('short_risk_off_avg_return'))}.",
        "",
        "## Risk score diagnostics",
        "",
        f"- TP/FP/TN/FN: `{oos.get('TP')}/{oos.get('FP')}/{oos.get('TN')}/{oos.get('FN')}`.",
        f"- Precision: {_format_metric(oos.get('big_loss_precision_rate'))}.",
        f"- False positive rate: {_format_metric(oos.get('false_positive_rate'))}.",
        "",
        "## Walk-forward fold summary",
        "",
        _top_rows_markdown(report.get("walk_forward_folds", []), ["fold", "train_start", "train_end", "test_start", "test_end", "sample_count", "direction_hit_rate", "big_loss_capture_rate"], 12),
        "",
        "## Factor stability ranking",
        "",
        _top_rows_markdown(report.get("factor_stability", []), ["factor_name", "return_ic_mean", "return_predictive_score", "risk_predictive_score", "weight_volatility", "final_stability_rank"], 20),
        "",
        "## Regime diagnostics",
        "",
        _regime_markdown(report.get("regime_diagnostics", {})),
        "",
        "## Bucket analysis",
        "",
        "### Return buckets",
        "",
        _top_rows_markdown(report.get("bucket_analysis_return", []), ["bucket", "sample_count", "next_day_avg_return", "direction_hit_rate", "big_loss_rate"], 10),
        "",
        "### Risk buckets",
        "",
        _top_rows_markdown(report.get("bucket_analysis_risk", []), ["bucket", "sample_count", "big_loss_rate", "avg_next_day_return", "false_alarm_count", "missed_big_loss_count"], 10),
        "",
        "## Leakage checks",
        "",
        _leakage_markdown(report.get("leakage_checks", {})),
        "",
        "## Recommendation",
        "",
        f"1. Can this optimizer improve return prediction? {recommendation.get('can_this_optimizer_improve_return_prediction', 'N/A')}",
        f"2. Can this optimizer improve risk filtering? {recommendation.get('can_this_optimizer_improve_risk_filtering', 'N/A')}",
        f"3. Should any weight be adopted into production now? {recommendation.get('should_any_weight_be_adopted_into_production_now', 'No.')}",
        "",
        "## Do / Do Not",
        "",
        "### Do",
        "",
        *[f"- {item}" for item in recommendation.get("do", [])],
        "",
        "### Do Not",
        "",
        *[f"- {item}" for item in recommendation.get("do_not", [])],
        "",
    ]
    return "\n".join(lines)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    pd.DataFrame(list(rows)).to_csv(path, index=False, encoding="utf-8")


def _records_from_frame(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [_json_ready(record) for record in frame.to_dict(orient="records")]


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return _date_text(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, np.bool_):
        return bool(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _ordered_factor_names(current_weights: Mapping[str, float], factors: pd.DataFrame) -> list[str]:
    names = list(current_weights.keys())
    for factor in factors["factor_name"].dropna().astype(str).drop_duplicates().tolist():
        if factor not in names:
            names.append(factor)
    return names


def _complete_weights(current_weights: Mapping[str, float], factor_names: Sequence[str]) -> dict[str, float]:
    return {factor: float(current_weights.get(factor, 0.0)) for factor in factor_names}


def _factor_rows_for_dates(factors: pd.DataFrame, dates: pd.Series) -> pd.DataFrame:
    date_index = set(pd.to_datetime(dates).dt.normalize())
    return factors[factors["date"].isin(date_index)].copy()


def _safe_corr(left: pd.Series, right: pd.Series) -> float | None:
    frame = pd.DataFrame(
        {
            "left": pd.to_numeric(left, errors="coerce"),
            "right": pd.to_numeric(right, errors="coerce"),
        }
    ).dropna()
    if len(frame) < 2 or frame["left"].std(ddof=0) == 0 or frame["right"].std(ddof=0) == 0:
        return None
    value = float(frame["left"].corr(frame["right"]))
    if not np.isfinite(value):
        return None
    return value


def _direction_hit_rate(signal: pd.Series, target: pd.Series) -> float | None:
    if signal.empty:
        return None
    signal_sign = np.sign(pd.to_numeric(signal, errors="coerce").fillna(0.0))
    target_sign = np.sign(pd.to_numeric(target, errors="coerce").fillna(0.0))
    mask = (signal_sign != 0) & (target_sign != 0)
    if not bool(mask.any()):
        return None
    return float((signal_sign[mask] == target_sign[mask]).mean())


def _binomial_ci_from_hits(signal: pd.Series, target: pd.Series) -> dict[str, Any] | None:
    signal_sign = np.sign(pd.to_numeric(signal, errors="coerce").fillna(0.0))
    target_sign = np.sign(pd.to_numeric(target, errors="coerce").fillna(0.0))
    mask = (signal_sign != 0) & (target_sign != 0)
    n = int(mask.sum())
    if n == 0:
        return None
    hits = int((signal_sign[mask] == target_sign[mask]).sum())
    return _wilson_ci(hits, n)


def _wilson_ci(successes: int, total: int, z: float = 1.96) -> dict[str, Any] | None:
    if total <= 0:
        return None
    p = successes / total
    denom = 1.0 + z * z / total
    centre = p + z * z / (2.0 * total)
    margin = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total)
    return {
        "successes": int(successes),
        "total": int(total),
        "rate": float(p),
        "lower": float((centre - margin) / denom),
        "upper": float((centre + margin) / denom),
    }


def _max_drawdown_proxy(score: pd.Series, returns: pd.Series, cfg: WeightOptimizerConfig) -> float | None:
    if score.empty:
        return None
    exposure = pd.Series(0.5, index=score.index)
    exposure[score >= cfg.strong_signal_threshold] = 1.0
    exposure[score <= -cfg.strong_signal_threshold] = 0.0
    strategy_returns = exposure * pd.to_numeric(returns, errors="coerce").fillna(0.0)
    equity = (1.0 + strategy_returns).cumprod()
    if equity.empty:
        return None
    drawdown = equity / equity.cummax() - 1.0
    return float(drawdown.min())


def _safe_div(numerator: int | float, denominator: int | float) -> float | None:
    return None if denominator == 0 else float(numerator) / float(denominator)


def _fold_ic_series(oos: pd.DataFrame) -> pd.Series:
    values = []
    for _, group in oos.groupby("fold", sort=True):
        value = _safe_corr(group["return_score"], group["market_return"])
        if value is not None:
            values.append(value)
    return pd.Series(values, dtype=float)


def _t_stat(values: pd.Series | Sequence[float]) -> float | None:
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if len(series) < 2:
        return None
    std = series.std(ddof=1)
    if std == 0 or pd.isna(std):
        return None
    return float(series.mean() / (std / math.sqrt(len(series))))


def _mean_metric(folds: Sequence[Mapping[str, Any]], metric: str) -> float | None:
    values = [float(fold[metric]) for fold in folds if fold.get(metric) is not None]
    return float(np.mean(values)) if values else None


def _percentile_rank(values: Sequence[float], real_value: float | None) -> float | None:
    if real_value is None or not values:
        return None
    return float((np.asarray(values) <= real_value).mean())


def _right_tail_p_value(values: Sequence[float], real_value: float | None) -> float | None:
    if real_value is None or not values:
        return None
    return float((1 + (np.asarray(values) >= real_value).sum()) / (len(values) + 1))


def _date_text(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _format_metric(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        if pd.isna(value):
            return "N/A"
    except (TypeError, ValueError):
        pass
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _weights_markdown_table(
    current: Mapping[str, Any],
    return_weights: Mapping[str, Any],
    risk_weights: Mapping[str, Any],
    blended: Mapping[str, Any],
) -> str:
    factors = sorted(set(current) | set(return_weights) | set(risk_weights) | set(blended))
    lines = ["| factor | current | return optimized | risk optimized | constrained blended |", "| --- | ---: | ---: | ---: | ---: |"]
    for factor in factors:
        lines.append(
            f"| `{factor}` | {_format_metric(current.get(factor))} | {_format_metric(return_weights.get(factor))} | "
            f"{_format_metric(risk_weights.get(factor))} | {_format_metric(blended.get(factor))} |"
        )
    return "\n".join(lines)


def _constraint_markdown(checks: Mapping[str, Any]) -> str:
    lines = ["| weight set | pass | violations |", "| --- | --- | --- |"]
    for name, check in checks.items():
        violations = "; ".join(check.get("violations", [])) if isinstance(check, Mapping) else ""
        passed = check.get("pass") if isinstance(check, Mapping) else None
        lines.append(f"| `{name}` | `{passed}` | {violations or 'none'} |")
    return "\n".join(lines)


def _top_rows_markdown(rows: Sequence[Mapping[str, Any]], columns: Sequence[str], limit: int) -> str:
    if not rows:
        return "No data."
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in list(rows)[:limit]:
        lines.append("| " + " | ".join(_format_metric(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def _regime_markdown(regimes: Mapping[str, Any]) -> str:
    if not regimes:
        return "No data."
    lines = []
    for regime_type, items in regimes.items():
        lines.append(f"### {regime_type}")
        lines.append("")
        lines.append("| regime | samples | failed factors | effective factors |")
        lines.append("| --- | ---: | --- | --- |")
        for item in items:
            lines.append(
                f"| {item.get('regime')} | {item.get('sample_count')} | "
                f"{', '.join(item.get('failed_factors', [])) or 'none'} | "
                f"{', '.join(item.get('regime_effective_factors', [])) or 'none'} |"
            )
        lines.append("")
    return "\n".join(lines)


def _leakage_markdown(checks: Mapping[str, Any]) -> str:
    rows = checks.get("checks", []) if isinstance(checks, Mapping) else []
    lines = ["| check | pass | note |", "| --- | --- | --- |"]
    for row in rows:
        lines.append(f"| {row.get('name')} | `{row.get('pass')}` | {row.get('note') or row.get('warning') or ''} |")
    warnings = checks.get("warnings", []) if isinstance(checks, Mapping) else []
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines)


def _resolve_snapshot_dir(snapshot_dir: str | None, snapshot_root: str) -> Path:
    if snapshot_dir:
        return Path(snapshot_dir)
    snapshots = list_snapshots(snapshot_root)
    if not snapshots:
        raise FileNotFoundError(f"No snapshots found under {snapshot_root}.")
    return snapshots[0].path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate walk-forward factor weight diagnostics.")
    parser.add_argument("--snapshot-dir", help="Specific local snapshot directory to analyze.")
    parser.add_argument("--snapshot-root", default="data/snapshots", help="Snapshot root used when --snapshot-dir is omitted.")
    parser.add_argument("--config-dir", default="configs", help="Project config directory.")
    parser.add_argument("--output-dir", default="reports/weight_optimizer", help="Directory for generated reports.")
    parser.add_argument("--train-window", type=int, default=WeightOptimizerConfig.train_window)
    parser.add_argument("--test-window", type=int, default=WeightOptimizerConfig.test_window)
    parser.add_argument("--step", type=int, default=WeightOptimizerConfig.step)
    parser.add_argument("--min-train-periods", type=int, default=WeightOptimizerConfig.min_train_periods)
    parser.add_argument("--rolling-ic-window", type=int, default=WeightOptimizerConfig.rolling_ic_window)
    parser.add_argument("--rolling-ic-min-periods", type=int, default=WeightOptimizerConfig.rolling_ic_min_periods)
    parser.add_argument("--permutation-count", type=int, default=WeightOptimizerConfig.permutation_count)
    args = parser.parse_args(argv)

    cfg = WeightOptimizerConfig(
        train_window=args.train_window,
        test_window=args.test_window,
        step=args.step,
        min_train_periods=args.min_train_periods,
        rolling_ic_window=args.rolling_ic_window,
        rolling_ic_min_periods=args.rolling_ic_min_periods,
        permutation_count=args.permutation_count,
    )
    snapshot = _resolve_snapshot_dir(args.snapshot_dir, args.snapshot_root)
    result = run_pipeline_from_snapshot(snapshot, config_dir=args.config_dir)
    current_weights, groups = load_weight_config(args.config_dir)
    report = generate_weight_diagnostic_report(
        factors=result["factors"],
        labels=result["labels"],
        current_weights=current_weights,
        groups=groups,
        config=cfg,
        index_ohlcv=result.get("raw", {}).get("index_ohlcv"),
    )
    output = save_weight_diagnostic_report(report, args.output_dir)
    print(f"weight diagnostic report: {output}")
    print("adoption_status:", report["adoption_status"])
    print("recommendation:", report["recommendation"]["recommendation"])
    print("constrained_blended_weights:")
    print(yaml.safe_dump(report["constrained_blended_weights"], sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
