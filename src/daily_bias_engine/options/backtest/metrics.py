"""Backtest metrics shared by option overlay tests."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def performance_metrics(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series | None = None,
    turnover: pd.Series | None = None,
) -> dict[str, Any]:
    returns = pd.to_numeric(strategy_returns, errors="coerce").fillna(0.0)
    if returns.empty:
        return _empty_metrics()
    equity = (1.0 + returns).cumprod()
    annualized_return = float(equity.iloc[-1] ** (252.0 / max(len(returns), 1)) - 1.0)
    annualized_vol = float(returns.std(ddof=0) * np.sqrt(252.0))
    sharpe = annualized_return / annualized_vol if annualized_vol > 0.0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    calmar = annualized_return / abs(max_drawdown) if max_drawdown < 0.0 else 0.0
    hit_rate = float((returns > 0.0).mean())
    tail_loss = float(returns.quantile(0.05))
    downside_capture = 0.0
    if benchmark_returns is not None:
        benchmark = pd.to_numeric(benchmark_returns, errors="coerce").reindex(returns.index).fillna(0.0)
        downside = benchmark < 0.0
        if downside.any() and abs(float(benchmark[downside].sum())) > 0.0:
            downside_capture = float(returns[downside].sum() / benchmark[downside].sum())
    return {
        "observations": int(len(returns)),
        "annualized_return": annualized_return,
        "annualized_vol": annualized_vol,
        "sharpe": float(sharpe),
        "max_drawdown": max_drawdown,
        "calmar": float(calmar),
        "turnover": float(pd.to_numeric(turnover, errors="coerce").fillna(0.0).mean()) if turnover is not None else 0.0,
        "hit_rate": hit_rate,
        "downside_capture": downside_capture,
        "tail_loss": tail_loss,
    }


def drawdown_stats(returns: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    equity = (1.0 + clean).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return {
        "max_drawdown": float(drawdown.min()) if not drawdown.empty else 0.0,
        "avg_drawdown": float(drawdown[drawdown < 0.0].mean()) if (drawdown < 0.0).any() else 0.0,
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "observations": 0,
        "annualized_return": 0.0,
        "annualized_vol": 0.0,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "calmar": 0.0,
        "turnover": 0.0,
        "hit_rate": 0.0,
        "downside_capture": 0.0,
        "tail_loss": 0.0,
    }
