"""Representative v1 factor calculators."""

from __future__ import annotations

import pandas as pd

from daily_bias_engine.features.base import (
    build_factor_frame,
    daily_mean,
    directional_score,
    rolling_zscore,
    validate_factor_frame,
)


def _asof_time(*frames: pd.DataFrame) -> str:
    for frame in frames:
        if "asof_time" in frame.columns and not frame.empty:
            return str(frame["asof_time"].iloc[-1])
    return "16:30:00"


def _pct_change(values: pd.Series, periods: int = 1) -> pd.Series:
    return values.pct_change(periods=periods).replace([float("inf"), float("-inf")], 0.0).fillna(0.0)


def calculate_equity_index_futures_structure(
    index_ohlcv: pd.DataFrame,
    futures_ohlcv: pd.DataFrame,
    open_interest: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate equity index futures basis and open-interest momentum factors."""

    index_close = daily_mean(index_ohlcv, "close")
    futures_close = daily_mean(futures_ohlcv, "close")
    dates = index_close.index.intersection(futures_close.index)
    basis = (futures_close.loc[dates] / index_close.loc[dates] - 1.0).fillna(0.0)
    basis_z = rolling_zscore(basis)

    oi = daily_mean(open_interest, "open_interest")
    oi_dates = basis.index.intersection(oi.index)
    oi_momentum = _pct_change(oi.loc[oi_dates], periods=5)
    oi_z = rolling_zscore(oi_momentum)

    asof = _asof_time(index_ohlcv, futures_ohlcv, open_interest)
    return validate_factor_frame(
        pd.concat(
            [
                build_factor_frame(
                    basis.index,
                    "equity_index_futures_basis",
                    basis,
                    basis_z,
                    directional_score(basis_z, polarity=1.0),
                    asof,
                ),
                build_factor_frame(
                    oi_momentum.index,
                    "futures_open_interest_momentum",
                    oi_momentum,
                    oi_z,
                    directional_score(oi_z, polarity=1.0),
                    asof,
                ),
            ],
            ignore_index=True,
        )
    )


def calculate_rates_and_bond_futures(rates: pd.DataFrame) -> pd.DataFrame:
    """Calculate representative rates pressure and curve slope factors."""

    if rates.empty or not {"date", "series", "rate"}.issubset(rates.columns):
        raise ValueError("Rates frame must include date, series, and rate.")

    prepared = rates.copy()
    prepared["date"] = pd.to_datetime(prepared["date"]).dt.normalize()
    pivot = prepared.pivot_table(index="date", columns="series", values="rate", aggfunc="mean")
    average_rate = pivot.mean(axis=1)
    rate_change = average_rate.diff(5).fillna(0.0)
    rate_z = rolling_zscore(rate_change)

    frames = [
        build_factor_frame(
            rate_change.index,
            "rates_change_5d",
            rate_change,
            rate_z,
            directional_score(rate_z, polarity=-1.0),
            _asof_time(rates),
        )
    ]

    if pivot.shape[1] >= 2:
        ordered = list(pivot.columns)
        slope = (pivot[ordered[-1]] - pivot[ordered[0]]).fillna(0.0)
        slope_z = rolling_zscore(slope)
        frames.append(
            build_factor_frame(
                slope.index,
                "yield_curve_slope",
                slope,
                slope_z,
                directional_score(slope_z, polarity=1.0),
                _asof_time(rates),
            )
        )

    return validate_factor_frame(pd.concat(frames, ignore_index=True))


def calculate_etf_and_margin_flow(flow_data: pd.DataFrame) -> pd.DataFrame:
    """Calculate ETF flow and margin-balance proxy factors.

    If ``margin_balance`` is absent, amount momentum is used as a deterministic
    proxy for demo and test data.
    """

    amount = daily_mean(flow_data, "amount")
    etf_flow = _pct_change(amount, periods=5)
    etf_z = rolling_zscore(etf_flow)

    if "margin_balance" in flow_data.columns:
        margin_base = daily_mean(flow_data, "margin_balance")
    else:
        margin_base = amount.rolling(window=5, min_periods=1).mean()
    margin_momentum = _pct_change(margin_base, periods=5)
    margin_z = rolling_zscore(margin_momentum)

    asof = _asof_time(flow_data)
    return validate_factor_frame(
        pd.concat(
            [
                build_factor_frame(
                    etf_flow.index,
                    "etf_flow_proxy",
                    etf_flow,
                    etf_z,
                    directional_score(etf_z, polarity=1.0),
                    asof,
                ),
                build_factor_frame(
                    margin_momentum.index,
                    "margin_balance_momentum",
                    margin_momentum,
                    margin_z,
                    directional_score(margin_z, polarity=1.0),
                    asof,
                ),
            ],
            ignore_index=True,
        )
    )


def calculate_overseas_market(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Calculate overseas momentum and volatility pressure factors."""

    close = daily_mean(ohlcv, "close")
    high = daily_mean(ohlcv, "high")
    low = daily_mean(ohlcv, "low")
    momentum = close.pct_change(1).fillna(0.0)
    momentum_z = rolling_zscore(momentum)

    volatility = ((high - low) / close.replace(0.0, pd.NA)).fillna(0.0)
    volatility_z = rolling_zscore(volatility)

    asof = _asof_time(ohlcv)
    return validate_factor_frame(
        pd.concat(
            [
                build_factor_frame(
                    momentum.index,
                    "overseas_market_momentum",
                    momentum,
                    momentum_z,
                    directional_score(momentum_z, polarity=1.0),
                    asof,
                ),
                build_factor_frame(
                    volatility.index,
                    "overseas_volatility_pressure",
                    volatility,
                    volatility_z,
                    directional_score(volatility_z, polarity=-1.0),
                    asof,
                ),
            ],
            ignore_index=True,
        )
    )


def calculate_ashare_market_structure(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Calculate market breadth and turnover momentum proxies."""

    if ohlcv.empty or not {"date", "symbol", "close", "open", "volume"}.issubset(ohlcv.columns):
        raise ValueError("A-share frame must include date, symbol, open, close, and volume.")

    prepared = ohlcv.copy()
    prepared["date"] = pd.to_datetime(prepared["date"]).dt.normalize()
    prepared["is_up"] = prepared["close"] > prepared["open"]
    breadth = prepared.groupby("date", sort=True)["is_up"].mean() - 0.5
    breadth_z = rolling_zscore(breadth)

    turnover = prepared.groupby("date", sort=True)["volume"].mean()
    turnover_momentum = _pct_change(turnover, periods=5)
    turnover_z = rolling_zscore(turnover_momentum)

    asof = _asof_time(ohlcv)
    return validate_factor_frame(
        pd.concat(
            [
                build_factor_frame(
                    breadth.index,
                    "ashare_breadth_proxy",
                    breadth,
                    breadth_z,
                    directional_score(breadth_z, polarity=1.0),
                    asof,
                ),
                build_factor_frame(
                    turnover_momentum.index,
                    "ashare_turnover_momentum",
                    turnover_momentum,
                    turnover_z,
                    directional_score(turnover_z, polarity=1.0),
                    asof,
                ),
            ],
            ignore_index=True,
        )
    )


def calculate_all_features(
    index_ohlcv: pd.DataFrame,
    futures_ohlcv: pd.DataFrame,
    open_interest: pd.DataFrame,
    rates: pd.DataFrame,
    etf_flow: pd.DataFrame,
    overseas_ohlcv: pd.DataFrame,
    ashare_ohlcv: pd.DataFrame,
) -> pd.DataFrame:
    """Run all representative v1 calculators and return one factor table."""

    return validate_factor_frame(
        pd.concat(
            [
                calculate_equity_index_futures_structure(index_ohlcv, futures_ohlcv, open_interest),
                calculate_rates_and_bond_futures(rates),
                calculate_etf_and_margin_flow(etf_flow),
                calculate_overseas_market(overseas_ohlcv),
                calculate_ashare_market_structure(ashare_ohlcv),
            ],
            ignore_index=True,
        )
    )
