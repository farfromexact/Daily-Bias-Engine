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

OVERSEAS_SYMBOL_WEIGHTS = {
    "SPX.GI": 0.80,
    "N225.GI": 0.10,
    "KS11.GI": 0.10,
}
ASHARE_STRUCTURE_SYMBOLS = {"000016.SH", "000300.SH", "000688.SH", "399006.SZ"}
FUNDING_RATE_SERIES = "DR007.IB"
YIELD_CURVE_SHORT_SERIES = "CGB10Y"
YIELD_CURVE_LONG_SERIES = "CGB30Y"


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
    prepared = prepared[prepared["date"].dt.weekday < 5]
    if prepared.empty:
        raise ValueError("Rates frame has no weekday observations.")
    pivot = prepared.pivot_table(index="date", columns="series", values="rate", aggfunc="mean")
    frames = []
    if FUNDING_RATE_SERIES in pivot:
        rate_change = pivot[FUNDING_RATE_SERIES].dropna().diff(5).fillna(0.0)
        rate_z = rolling_zscore(rate_change)
        frames.append(
            build_factor_frame(rate_change.index, "rates_change_5d", rate_change, rate_z,
                               directional_score(rate_z, polarity=-1.0), _asof_time(rates))
        )

    if {YIELD_CURVE_SHORT_SERIES, YIELD_CURVE_LONG_SERIES}.issubset(pivot.columns):
        slope = (pivot[YIELD_CURVE_LONG_SERIES] - pivot[YIELD_CURVE_SHORT_SERIES]).dropna()
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

    if not frames:
        raise ValueError("Rates contain neither DR007 nor the two government bond yields.")
    return validate_factor_frame(pd.concat(frames, ignore_index=True))


