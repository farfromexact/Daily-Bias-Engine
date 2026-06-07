"""Daily option state report and CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from daily_bias_engine.options.analytics.exposure import ExposureMode, aggregate_exposures, compute_contract_exposures
from daily_bias_engine.options.analytics.factors import build_option_factors
from daily_bias_engine.options.analytics.regime_classifier import classify_option_regime
from daily_bias_engine.options.data.market_data_store import OptionMarketDataStore
from daily_bias_engine.options.reports.plots import build_plot_datasets


def generate_daily_option_state(
    trade_date: str | pd.Timestamp,
    product_group: str,
    *,
    store: OptionMarketDataStore | None = None,
    data_root: str | Path = Path("data/options"),
    mode: ExposureMode | str = ExposureMode.DEALER_SHORT_OPTIONS,
    underlying_history: pd.DataFrame | None = None,
    historical_factors: pd.DataFrame | None = None,
    include_markdown: bool = True,
    include_plots: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any], str | None, dict[str, pd.DataFrame] | None]:
    """Generate a daily option state factor row from local normalized option data."""

    option_store = store or OptionMarketDataStore(data_root)
    chain = option_store.read_normalized_chain(product_group.upper(), trade_date)
    factors = build_option_factors(chain, underlying_history=underlying_history, historical_factors=historical_factors, mode=mode)
    regime = classify_option_regime(factors)
    exposures = aggregate_exposures(compute_contract_exposures(chain, mode=mode))

    factors = factors.copy()
    factors["regime"] = regime.regime
    factors["option_direction_score"] = regime.option_direction_score
    factors["option_risk_score"] = regime.option_risk_score
    factors["vol_carry_score"] = regime.vol_carry_score
    factors["tail_risk_score"] = regime.tail_risk_score
    factors["recommended_beta_multiplier"] = regime.recommended_beta_multiplier
    factors["allow_short_vol"] = regime.allow_short_vol
    factors["prefer_option_structure"] = regime.prefer_option_structure
    factors["explanation"] = regime.explanation

    row = factors.iloc[0].to_dict()
    payload = {
        "date": pd.Timestamp(trade_date).strftime("%Y-%m-%d"),
        "product_group": product_group.upper(),
        "option_direction_score": regime.option_direction_score,
        "option_risk_score": regime.option_risk_score,
        "vol_carry_score": regime.vol_carry_score,
        "tail_risk_score": regime.tail_risk_score,
        "regime": regime.regime,
        "key_levels": {
            "spot": _json_float(row.get("spot")),
            "zero_gamma": _json_float(row.get("zero_gamma")),
            "put_wall": _json_float(row.get("put_wall")),
            "call_wall": _json_float(row.get("call_wall")),
            "max_gamma_strike": _json_float(row.get("max_gamma_strike")),
        },
        "exposures": {
            "gex_1pct": _json_float(exposures.get("gex_1pct")),
            "vanna_1vol": _json_float(exposures.get("vanna_1vol")),
            "charm_1day": _json_float(exposures.get("charm_1day")),
            "vega_1vol": _json_float(exposures.get("vega_1vol")),
        },
        "vol": {
            "iv_30d": _json_float(row.get("iv_30d")),
            "rv_20d": _json_float(row.get("rv_20d")),
            "vrp_30d": _json_float(row.get("vrp_30d")),
            "iv_percentile_252d": _json_float(row.get("iv_percentile_252d")),
        },
        "skew": {
            "put_skew_25d": _json_float(row.get("put_skew_25d")),
            "call_skew_25d": _json_float(row.get("call_skew_25d")),
            "risk_reversal_25d": _json_float(row.get("risk_reversal_25d")),
        },
        "recommended_overlay": {
            "beta_multiplier": regime.recommended_beta_multiplier,
            "allow_short_vol": regime.allow_short_vol,
            "prefer_option_structure": regime.prefer_option_structure,
        },
        "explanation": regime.explanation,
    }
    markdown = _markdown_summary(payload) if include_markdown else None
    plots = build_plot_datasets(chain, factors, mode=mode) if include_plots else None
    return factors, payload, markdown, plots


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate a daily A-share index option state report.")
    parser.add_argument("--date", required=True, help="Trade date, YYYY-MM-DD.")
    parser.add_argument("--product", required=True, choices=["SSE50", "CSI300", "CSI1000"], help="Product group.")
    parser.add_argument("--data-root", default="data/options", help="Root directory for localized option parquet data.")
    parser.add_argument("--mode", default=ExposureMode.DEALER_SHORT_OPTIONS.value, choices=[mode.value for mode in ExposureMode])
    parser.add_argument("--markdown", action="store_true", help="Print markdown summary after JSON.")
    args = parser.parse_args(argv)

    _, payload, markdown, _ = generate_daily_option_state(
        args.date,
        args.product,
        data_root=args.data_root,
        mode=args.mode,
        include_markdown=args.markdown,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.markdown and markdown:
        print()
        print(markdown)


def _markdown_summary(payload: dict[str, Any]) -> str:
    levels = payload["key_levels"]
    exposures = payload["exposures"]
    return "\n".join(
        [
            f"# {payload['product_group']} Option State - {payload['date']}",
            "",
            f"- Regime: {payload['regime']}",
            f"- Scores: direction {payload['option_direction_score']:.2f}, risk {payload['option_risk_score']:.2f}, carry {payload['vol_carry_score']:.2f}",
            f"- Key levels: spot {levels['spot']}, zero gamma {levels['zero_gamma']}, put wall {levels['put_wall']}, call wall {levels['call_wall']}",
            f"- Exposures: GEX 1% {exposures['gex_1pct']}, vanna 1vol {exposures['vanna_1vol']}, charm 1d {exposures['charm_1day']}",
            f"- Explanation: {payload['explanation']}",
        ]
    )


def _json_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


if __name__ == "__main__":
    main()
