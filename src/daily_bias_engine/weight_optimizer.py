"""Walk-forward factor weight diagnostics.

This module intentionally does not update ``configs/factor_weights.yaml``. It
generates diagnostics and recommended weights that can be reviewed manually.
"""

from __future__ import annotations

import argparse
import json
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
    max_factor_weight: float = 0.25
    max_group_weight: float = 0.35
    rates_change_5d_max_weight: float = 0.05
    etf_margin_combined_max_weight: float = 0.15
    blended_current_weight: float = 0.60
    blended_optimized_weight: float = 0.40


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
) -> dict[str, Any]:
    """Generate a walk-forward weight diagnostic report.

    The optimizer uses only factor rows and labels in each training window to
    fit fold weights. Test metrics are then computed on the subsequent
    chronological test window. No random split or full-sample normalization is
    used.
    """

    cfg = config or WeightOptimizerConfig()
    factor_daily = validate_no_lookahead_contract(validate_factor_frame(factors))
    factor_names = _ordered_factor_names(current_weights, factor_daily)
    model = _prepare_model_frame(factor_daily, labels, factor_names)
    if len(model) < cfg.min_train_periods + 1:
        raise ValueError(
            f"Need at least {cfg.min_train_periods + 1} aligned observations for walk-forward diagnostics; "
            f"got {len(model)}."
        )

    current = _complete_weights(current_weights, factor_names)
    fold_records: list[dict[str, Any]] = []
    fold_weight_records: list[dict[str, Any]] = []
    for split in _walk_forward_splits(model, cfg):
        train = model.iloc[split["train_start_idx"] : split["train_end_idx"] + 1].copy()
        test = model.iloc[split["test_start_idx"] : split["test_end_idx"] + 1].copy()
        train_factor_rows = _factor_rows_for_dates(factor_daily, train["date"])
        weights = _fit_constrained_weights(train, train_factor_rows, factor_names, current, groups, cfg)
        metrics = _evaluate_weight_set(test, weights, factor_names, cfg)
        fold = {
            "train_start": _date_text(train["date"].iloc[0]),
            "train_end": _date_text(train["date"].iloc[-1]),
            "test_start": _date_text(test["date"].iloc[0]),
            "test_end": _date_text(test["date"].iloc[-1]),
            "weights": weights,
            **metrics,
        }
        fold_records.append(_json_ready(fold))
        fold_weight_records.append({"fold": len(fold_records) - 1, **weights})

    optimized = _fit_constrained_weights(model, factor_daily, factor_names, current, groups, cfg)
    blended = {
        factor: (
            cfg.blended_current_weight * current.get(factor, 0.0)
            + cfg.blended_optimized_weight * optimized.get(factor, 0.0)
        )
        for factor in factor_names
    }
    rolling_ic = _rolling_factor_ic(model, factor_names, cfg)
    factor_stability = _factor_stability(
        rolling_ic=rolling_ic,
        fold_weight_records=fold_weight_records,
        factor_names=factor_names,
        current_weights=current,
        optimized_weights=optimized,
        blended_weights=blended,
    )
    final_yield_has_real_data = _factor_has_real_data(factor_daily, YIELD_CURVE_FACTOR)
    report = {
        "created_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "objective": "Walk-forward weight diagnostics; does not overwrite factor_weights.yaml.",
        "methodology": {
            "split": "strict chronological walk-forward",
            "normalization": "uses existing as-of directional_score; no full-sample refit or random split",
            "training_targets": [
                "next-day return IC",
                "direction hit rate",
                "big loss day filtering ability",
            ],
            "final_recommendation": "optimized_weights are fit on all currently visible history; blended_weights are formula-only.",
        },
        "config": _json_ready(cfg.__dict__),
        "constraints": {
            "max_factor_weight": cfg.max_factor_weight,
            "max_group_weight": cfg.max_group_weight,
            "nonnegative_weights": True,
            "yield_curve_slope_zero_until_real_data": True,
            "rates_change_5d_max_weight": cfg.rates_change_5d_max_weight,
            "etf_flow_plus_margin_proxy_max_weight": cfg.etf_margin_combined_max_weight,
        },
        "current_weights": _json_ready(current),
        "optimized_weights": _json_ready(optimized),
        "blended_weights": _json_ready(blended),
        "constraint_checks": {
            "optimized_weights": _constraint_violations(optimized, groups, cfg, final_yield_has_real_data),
            "blended_weights": _constraint_violations(blended, groups, cfg, final_yield_has_real_data),
        },
        "walk_forward_folds": fold_records,
        "factor_stability": _records_from_frame(factor_stability),
        "rolling_ic": _records_from_frame(rolling_ic),
    }
    return report


