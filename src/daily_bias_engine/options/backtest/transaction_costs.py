"""Transaction-cost placeholders for option strategies."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class OptionTransactionCostModel:
    broker_fee_per_contract: float = 1.5
    hedge_slippage_bps: float = 1.0
    min_half_spread: float = 0.001

    def estimate_option_cost(self, legs: pd.DataFrame) -> float:
        if legs.empty:
            return 0.0
        bid = pd.to_numeric(legs.get("bid"), errors="coerce")
        ask = pd.to_numeric(legs.get("ask"), errors="coerce")
        half_spread = ((ask - bid) / 2.0).clip(lower=self.min_half_spread).fillna(self.min_half_spread)
        multiplier = pd.to_numeric(legs.get("multiplier_or_contract_unit"), errors="coerce").fillna(1.0)
        quantity = pd.to_numeric(legs.get("quantity", 1.0), errors="coerce").abs().fillna(1.0)
        spread_cost = float((half_spread * multiplier * quantity).sum())
        fees = float(quantity.sum() * self.broker_fee_per_contract)
        return spread_cost + fees

    def estimate_hedge_cost(self, notional: float) -> float:
        return abs(float(notional)) * self.hedge_slippage_bps / 10_000.0
