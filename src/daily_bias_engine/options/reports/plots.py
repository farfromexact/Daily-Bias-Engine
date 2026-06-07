"""Plot-ready datasets for option reports without hard matplotlib dependency."""

from __future__ import annotations

import pandas as pd

from daily_bias_engine.options.analytics.exposure import ExposureMode, compute_contract_exposures
from daily_bias_engine.options.analytics.levels import calculate_key_levels


def build_plot_datasets(
    chain: pd.DataFrame,
    factors: pd.DataFrame,
    mode: ExposureMode | str = ExposureMode.DEALER_SHORT_OPTIONS,
) -> dict[str, pd.DataFrame]:
    exposures = compute_contract_exposures(chain, mode=mode)
    levels = calculate_key_levels(exposures, mode=mode)
    term_structure = _term_structure_frame(factors)
    skew_curve = _skew_curve_frame(factors)
    risk_history = factors[["date", "product_group"]].copy()
    if "option_risk_score" in factors.columns:
        risk_history["option_risk_score"] = factors["option_risk_score"]
    return {
        "gex_by_strike": levels["gamma_by_strike"],
        "spot_grid_gex": levels["spot_grid_gamma"],
        "iv_term_structure": term_structure,
        "skew_curve": skew_curve,
        "historical_option_risk_score": risk_history,
    }


def _term_structure_frame(factors: pd.DataFrame) -> pd.DataFrame:
    row = factors.iloc[0].to_dict() if not factors.empty else {}
    return pd.DataFrame(
        [{"tenor_days": tenor, "atm_iv": row.get(f"iv_{tenor}d")} for tenor in (7, 14, 30, 60, 90)]
    )


def _skew_curve_frame(factors: pd.DataFrame) -> pd.DataFrame:
    row = factors.iloc[0].to_dict() if not factors.empty else {}
    return pd.DataFrame(
        [
            {"point": "10d_put", "iv": row.get("put_10d_iv")},
            {"point": "25d_put", "iv": row.get("put_25d_iv")},
            {"point": "atm", "iv": row.get("iv_30d")},
            {"point": "25d_call", "iv": row.get("call_25d_iv")},
            {"point": "10d_call", "iv": row.get("call_10d_iv")},
        ]
    )