def save_weight_diagnostic_report(report: Mapping[str, Any], output_dir: Path | str) -> Path:
    """Write report JSON plus review-friendly CSV/YAML artifacts."""

    root = Path(output_dir) / pd.Timestamp.now(tz="Asia/Shanghai").strftime("%Y%m%dT%H%M%S%z")
    root.mkdir(parents=True, exist_ok=False)
    (root / "weight_diagnostic_report.json").write_text(
        json.dumps(_json_ready(dict(report)), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    folds = list(report.get("walk_forward_folds", []))
    if folds:
        fold_rows = []
        for fold in folds:
            row = {key: value for key, value in fold.items() if key != "weights"}
            for factor, weight in dict(fold.get("weights", {})).items():
                row[f"weight__{factor}"] = weight
            fold_rows.append(row)
        pd.DataFrame(fold_rows).to_csv(root / "walk_forward_folds.csv", index=False, encoding="utf-8")

    stability = report.get("factor_stability", [])
    if stability:
        pd.DataFrame(stability).to_csv(root / "factor_stability.csv", index=False, encoding="utf-8")

    rolling_ic = report.get("rolling_ic", [])
    if rolling_ic:
        pd.DataFrame(rolling_ic).to_csv(root / "rolling_ic.csv", index=False, encoding="utf-8")

    recommendation = {
        "note": "Review only. Do not copy blindly; this file is not loaded by the engine.",
        "current_weights": report.get("current_weights", {}),
        "optimized_weights": report.get("optimized_weights", {}),
        "blended_weights": report.get("blended_weights", {}),
        "constraint_checks": report.get("constraint_checks", {}),
    }
    (root / "recommended_weights.yaml").write_text(
        yaml.safe_dump(_json_ready(recommendation), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return root


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
    cfg: WeightOptimizerConfig,
) -> dict[str, float]:
    scores = _training_factor_scores(train, factor_names, cfg)
    if not any(value > 0 for value in scores.values()):
        scores = {factor: max(float(current_weights.get(factor, 0.0)), 0.0) for factor in factor_names}
    yield_has_real_data = _factor_has_real_data(train_factor_rows, YIELD_CURVE_FACTOR)
    return _allocate_constrained_weights(scores, factor_names, groups, cfg, yield_has_real_data)


def _training_factor_scores(
    train: pd.DataFrame,
    factor_names: Sequence[str],
    cfg: WeightOptimizerConfig,
) -> dict[str, float]:
    target = pd.to_numeric(train["market_return"], errors="coerce").fillna(0.0)
    big_loss = train["big_loss_day_flag"].astype(bool)
    scores: dict[str, float] = {}
    for factor in factor_names:
        signal = pd.to_numeric(train[factor], errors="coerce").fillna(0.0)
        ic = _safe_corr(signal, target)
        hit_rate = _direction_hit_rate(signal, target)
        if big_loss.any():
            strong_negative = signal <= -cfg.strong_signal_threshold
            loss_capture = float((strong_negative & big_loss).sum() / big_loss.sum())
            loose_avoidance = float(((signal <= 0.0) & big_loss).sum() / big_loss.sum())
        else:
            loss_capture = 0.0
            loose_avoidance = 0.0
        hit_component = 0.0 if hit_rate is None else max(hit_rate - 0.5, 0.0) * 2.0
        loss_component = 0.7 * loss_capture + 0.3 * loose_avoidance
        score = 0.50 * max(ic or 0.0, 0.0) + 0.25 * hit_component + 0.25 * loss_component
        scores[factor] = float(max(score, 0.0))
    return scores


def _allocate_constrained_weights(
    raw_scores: Mapping[str, float],
    factor_names: Sequence[str],
    groups: Mapping[str, str],
    cfg: WeightOptimizerConfig,
    yield_curve_has_real_data: bool,
) -> dict[str, float]:
    weights = {factor: 0.0 for factor in factor_names}
    desired = {factor: max(float(raw_scores.get(factor, 0.0)), 0.0) for factor in factor_names}
    if not yield_curve_has_real_data and YIELD_CURVE_FACTOR in desired:
        desired[YIELD_CURVE_FACTOR] = 0.0

    remaining = 1.0
    for _ in range(500):
        if remaining <= 1e-10:
            break
        capacities = {
            factor: _capacity_for_factor(factor, weights, groups, cfg, yield_curve_has_real_data)
            for factor in factor_names
        }
        eligible = [factor for factor in factor_names if capacities[factor] > 1e-10]
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
            capacity = _capacity_for_factor(factor, weights, groups, cfg, yield_curve_has_real_data)
            if capacity <= 1e-10 or remaining <= 1e-10:
                continue
            addition = min(capacity, remaining * preference[factor] / preference_sum)
            if addition <= 1e-12:
                continue
            weights[factor] += addition
            remaining -= addition
            added += addition
        if added <= 1e-12:
            capacities = {
                factor: _capacity_for_factor(factor, weights, groups, cfg, yield_curve_has_real_data)
                for factor in factor_names
            }
            eligible = [factor for factor in factor_names if capacities[factor] > 1e-10]
            if not eligible:
                break
            factor = max(eligible, key=lambda item: capacities[item])
            added = min(remaining, capacities[factor])
            weights[factor] += added
            remaining -= added

    cleaned = {factor: float(0.0 if abs(value) < 1e-12 else value) for factor, value in weights.items()}
    return cleaned


def _capacity_for_factor(
    factor: str,
    weights: Mapping[str, float],
    groups: Mapping[str, str],
    cfg: WeightOptimizerConfig,
    yield_curve_has_real_data: bool,
) -> float:
    if factor == YIELD_CURVE_FACTOR and not yield_curve_has_real_data:
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


def _evaluate_weight_set(
    test: pd.DataFrame,
    weights: Mapping[str, float],
    factor_names: Sequence[str],
    cfg: WeightOptimizerConfig,
) -> dict[str, Any]:
    score = _composite_score(test, weights, factor_names)
    target = pd.to_numeric(test["market_return"], errors="coerce").fillna(0.0)
    strong = score.abs() >= cfg.strong_signal_threshold
    big_loss = test["big_loss_day_flag"].astype(bool)
    strong_negative = score <= -cfg.strong_signal_threshold
    strong_signal_hit = _direction_hit_rate(score[strong], target[strong]) if strong.any() else None
    if big_loss.any():
        capture = float((strong_negative & big_loss).sum() / big_loss.sum())
        avoidance = float(((score <= 0.0) & big_loss).sum() / big_loss.sum())
    else:
        capture = None
        avoidance = None
    precision = float((strong_negative & big_loss).sum() / strong_negative.sum()) if strong_negative.any() else None
    return {
        "test_ic": _safe_corr(score, target),
        "direction_hit_rate": _direction_hit_rate(score, target),
        "strong_signal_hit_rate": strong_signal_hit,
        "big_loss_capture_rate": capture,
        "big_loss_avoidance_rate": avoidance,
        "big_loss_precision_rate": precision,
        "max_drawdown_proxy": _max_drawdown_proxy(score, target, cfg),
        "sample_count": int(len(test)),
    }


def _composite_score(test: pd.DataFrame, weights: Mapping[str, float], factor_names: Sequence[str]) -> pd.Series:
    weight_values = pd.Series({factor: float(weights.get(factor, 0.0)) for factor in factor_names})
    weight_sum = weight_values.abs().sum()
    if weight_sum <= 0:
        return pd.Series(0.0, index=test.index)
    matrix = test[list(factor_names)].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    return matrix.dot(weight_values) / weight_sum


def _rolling_factor_ic(model: pd.DataFrame, factor_names: Sequence[str], cfg: WeightOptimizerConfig) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for factor in factor_names:
        frame = model[["date", factor, "market_return"]].copy()
        for end_idx in range(len(frame)):
            start_idx = max(0, end_idx - cfg.rolling_ic_window + 1)
            window = frame.iloc[start_idx : end_idx + 1]
            sample_count = int(len(window))
            rolling_ic = None
            if sample_count >= cfg.rolling_ic_min_periods:
                rolling_ic = _safe_corr(window[factor], window["market_return"])
            rows.append(
                {
                    "date": frame["date"].iloc[end_idx],
                    "factor_name": factor,
                    "rolling_ic": rolling_ic,
                    "sample_count": sample_count,
                }
            )
    return pd.DataFrame(rows)


def _factor_stability(
    rolling_ic: pd.DataFrame,
    fold_weight_records: Sequence[Mapping[str, Any]],
    factor_names: Sequence[str],
    current_weights: Mapping[str, float],
    optimized_weights: Mapping[str, float],
    blended_weights: Mapping[str, float],
) -> pd.DataFrame:
    weight_frame = pd.DataFrame(fold_weight_records)
    rows: list[dict[str, Any]] = []
    for factor in factor_names:
        ic_values = pd.to_numeric(
            rolling_ic.loc[rolling_ic["factor_name"] == factor, "rolling_ic"],
            errors="coerce",
        ).dropna()
        weight_values = (
            pd.to_numeric(weight_frame[factor], errors="coerce").dropna()
            if factor in weight_frame.columns
            else pd.Series(dtype=float)
        )
        ic_mean = float(ic_values.mean()) if not ic_values.empty else None
        ic_vol = float(ic_values.std(ddof=0)) if len(ic_values) > 1 else 0.0
        stability_score = None
        if ic_mean is not None:
            stability_score = abs(ic_mean) / (ic_vol + 1e-9)
        rows.append(
            {
                "factor_name": factor,
                "rolling_ic_mean": ic_mean,
                "rolling_ic_abs_mean": float(ic_values.abs().mean()) if not ic_values.empty else None,
                "rolling_ic_volatility": ic_vol,
                "stability_score": stability_score,
                "weight_volatility": float(weight_values.std(ddof=0)) if len(weight_values) > 1 else 0.0,
                "average_fold_weight": float(weight_values.mean()) if not weight_values.empty else 0.0,
                "current_weight": float(current_weights.get(factor, 0.0)),
                "optimized_weight": float(optimized_weights.get(factor, 0.0)),
                "blended_weight": float(blended_weights.get(factor, 0.0)),
            }
        )
    output = pd.DataFrame(rows)
    output["stability_rank"] = output["stability_score"].rank(method="min", ascending=False, na_option="bottom").astype(int)
    return output.sort_values(["stability_rank", "factor_name"]).reset_index(drop=True)


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


def _direction_hit_rate(signal: pd.Series, target: pd.Series) -> float | None:
    if signal.empty:
        return None
    signal_sign = np.sign(pd.to_numeric(signal, errors="coerce").fillna(0.0))
    target_sign = np.sign(pd.to_numeric(target, errors="coerce").fillna(0.0))
    mask = (signal_sign != 0) & (target_sign != 0)
    if not bool(mask.any()):
        return None
    return float((signal_sign[mask] == target_sign[mask]).mean())


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


def _factor_has_real_data(factors: pd.DataFrame, factor_name: str) -> bool:
    subset = factors[factors["factor_name"] == factor_name]
    if subset.empty or "raw_value" not in subset.columns:
        return False
    values = pd.to_numeric(subset["raw_value"], errors="coerce").dropna()
    return bool((values.abs() > 1e-12).any())


def _constraint_violations(
    weights: Mapping[str, float],
    groups: Mapping[str, str],
    cfg: WeightOptimizerConfig,
    yield_curve_has_real_data: bool,
) -> list[str]:
    violations: list[str] = []
    total = sum(float(value) for value in weights.values())
    if abs(total - 1.0) > 1e-6:
        violations.append(f"weights_sum={total:.6f}")
    for factor, value in weights.items():
        weight = float(value)
        cap = cfg.rates_change_5d_max_weight if factor == RATES_FACTOR else cfg.max_factor_weight
        if weight < -1e-9:
            violations.append(f"{factor} is negative")
        if weight > cap + 1e-9:
            violations.append(f"{factor} exceeds cap {cap:.2%}")
    if not yield_curve_has_real_data and float(weights.get(YIELD_CURVE_FACTOR, 0.0)) > 1e-9:
        violations.append("yield_curve_slope has weight before real data is available")
    group_names = sorted({groups.get(factor, "ungrouped") for factor in weights})
    for group in group_names:
        group_weight = sum(float(value) for factor, value in weights.items() if groups.get(factor, "ungrouped") == group)
        if group_weight > cfg.max_group_weight + 1e-9:
            violations.append(f"group {group} exceeds cap {cfg.max_group_weight:.2%}")
    etf_margin_weight = sum(float(weights.get(factor, 0.0)) for factor in ETF_MARGIN_FACTORS)
    if etf_margin_weight > cfg.etf_margin_combined_max_weight + 1e-9:
        violations.append(f"ETF flow + margin proxy exceeds cap {cfg.etf_margin_combined_max_weight:.2%}")
    return violations


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
    if pd.isna(value):
        return None
    return value


def _date_text(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


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
    args = parser.parse_args(argv)

    cfg = WeightOptimizerConfig(
        train_window=args.train_window,
        test_window=args.test_window,
        step=args.step,
        min_train_periods=args.min_train_periods,
        rolling_ic_window=args.rolling_ic_window,
        rolling_ic_min_periods=args.rolling_ic_min_periods,
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
    )
    output = save_weight_diagnostic_report(report, args.output_dir)
    print(f"weight diagnostic report: {output}")
    print("optimized_weights:")
    print(yaml.safe_dump(report["optimized_weights"], sort_keys=False))
    print("blended_weights:")
    print(yaml.safe_dump(report["blended_weights"], sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
