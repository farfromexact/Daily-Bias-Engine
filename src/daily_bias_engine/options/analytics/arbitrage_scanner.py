"""Relative-value scanners for option state outputs."""

from __future__ import annotations

import pandas as pd


OUTPUT_COLUMNS = [
    "product_group",
    "instruments",
    "signal_name",
    "z_score",
    "expected_direction",
    "required_hedge",
    "estimated_transaction_cost",
    "liquidity_score",
    "risk_notes",
]


def scan_option_arbitrage(factors: pd.DataFrame, z_threshold: float = 1.5) -> pd.DataFrame:
    """Flag relative-value opportunities from product-level option factors.

    These are diagnostics, not risk-free arbitrage claims.
    """

    if factors.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    rows: list[dict[str, object]] = []
    rows.extend(_cross_index_vol(factors, z_threshold))
    rows.extend(_calendar_spread(factors, z_threshold))
    rows.extend(_skew_richness(factors, z_threshold))
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def synthetic_forward_parity_scan(chain: pd.DataFrame, tolerance_bps: float = 25.0) -> pd.DataFrame:
    """Scan same-strike call/put pairs for synthetic-forward deviations."""

    from daily_bias_engine.options.analytics.pricing import synthetic_forward_from_put_call

    rows = []
    required = {"option_type", "strike", "expiry_date", "mid", "risk_free_rate", "year_fraction", "underlying_price"}
    if chain.empty or not required.issubset(chain.columns):
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    pivot = chain.pivot_table(index=["product_group", "venue", "expiry_date", "strike"], columns="option_type", values="mid", aggfunc="mean").dropna()
    for index, prices in pivot.iterrows():
        product_group, venue, expiry, strike = index
        sample = chain[(chain["venue"] == venue) & (chain["expiry_date"] == expiry) & (chain["strike"] == strike)].iloc[0]
        forward = synthetic_forward_from_put_call(prices["call"], prices["put"], strike, sample["year_fraction"], sample["risk_free_rate"])
        spot = float(sample["underlying_price"])
        deviation_bps = (forward / spot - 1.0) * 10_000.0
        if abs(deviation_bps) >= tolerance_bps:
            rows.append(
                {
                    "product_group": product_group,
                    "instruments": f"{venue} call/put synthetic",
                    "signal_name": "synthetic_forward_put_call_parity",
                    "z_score": deviation_bps / tolerance_bps,
                    "expected_direction": "sell rich synthetic forward" if deviation_bps > 0 else "buy cheap synthetic forward",
                    "required_hedge": "underlying ETF/index future delta hedge",
                    "estimated_transaction_cost": "half-spread plus hedge slippage",
                    "liquidity_score": 0.5,
                    "risk_notes": "Not risk-free: exercise, funding, borrow, dividends, execution, and margin matter.",
                }
            )
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def _cross_index_vol(factors: pd.DataFrame, z_threshold: float) -> list[dict[str, object]]:
    rows = []
    if not {"product_group", "iv_30d", "rv_20d"}.issubset(factors.columns) or len(factors) < 2:
        return rows
    current = factors.set_index("product_group")
    for left, right in [("CSI1000", "CSI300"), ("CSI300", "SSE50")]:
        if left not in current.index or right not in current.index:
            continue
        iv_spread = float(current.loc[left, "iv_30d"] - current.loc[right, "iv_30d"])
        rv_spread = float(current.loc[left, "rv_20d"] - current.loc[right, "rv_20d"])
        z_score = iv_spread - rv_spread
        if abs(z_score) >= z_threshold:
            rows.append(_row(left, f"{left} vs {right}", "cross_index_vol_relative_value", z_score, "sell rich vol / buy cheap vol"))
    return rows


def _calendar_spread(factors: pd.DataFrame, z_threshold: float) -> list[dict[str, object]]:
    rows = []
    for _, row in factors.iterrows():
        value = float(row.get("term_structure_30d_7d", 0.0) or 0.0)
        z_score = value / 0.03 if value else 0.0
        if abs(z_score) >= z_threshold:
            rows.append(_row(row.get("product_group", ""), "front vs back tenor", "calendar_spread_iv_z", z_score, "sell steep tenor / buy flat tenor"))
    return rows


def _skew_richness(factors: pd.DataFrame, z_threshold: float) -> list[dict[str, object]]:
    rows = []
    for _, row in factors.iterrows():
        z_score = float(row.get("put_skew_z", 0.0) or 0.0)
        if abs(z_score) >= z_threshold:
            rows.append(_row(row.get("product_group", ""), "25d put skew", "skew_relative_value", z_score, "sell rich put skew" if z_score > 0 else "buy cheap put skew"))
    return rows


def _row(product_group: object, instruments: str, signal_name: str, z_score: float, expected_direction: str) -> dict[str, object]:
    return {
        "product_group": str(product_group),
        "instruments": instruments,
        "signal_name": signal_name,
        "z_score": float(z_score),
        "expected_direction": expected_direction,
        "required_hedge": "delta and vega hedge where tradable",
        "estimated_transaction_cost": "half-spread plus fees placeholder",
        "liquidity_score": 0.5,
        "risk_notes": "Scanner output is a flag only; liquidity, funding, margin, model, and execution risks remain.",
    }
