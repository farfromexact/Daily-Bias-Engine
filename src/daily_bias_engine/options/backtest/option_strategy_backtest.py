"""Basic option strategy backtest scaffolding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from daily_bias_engine.options.backtest.transaction_costs import OptionTransactionCostModel


@dataclass(frozen=True)
class OptionStrategyBacktester:
    cost_model: OptionTransactionCostModel = OptionTransactionCostModel()

    def select_long_atm_straddle(self, chain: pd.DataFrame) -> pd.DataFrame:
        return self._atm_pair(chain).assign(quantity=1.0)

    def select_short_atm_straddle(self, chain: pd.DataFrame) -> pd.DataFrame:
        return self._atm_pair(chain).assign(quantity=-1.0)

    def estimate_entry(self, legs: pd.DataFrame) -> dict[str, Any]:
        if legs.empty:
            return {"premium": 0.0, "transaction_cost": 0.0, "capital_usage": 0.0}
        premium = float((legs["mid"] * legs["multiplier_or_contract_unit"] * legs["quantity"]).sum())
        transaction_cost = self.cost_model.estimate_option_cost(legs)
        capital_usage = float(abs(premium) + transaction_cost)
        return {"premium": premium, "transaction_cost": transaction_cost, "capital_usage": capital_usage}

    def pnl_attribution_placeholder(self, legs: pd.DataFrame, next_chain: pd.DataFrame) -> dict[str, float]:
        if legs.empty or next_chain.empty:
            return {"delta_pnl": 0.0, "gamma_pnl": 0.0, "theta_pnl": 0.0, "vega_pnl": 0.0, "residual": 0.0}
        merged = legs[["option_code", "quantity", "mid", "delta", "gamma", "theta", "vega", "multiplier_or_contract_unit"]].merge(
            next_chain[["option_code", "mid", "underlying_price", "implied_vol"]],
            on="option_code",
            how="inner",
            suffixes=("", "_next"),
        )
        if merged.empty:
            return {"delta_pnl": 0.0, "gamma_pnl": 0.0, "theta_pnl": 0.0, "vega_pnl": 0.0, "residual": 0.0}
        option_pnl = (merged["mid_next"] - merged["mid"]) * merged["quantity"] * merged["multiplier_or_contract_unit"]
        total = float(option_pnl.sum())
        theta_pnl = float((merged["theta"] * merged["quantity"] * merged["multiplier_or_contract_unit"]).sum())
        return {"delta_pnl": 0.0, "gamma_pnl": 0.0, "theta_pnl": theta_pnl, "vega_pnl": 0.0, "residual": total - theta_pnl}

    def _atm_pair(self, chain: pd.DataFrame) -> pd.DataFrame:
        if chain.empty:
            return chain.copy()
        frame = chain.copy()
        frame["atm_distance"] = (frame["strike"] / frame["underlying_price"] - 1.0).abs()
        expiry = frame.loc[frame["dte_calendar"].sub(30).abs().idxmin(), "expiry_date"]
        subset = frame[frame["expiry_date"] == expiry]
        strike = subset.loc[subset["atm_distance"].idxmin(), "strike"]
        return subset[subset["strike"] == strike].copy()
