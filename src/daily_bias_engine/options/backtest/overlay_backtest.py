"""Overlay option scores onto an existing daily bias signal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from daily_bias_engine.options.backtest.metrics import performance_metrics


@dataclass(frozen=True)
class OverlayBacktester:
    option_lambda: float = 0.35
    risk_lambda: float = 0.25

    def run(
        self,
        base_signals: pd.DataFrame,
        option_signals: pd.DataFrame,
        returns: pd.DataFrame,
    ) -> dict[str, Any]:
        required_base = {"date", "base_signal"}
        required_option = {"date", "option_direction_score", "option_risk_score"}
        required_returns = {"date", "return"}
        _require(base_signals, required_base, "base_signals")
        _require(option_signals, required_option, "option_signals")
        _require(returns, required_returns, "returns")

        base = base_signals.copy()
        option = option_signals.copy()
        ret = returns.copy()
        for frame in (base, option, ret):
            frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()

        joined = base.merge(option, on="date", how="inner").merge(ret, on="date", how="inner")
        if joined.empty:
            return {"joined": joined, "metrics": {}}
        risk_adjustment = np.sign(joined["base_signal"].fillna(0.0)) * joined["option_risk_score"].fillna(0.0)
        joined["final_signal"] = (
            joined["base_signal"].fillna(0.0)
            + self.option_lambda * joined["option_direction_score"].fillna(0.0)
            - self.risk_lambda * risk_adjustment
        ).clip(-1.0, 1.0)
        joined["base_strategy_return"] = joined["base_signal"].shift(1).fillna(0.0) * joined["return"]
        joined["option_strategy_return"] = joined["option_direction_score"].shift(1).fillna(0.0) * joined["return"]
        joined["combined_strategy_return"] = joined["final_signal"].shift(1).fillna(0.0) * joined["return"]
        joined["turnover"] = joined["final_signal"].diff().abs().fillna(0.0)
        metrics = {
            "base_engine_only": performance_metrics(joined["base_strategy_return"], joined["return"], joined["base_signal"].diff().abs()),
            "option_overlay_only": performance_metrics(joined["option_strategy_return"], joined["return"], joined["option_direction_score"].diff().abs()),
            "combined_engine": performance_metrics(joined["combined_strategy_return"], joined["return"], joined["turnover"]),
        }
        return {"joined": joined, "metrics": metrics}


def _require(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"{name} missing columns: {sorted(missing)}")
