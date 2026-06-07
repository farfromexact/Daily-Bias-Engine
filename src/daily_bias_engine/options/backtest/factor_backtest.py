"""No-lookahead option factor backtester."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from daily_bias_engine.options.backtest.metrics import drawdown_stats


@dataclass(frozen=True)
class FactorBacktester:
    factor_column: str
    return_column: str = "forward_return"
    quantiles: int = 5

    def run(self, factors: pd.DataFrame, target_returns: pd.DataFrame) -> dict[str, Any]:
        aligned = self.align(factors, target_returns)
        if aligned.empty:
            return self._empty_result(aligned)
        factor = pd.to_numeric(aligned[self.factor_column], errors="coerce")
        returns = pd.to_numeric(aligned[self.return_column], errors="coerce")
        valid = pd.DataFrame({"factor": factor, "returns": returns}).dropna()
        if valid.empty:
            return self._empty_result(aligned)

        ic = float(valid["factor"].corr(valid["returns"])) if len(valid) > 1 else 0.0
        rank_ic = float(valid["factor"].rank().corr(valid["returns"].rank())) if len(valid) > 1 else 0.0
        quantile_returns = self._quantile_returns(valid)
        strategy_returns = np.sign(valid["factor"]) * valid["returns"]
        return {
            "observations": int(len(valid)),
            "ic": 0.0 if np.isnan(ic) else ic,
            "rank_ic": 0.0 if np.isnan(rank_ic) else rank_ic,
            "quantile_returns": quantile_returns,
            "conditional_forward_returns": {
                "positive_factor": float(valid.loc[valid["factor"] > 0.0, "returns"].mean()) if (valid["factor"] > 0.0).any() else 0.0,
                "negative_factor": float(valid.loc[valid["factor"] < 0.0, "returns"].mean()) if (valid["factor"] < 0.0).any() else 0.0,
            },
            "conditional_realized_vol": {
                "positive_factor": float(valid.loc[valid["factor"] > 0.0, "returns"].std(ddof=0) * np.sqrt(252.0)) if (valid["factor"] > 0.0).any() else 0.0,
                "negative_factor": float(valid.loc[valid["factor"] < 0.0, "returns"].std(ddof=0) * np.sqrt(252.0)) if (valid["factor"] < 0.0).any() else 0.0,
            },
            "hit_rate": float((np.sign(valid["factor"]) == np.sign(valid["returns"])).mean()),
            "drawdown_stats": drawdown_stats(strategy_returns),
            "aligned": aligned,
        }

    def align(self, factors: pd.DataFrame, target_returns: pd.DataFrame) -> pd.DataFrame:
        if self.factor_column not in factors.columns:
            raise ValueError(f"Factor frame missing {self.factor_column}.")
        if self.return_column not in target_returns.columns:
            raise ValueError(f"Target return frame missing {self.return_column}.")
        prepared = factors.copy()
        returns = target_returns.copy()
        if "data_date" in prepared.columns:
            prepared["factor_data_date"] = pd.to_datetime(prepared["data_date"]).dt.normalize()
        elif "trade_date" in prepared.columns:
            prepared["factor_data_date"] = pd.to_datetime(prepared["trade_date"]).dt.normalize()
        elif "date" in prepared.columns:
            prepared["factor_data_date"] = pd.to_datetime(prepared["date"]).dt.normalize()
        else:
            raise ValueError("Factor frame must include date, trade_date, or data_date.")

        if "signal_date" in prepared.columns:
            prepared["join_date"] = pd.to_datetime(prepared["signal_date"]).dt.normalize()
        elif "date" in prepared.columns and "data_date" in prepared.columns:
            candidate = pd.to_datetime(prepared["date"]).dt.normalize()
            prepared["join_date"] = candidate.where(candidate > prepared["factor_data_date"], prepared["factor_data_date"] + pd.offsets.BDay(1))
        else:
            prepared["join_date"] = prepared["factor_data_date"] + pd.offsets.BDay(1)

        if (prepared["factor_data_date"] >= prepared["join_date"]).any():
            raise ValueError("Lookahead detected: factor data_date must be before target return date.")

        returns["join_date"] = pd.to_datetime(returns["date"]).dt.normalize()
        aligned = prepared.merge(returns, on="join_date", how="inner", suffixes=("", "_target"))
        if aligned.empty:
            return aligned
        if (aligned["factor_data_date"] >= aligned["join_date"]).any():
            raise ValueError("Lookahead detected after factor/return alignment.")
        return aligned.sort_values("join_date").reset_index(drop=True)

    def _quantile_returns(self, valid: pd.DataFrame) -> dict[str, float]:
        if len(valid) < self.quantiles:
            return {}
        try:
            buckets = pd.qcut(valid["factor"], q=self.quantiles, duplicates="drop")
        except ValueError:
            return {}
        grouped = valid.groupby(buckets, observed=False)["returns"].mean()
        return {str(label): float(value) for label, value in grouped.items()}

    def _empty_result(self, aligned: pd.DataFrame) -> dict[str, Any]:
        return {
            "observations": 0,
            "ic": 0.0,
            "rank_ic": 0.0,
            "quantile_returns": {},
            "conditional_forward_returns": {},
            "conditional_realized_vol": {},
            "hit_rate": 0.0,
            "drawdown_stats": {"max_drawdown": 0.0, "avg_drawdown": 0.0},
            "aligned": aligned,
        }
