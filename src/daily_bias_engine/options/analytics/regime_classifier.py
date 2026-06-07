"""Rules-based option regime classifier."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Any

import pandas as pd


@dataclass(frozen=True)
class OptionRegimeResult:
    regime: str
    option_direction_score: float
    option_risk_score: float
    vol_carry_score: float
    tail_risk_score: float
    recommended_beta_multiplier: float
    allow_short_vol: bool
    prefer_option_structure: str
    explanation: str


def classify_option_regime(factors: Mapping[str, Any] | pd.Series | pd.DataFrame) -> OptionRegimeResult:
    """Classify product option state from a wide factor row."""

    row = _as_mapping(factors)
    gex_z = _num(row, "gex_z")
    iv_change = _num(row, "iv_30d_change")
    iv_percentile = _num(row, "iv_percentile_252d", default=0.5)
    put_skew_z = _num(row, "put_skew_z")
    put_skew_change = _num(row, "put_skew_25d_change")
    call_skew_change = _num(row, "call_skew_25d_change")
    distance_to_zero = abs(_num(row, "spot_to_zero_gamma_pct", default=9.0))
    distance_to_max_gamma = abs(_num(row, "spot_to_max_gamma_pct", default=9.0))
    spot_above_put_wall = _num(row, "spot_to_put_wall_pct", default=-1.0) < 0.0
    call_oi_rising = _num(row, "call_oi_change", default=0.0) > 0.0 or _num(row, "oi_change_by_moneyness_otm", default=0.0) > 0.0
    put_oi_rising = _num(row, "put_oi_change", default=0.0) > 0.0 or put_skew_change > 0.0
    vanna_down_support = _num(row, "vanna_shock_down") > 0.0
    near_gamma_wall = distance_to_max_gamma <= 0.02 or distance_to_zero <= 0.02

    if gex_z > 1.0 and iv_change <= 0.005 and near_gamma_wall and put_skew_change <= 0.005:
        return OptionRegimeResult(
            regime="PIN_GRIND",
            option_direction_score=0.15,
            option_risk_score=0.25,
            vol_carry_score=0.45,
            tail_risk_score=0.20,
            recommended_beta_multiplier=0.85,
            allow_short_vol=True,
            prefer_option_structure="defined-risk short premium or no overlay",
            explanation=_explain("Positive gamma pinning dominates", ["GEX z-score > +1", "spot near gamma wall", "IV not rising"]),
        )

    if gex_z < -1.0 and distance_to_zero <= 0.03 and iv_change > 0.0 and put_skew_change >= 0.0:
        return OptionRegimeResult(
            regime="NEGATIVE_GAMMA_FRAGILE",
            option_direction_score=-0.45,
            option_risk_score=0.85,
            vol_carry_score=-0.35,
            tail_risk_score=0.75,
            recommended_beta_multiplier=0.45,
            allow_short_vol=False,
            prefer_option_structure="put spread hedge",
            explanation=_explain("Negative gamma and worsening put demand raise fragility", ["GEX z-score < -1", "spot near zero gamma", "IV/skew rising"]),
        )

    if iv_percentile >= 0.75 and vanna_down_support and spot_above_put_wall:
        return OptionRegimeResult(
            regime="VOL_CRUSH_VANNA_SUPPORT",
            option_direction_score=0.35,
            option_risk_score=0.35,
            vol_carry_score=0.55,
            tail_risk_score=0.30,
            recommended_beta_multiplier=1.15,
            allow_short_vol=True,
            prefer_option_structure="defined-risk short vol",
            explanation=_explain("High IV can mean-revert while vanna flow supports spot", ["IV percentile high", "vanna shock-down support", "spot above put wall"]),
        )

    if put_skew_z > 1.5 and put_oi_rising and gex_z < 0.5:
        return OptionRegimeResult(
            regime="TAIL_DEMAND",
            option_direction_score=-0.20,
            option_risk_score=0.70,
            vol_carry_score=-0.20,
            tail_risk_score=0.85,
            recommended_beta_multiplier=0.65,
            allow_short_vol=False,
            prefer_option_structure="put spread or long convexity",
            explanation=_explain("OTM put demand is richening", ["put skew z-score > +1.5", "put demand rising", "GEX not supportive"]),
        )

    if call_skew_change > 0.0 and call_oi_rising and _num(row, "spot_to_call_wall_pct", default=9.0) <= 0.02 and gex_z < 0.0:
        return OptionRegimeResult(
            regime="UPSIDE_SQUEEZE",
            option_direction_score=0.55,
            option_risk_score=0.55,
            vol_carry_score=-0.05,
            tail_risk_score=0.25,
            recommended_beta_multiplier=1.25,
            allow_short_vol=False,
            prefer_option_structure="call spread",
            explanation=_explain("Call-side positioning can amplify upside", ["call skew rising", "call OI rising", "negative gamma above"]),
        )

    return OptionRegimeResult(
        regime="NEUTRAL",
        option_direction_score=0.0,
        option_risk_score=0.40,
        vol_carry_score=0.0,
        tail_risk_score=0.35,
        recommended_beta_multiplier=1.0,
        allow_short_vol=False,
        prefer_option_structure="none",
        explanation=_explain("No single option driver dominates", [f"GEX z-score {gex_z:.2f}", f"IV change {iv_change:.4f}"]),
    )


def _as_mapping(value: Mapping[str, Any] | pd.Series | pd.DataFrame) -> Mapping[str, Any]:
    if isinstance(value, pd.DataFrame):
        if value.empty:
            return {}
        return value.iloc[0].to_dict()
    if isinstance(value, pd.Series):
        return value.to_dict()
    return value


def _num(row: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key, default)
    if isinstance(value, dict):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(result):
        return default
    return result


def _explain(summary: str, drivers: list[str]) -> str:
    return f"{summary}. Top drivers: {', '.join(drivers)}."
