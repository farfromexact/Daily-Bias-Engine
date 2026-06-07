"""Normalize raw option contracts, quotes, underlyings, and rates."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from daily_bias_engine.options.analytics.calendar import calendar_days_to_expiry, trading_days_to_expiry, year_fraction
from daily_bias_engine.options.analytics.pricing import implied_volatility
from daily_bias_engine.options.data.wind_client import OptionWindClient

NORMALIZED_OPTION_COLUMNS = [
    "trade_date",
    "option_code",
    "product_group",
    "venue",
    "underlying_code",
    "reference_index_code",
    "option_type",
    "strike",
    "expiry_date",
    "dte_calendar",
    "dte_trading",
    "year_fraction",
    "multiplier_or_contract_unit",
    "settlement_type",
    "option_style",
    "adjusted_contract_flag",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "volume",
    "open_interest",
    "bid",
    "ask",
    "mid",
    "underlying_price",
    "reference_index_level",
    "risk_free_rate",
    "dividend_yield",
    "implied_vol",
    "implied_vol_source",
    "asof_time",
    "source",
]


def load_normalized_chain(
    client: OptionWindClient,
    product_group: str,
    trade_date: str | pd.Timestamp,
) -> pd.DataFrame:
    """Fetch and normalize a full option chain for one product group and date."""

    contracts = client.get_option_contracts(product_group, trade_date)
    if contracts.empty:
        raise ValueError(f"No option contracts returned for {product_group} on {trade_date}.")
    eod = client.get_option_eod(contracts["option_code"].astype(str).tolist(), trade_date)
    underlying = client.get_underlying_eod(sorted(contracts["underlying_code"].astype(str).unique()), trade_date)
    index = client.get_index_eod(sorted(contracts["reference_index_code"].astype(str).unique()), trade_date)
    rates = client.get_rates(trade_date)
    min_expiry = contracts["expiry_date"].min()
    max_expiry = contracts["expiry_date"].max()
    calendar = client.get_trading_calendar(min(pd.Timestamp(trade_date), pd.Timestamp(min_expiry)), max_expiry)
    return normalize_option_chain(contracts, eod, underlying, index, rates, trade_date, calendar)


def normalize_option_chain(
    contracts: pd.DataFrame,
    eod: pd.DataFrame,
    underlying: pd.DataFrame,
    index: pd.DataFrame,
    rates: pd.DataFrame,
    trade_date: str | pd.Timestamp,
    trading_calendar: Sequence[pd.Timestamp] | pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """Return one normalized contract-level chain with RMB-ready inputs."""

    trade_ts = pd.Timestamp(trade_date).normalize()
    required_contracts = {
        "option_code",
        "product_group",
        "venue",
        "underlying_code",
        "reference_index_code",
        "option_type",
        "strike",
        "expiry_date",
        "multiplier_or_contract_unit",
        "settlement_type",
    }
    _require_columns(contracts, required_contracts, "contracts")
    _require_columns(eod, {"option_code", "close", "volume", "open_interest"}, "option_eod")

    frame = contracts.copy()
    frame["trade_date"] = trade_ts
    frame["option_code"] = frame["option_code"].astype(str)
    frame["option_type"] = frame["option_type"].astype(str).str.lower()
    frame["expiry_date"] = pd.to_datetime(frame["expiry_date"]).dt.normalize()
    frame["strike"] = pd.to_numeric(frame["strike"], errors="coerce")
    frame["multiplier_or_contract_unit"] = pd.to_numeric(frame["multiplier_or_contract_unit"], errors="coerce")
    if "adjusted_contract_flag" not in frame.columns:
        frame["adjusted_contract_flag"] = False
    if "option_style" not in frame.columns:
        frame["option_style"] = "European"

    quotes = eod.copy()
    quotes["option_code"] = quotes["option_code"].astype(str)
    frame = frame.merge(quotes.drop(columns=["trade_date"], errors="ignore"), on="option_code", how="left", suffixes=("", "_quote"))

    under = _price_lookup(underlying, "underlying_price")
    ref_index = _price_lookup(index, "reference_index_level")
    frame = frame.merge(under, left_on="underlying_code", right_on="symbol", how="left").drop(columns=["symbol"], errors="ignore")
    frame = frame.merge(ref_index, left_on="reference_index_code", right_on="symbol", how="left").drop(columns=["symbol"], errors="ignore")

    rate_row = rates.iloc[0].to_dict() if not rates.empty else {}
    frame["risk_free_rate"] = float(rate_row.get("risk_free_rate", 0.02) or 0.02)
    frame["dividend_yield"] = float(rate_row.get("dividend_yield", 0.0) or 0.0)

    frame["dte_calendar"] = frame["expiry_date"].map(lambda expiry: calendar_days_to_expiry(trade_ts, expiry))
    frame["dte_trading"] = frame["expiry_date"].map(lambda expiry: trading_days_to_expiry(trade_ts, expiry, trading_calendar))
    frame["year_fraction"] = frame["dte_calendar"].map(year_fraction)

    for column in ["open", "high", "low", "close", "settle", "volume", "open_interest", "bid", "ask", "implied_vol"]:
        if column not in frame.columns:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    valid_bid_ask = (frame["bid"] > 0) & (frame["ask"] > frame["bid"])
    frame["mid"] = np.where(valid_bid_ask, (frame["bid"] + frame["ask"]) / 2.0, frame["close"].fillna(frame["settle"]))
    frame["mid"] = pd.to_numeric(frame["mid"], errors="coerce").fillna(frame["settle"]).fillna(frame["close"])

    frame["implied_vol_source"] = np.where(frame["implied_vol"].notna() & (frame["implied_vol"] > 0), "source", "internal")
    missing_iv = frame["implied_vol"].isna() | (frame["implied_vol"] <= 0)
    if missing_iv.any():
        frame.loc[missing_iv, "implied_vol"] = frame.loc[missing_iv].apply(_row_implied_vol, axis=1)

    frame["asof_time"] = frame.get("asof_time", "16:30:00")
    frame["source"] = frame.get("source", "normalized")
    clean = frame[NORMALIZED_OPTION_COLUMNS].copy()
    validate_normalized_chain(clean)
    return clean.sort_values(["product_group", "venue", "expiry_date", "strike", "option_type", "option_code"]).reset_index(drop=True)


def validate_normalized_chain(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, set(NORMALIZED_OPTION_COLUMNS), "normalized_chain")
    if frame.empty:
        raise ValueError("Normalized option chain is empty.")
    if not frame["option_type"].isin(["call", "put"]).all():
        raise ValueError("option_type must be call or put.")
    if frame["strike"].isna().any() or (frame["strike"] <= 0).any():
        raise ValueError("Normalized chain contains invalid strikes.")
    if frame["underlying_price"].isna().any() or (frame["underlying_price"] <= 0).any():
        raise ValueError("Normalized chain contains invalid underlying prices.")
    if frame["multiplier_or_contract_unit"].isna().any() or (frame["multiplier_or_contract_unit"] <= 0).any():
        raise ValueError("Normalized chain contains invalid multipliers.")
    return frame


def _price_lookup(frame: pd.DataFrame, output_column: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["symbol", output_column])
    symbol_column = "symbol" if "symbol" in frame.columns else "code"
    _require_columns(frame, {symbol_column, "close"}, "price frame")
    result = frame[[symbol_column, "close"]].copy()
    return result.rename(columns={symbol_column: "symbol", "close": output_column})


def _row_implied_vol(row: pd.Series) -> float:
    try:
        value = implied_volatility(
            price=float(row["mid"]),
            spot=float(row["underlying_price"]),
            strike=float(row["strike"]),
            year_fraction=float(row["year_fraction"]),
            rate=float(row["risk_free_rate"]),
            option_type=str(row["option_type"]),
            dividend_yield=float(row["dividend_yield"]),
        )
    except (ValueError, FloatingPointError, OverflowError):
        value = np.nan
    return float(value) if pd.notna(value) and value > 0 else np.nan


def _require_columns(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"{name} is missing columns: {sorted(missing)}")