def calculate_etf_and_margin_flow(
    flow_data: pd.DataFrame,
    margin_financing: pd.DataFrame | None = None,
    trading_sessions: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """Keep turnover participation and independently reported ETF financing separate."""
    amount = daily_mean(flow_data, "amount")
    etf_flow = _pct_change(amount, periods=5)
    etf_z = rolling_zscore(etf_flow)
    turnover = build_factor_frame(
        etf_flow.index, "etf_flow_proxy", etf_flow, etf_z, directional_score(etf_z), _asof_time(flow_data),
    )
    if margin_financing is None or margin_financing.empty:
        return turnover

    sessions = trading_sessions if trading_sessions is not None else signal_sessions(flow_data)
    balances = margin_financing.pivot(index="date", columns="symbol", values="margin_balance")
    balances.index = pd.DatetimeIndex(balances.index).normalize()
    balances = balances.reindex(index=sessions, columns=["510300.SH", "510500.SH"])
    total = balances.sum(axis=1, min_count=2)
    change = total.pct_change(5, fill_method=None).replace([float("inf"), -float("inf")], float("nan"))
    z = rolling_zscore(change)
    # Reserve one full domestic session for publication. At T+2 09:20 the
    # T balance can be used without assuming a precise provider release time.
    dates = change.dropna().index.intersection(sessions[:-2])
    idx = sessions.get_indexer(dates)
    financing = build_factor_frame(
        dates, "margin_balance_momentum", change.loc[dates], z.loc[dates], directional_score(z.loc[dates]),
        "16:30:00", signal_dates=sessions.take(idx + 2),
    )
    financing["available_date"] = sessions.take(idx + 1)
    return pd.concat([turnover, financing], ignore_index=True)


def calculate_overseas_market(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Calculate overseas momentum and volatility pressure factors."""

    if ohlcv.empty or not {"date", "symbol", "close", "high", "low"}.issubset(ohlcv.columns):
        raise ValueError("Overseas frame must include date, symbol, close, high, and low.")

    prepared = ohlcv.copy()
    prepared["date"] = pd.to_datetime(prepared["date"]).dt.normalize()
    prepared = prepared.sort_values(["symbol", "date"])
    prepared["close"] = pd.to_numeric(prepared["close"], errors="coerce")
    prepared["high"] = pd.to_numeric(prepared["high"], errors="coerce")
    prepared["low"] = pd.to_numeric(prepared["low"], errors="coerce")
    prepared["symbol_momentum"] = prepared.groupby("symbol", sort=True)["close"].pct_change().fillna(0.0)
    prepared["symbol_volatility"] = ((prepared["high"] - prepared["low"]) / prepared["close"].replace(0.0, pd.NA)).fillna(0.0)
    prepared["symbol_weight"] = prepared["symbol"].map(OVERSEAS_SYMBOL_WEIGHTS).fillna(0.0)
    prepared = prepared[prepared["symbol_weight"] > 0.0].copy()
    if prepared.empty:
        raise ValueError("Overseas frame has no supported symbols.")

    momentum = _weighted_daily_mean(prepared, "symbol_momentum")
    momentum_z = rolling_zscore(momentum)

    volatility = _weighted_daily_mean(prepared, "symbol_volatility")
    volatility_z = rolling_zscore(volatility)

    asof = _asof_time(ohlcv)
    factors = validate_factor_frame(
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

    includes_us = factors["data_date"].isin(prepared.loc[prepared["symbol"].eq("SPX.GI"), "date"])
    us_dates = pd.DatetimeIndex(factors.loc[includes_us, "data_date"])
    us_close = (us_dates + pd.Timedelta(hours=16)).tz_localize("America/New_York").tz_convert("Asia/Shanghai")
    factors.loc[includes_us, "available_date"] = us_close.tz_localize(None).normalize()
    factors.loc[includes_us, "available_time"] = us_close.strftime("%H:%M:%S")
    return factors


def _weighted_daily_mean(frame: pd.DataFrame, value_column: str) -> pd.Series:
    weighted = frame.copy()
    weighted["_weighted_value"] = weighted[value_column] * weighted["symbol_weight"]
    grouped = weighted.groupby("date", sort=True)
    numerator = grouped["_weighted_value"].sum()
    denominator = grouped["symbol_weight"].sum().replace(0.0, pd.NA)
    return (numerator / denominator).fillna(0.0)


def calculate_ashare_market_structure(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Calculate market breadth and turnover momentum proxies."""

    if ohlcv.empty or not {"date", "symbol", "close", "open", "volume"}.issubset(ohlcv.columns):
        raise ValueError("A-share frame must include date, symbol, open, close, and volume.")

    prepared = ohlcv.copy()
    prepared["date"] = pd.to_datetime(prepared["date"]).dt.normalize()
    prepared = prepared[prepared["symbol"].isin(ASHARE_STRUCTURE_SYMBOLS)].copy()
    if prepared.empty:
        raise ValueError("A-share frame has no supported structure symbols.")
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


def signal_sessions(index_ohlcv: pd.DataFrame, calendar: pd.Series | None = None) -> pd.DatetimeIndex:
    """Limit signals to benchmark history and one upcoming domestic session."""
    observed = pd.DatetimeIndex(index_ohlcv["date"]).normalize().unique().sort_values()
    if observed.empty:
        raise ValueError("No benchmark trading dates in the snapshot.")
    last_close = observed[-1]
    if calendar is None:
        # Older snapshots only recorded bars. The first future date is an estimate.
        return observed.union([last_close + pd.offsets.BDay(1)])
    official = pd.DatetimeIndex(calendar).normalize().dropna().unique().sort_values()
    future = official[official > last_close]
    if future.empty:
        raise ValueError("Wind calendar does not cover the session after the last benchmark bar.")
    if not observed[observed >= official[0]].isin(official).all():
        raise ValueError("Benchmark contains a close outside the Wind SSE calendar.")
    return observed[observed < official[0]].union(official[official <= future[0]]).sort_values()


def calculate_all_features(
    index_ohlcv: pd.DataFrame,
    futures_ohlcv: pd.DataFrame,
    open_interest: pd.DataFrame,
    rates: pd.DataFrame,
    etf_flow: pd.DataFrame,
    overseas_ohlcv: pd.DataFrame,
    ashare_ohlcv: pd.DataFrame,
    trading_sessions: pd.DatetimeIndex | None = None,
    margin_financing: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Run all representative v1 calculators and return one factor table."""

    sessions = trading_sessions if trading_sessions is not None else signal_sessions(index_ohlcv)
    rates = rates.loc[pd.to_datetime(rates["date"]).dt.normalize().isin(sessions)]
    factors = pd.concat(
        [
            calculate_equity_index_futures_structure(index_ohlcv, futures_ohlcv, open_interest),
            calculate_rates_and_bond_futures(rates),
            calculate_etf_and_margin_flow(etf_flow, margin_financing, sessions),
            calculate_overseas_market(overseas_ohlcv),
            calculate_ashare_market_structure(ashare_ohlcv),
        ],
        ignore_index=True,
    )
    # Foreign markets can trade through a mainland holiday. Use their latest
    # available close once, on the first domestic session after that close.
    positions = sessions.searchsorted(factors["data_date"], side="right")
    financing = factors["factor_name"].eq("margin_balance_momentum")
    positions[financing] = sessions.searchsorted(factors.loc[financing, "available_date"], side="right")
    covered = positions < len(sessions)
    factors = factors.loc[covered].copy()
    factors["date"] = sessions.take(positions[covered])
    factors["signal_date"] = factors["date"]
    factors = factors.sort_values("data_date").drop_duplicates(["date", "factor_name"], keep="last")
    return validate_factor_frame(factors)
