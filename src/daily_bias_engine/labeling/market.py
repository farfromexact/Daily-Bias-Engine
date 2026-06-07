"""Market outcome labeling."""

from __future__ import annotations

import pandas as pd


def label_market_results(
    ohlcv: pd.DataFrame,
    symbol: str | None = None,
    trend_body_ratio_threshold: float = 0.60,
    trend_range_quantile: float = 0.60,
    close_location_threshold: float = 0.20,
    big_loss_threshold: float = -0.015,
    tail_loss_quantile: float = 0.10,
    choppy_return_abs_max: float = 0.003,
    choppy_range_min: float = 0.01,
) -> pd.DataFrame:
    """Label realized market outcomes from daily OHLCV bars."""

    bars = _prepare_symbol_bars(ohlcv, symbol)
    bars["open_to_close_return"] = (bars["close"] / bars["open"].replace(0.0, pd.NA) - 1.0).fillna(0.0)
    bars["close_to_close_return"] = bars.groupby("symbol")["close"].pct_change().fillna(0.0)
    bars["intraday_range"] = ((bars["high"] - bars["low"]) / bars["close"].replace(0.0, pd.NA)).fillna(0.0)
    price_range = (bars["high"] - bars["low"]).replace(0.0, pd.NA)
    bars["body_ratio"] = ((bars["close"] - bars["open"]).abs() / price_range).fillna(0.0)
    bars["close_location"] = ((bars["close"] - bars["low"]) / price_range).fillna(0.5)

    market = (
        bars.groupby("date", sort=True)
        .agg(
            market_composite_return=("close_to_close_return", "mean"),
            composite_open_to_close_return=("open_to_close_return", "mean"),
            intraday_range=("intraday_range", "mean"),
            body_ratio=("body_ratio", "mean"),
            close_location=("close_location", "mean"),
        )
        .reset_index()
    )
    market["market_return"] = market["market_composite_return"]
    market["open_close_direction"] = market["composite_open_to_close_return"].map(_direction)

    range_threshold = (
        market["intraday_range"]
        .rolling(window=60, min_periods=3)
        .quantile(trend_range_quantile)
        .fillna(market["intraday_range"].expanding(min_periods=1).quantile(trend_range_quantile))
    )
    closes_near_extreme = (
        (market["close_location"] <= close_location_threshold)
        | (market["close_location"] >= 1.0 - close_location_threshold)
    )
    market["trend_day_flag"] = (
        (market["body_ratio"] >= trend_body_ratio_threshold)
        & (market["intraday_range"] >= range_threshold)
        & closes_near_extreme
    )
    market["up_trend_day_flag"] = market["trend_day_flag"] & (market["composite_open_to_close_return"] > 0)
    market["down_trend_day_flag"] = market["trend_day_flag"] & (market["composite_open_to_close_return"] < 0)
    market["big_loss_day_flag"] = market["market_composite_return"] <= big_loss_threshold
    market["big_loss_day_flag"] = market["big_loss_day_flag"] | _tail_loss_flag(bars, tail_loss_quantile)
    market["choppy_day_flag"] = (
        (market["market_return"].abs() <= choppy_return_abs_max)
        & (market["intraday_range"] >= choppy_range_min)
        & ~market["trend_day_flag"]
    )

    market = market.merge(_wide_return_columns(bars), on="date", how="left")

    columns = [
        "date",
        "market_return",
        "market_composite_return",
        "intraday_range",
        "open_close_direction",
        "body_ratio",
        "close_location",
        "trend_day_flag",
        "up_trend_day_flag",
        "down_trend_day_flag",
        "big_loss_day_flag",
        "choppy_day_flag",
    ]
    return market[columns + [column for column in market.columns if column.endswith("_return") and column not in columns]]


def _prepare_symbol_bars(ohlcv: pd.DataFrame, symbol: str | None) -> pd.DataFrame:
    required = {"date", "open", "high", "low", "close", "symbol"}
    if ohlcv.empty or not required.issubset(ohlcv.columns):
        raise ValueError("OHLCV frame must include date, symbol, open, high, low, and close.")

    frame = ohlcv.copy()
    if symbol is not None:
        frame = frame[frame["symbol"] == symbol]
        if frame.empty:
            raise ValueError(f"No OHLCV rows found for symbol {symbol}.")

    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    return (
        frame.groupby(["date", "symbol"], sort=True)
        .agg(open=("open", "mean"), high=("high", "mean"), low=("low", "mean"), close=("close", "mean"))
        .reset_index()
    )


def _direction(value: float) -> str:
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def _tail_loss_flag(bars: pd.DataFrame, tail_loss_quantile: float) -> pd.Series:
    pivot = bars.pivot(index="date", columns="symbol", values="open_to_close_return")
    if pivot.empty:
        return pd.Series(False, index=pd.Index([], name="date"))
    tail_thresholds = pivot.rolling(window=120, min_periods=3).quantile(tail_loss_quantile)
    tail_hits = (pivot <= tail_thresholds).sum(axis=1)
    return (tail_hits >= 2).rename("big_loss_tail_flag").reset_index()["big_loss_tail_flag"]


def _wide_return_columns(bars: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "IF.CFE": "IF_open_to_close_return",
        "IH.CFE": "IH_open_to_close_return",
        "IC.CFE": "IC_open_to_close_return",
        "IM.CFE": "IM_open_to_close_return",
        "000300.SH": "CSI300_return",
        "000905.SH": "CSI500_return",
        "000852.SH": "CSI1000_return",
    }
    output = pd.DataFrame({"date": sorted(bars["date"].unique())})
    for symbol, column in aliases.items():
        symbol_frame = bars[bars["symbol"] == symbol]
        if symbol_frame.empty:
            continue
        value_column = "open_to_close_return" if column.endswith("open_to_close_return") else "close_to_close_return"
        output = output.merge(symbol_frame[["date", value_column]].rename(columns={value_column: column}), on="date", how="left")
    return output
