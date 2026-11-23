"""Wind-like option data clients backed by WindPy."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Sequence

import pandas as pd

from daily_bias_engine.data.client import MarketDataError, check_wind_result, get_wind_session
from daily_bias_engine.options.data.contract_master import get_product_metadata


class OptionDataError(RuntimeError):
    """Raised when option market data cannot be fetched or normalized."""


class OptionWindClient(ABC):
    """Interface for Wind-compatible option data providers."""

    @abstractmethod
    def get_option_contracts(self, product: str, trade_date: str | pd.Timestamp) -> pd.DataFrame:
        """Return listed option contracts for a product group on a trade date."""

    @abstractmethod
    def get_option_eod(self, codes: Sequence[str], trade_date: str | pd.Timestamp) -> pd.DataFrame:
        """Return option end-of-day quote, volume, OI, and IV data."""

    @abstractmethod
    def get_underlying_eod(self, codes: Sequence[str], trade_date: str | pd.Timestamp) -> pd.DataFrame:
        """Return ETF or index underlying end-of-day data."""

    @abstractmethod
    def get_index_eod(self, codes: Sequence[str], trade_date: str | pd.Timestamp) -> pd.DataFrame:
        """Return reference index end-of-day data."""

    @abstractmethod
    def get_futures_eod(self, prefix: str, trade_date: str | pd.Timestamp) -> pd.DataFrame:
        """Return a hedge future proxy for the product group."""

    @abstractmethod
    def get_rates(self, trade_date: str | pd.Timestamp) -> pd.DataFrame:
        """Return risk-free and dividend/forward adjustment inputs."""

    @abstractmethod
    def get_trading_calendar(self, start: str | pd.Timestamp, end: str | pd.Timestamp) -> pd.DatetimeIndex:
        """Return exchange trading dates."""


@dataclass
class WindPyOptionClient(OptionWindClient):
    """Fetch historical contract membership and end-of-day quotes from Wind."""

    asof_time: str = "16:30:00"
    # Strike and multiplier refer to the unadjusted spot price on the trade date.
    options: str = "priceAdj=U;cycle=D"

    def get_option_contracts(self, product: str, trade_date: str | pd.Timestamp) -> pd.DataFrame:
        day = pd.Timestamp(trade_date).normalize()
        rows = []
        for instrument in get_product_metadata(product).instruments:
            code = instrument.underlying_code
            result = get_wind_session().wset(
                "optionchain", f"date={day.date()};us_code={code};option_var=all;call_put=all"
            )
            table = _wind_table(result, f"WSET optionchain {code} {day.date()}")
            if table.empty:
                raise OptionDataError(f"Wind returned an empty option chain for {code} on {day.date()}")
            for item in table.itertuples(index=False):
                if item.us_code.upper() != code:
                    raise OptionDataError(f"Wind returned underlying {item.us_code} for {code}")
                side = {"认购": "call", "认沽": "put", "call": "call", "put": "put"}.get(str(item.call_put).lower())
                expiry = pd.Timestamp(item.last_tradedate).normalize()
                if side is None or pd.isna(expiry) or expiry < day or pd.Timestamp(item.first_tradedate) > day:
                    raise OptionDataError(f"Invalid Wind contract metadata for {item.option_code} on {day.date()}")
                rows.append({
                    "trade_date": day,
                    "option_code": item.option_code,
                    "product_group": instrument.product_group,
                    "venue": instrument.venue,
                    "option_product_code": instrument.option_product_code,
                    "underlying_code": code,
                    "reference_index_code": instrument.reference_index_code,
                    "option_type": side,
                    "strike": float(item.strike_price),
                    "expiry_date": expiry,
                    "multiplier_or_contract_unit": float(item.multiplier),
                    "settlement_type": instrument.settlement_type,
                    "option_style": instrument.option_style,
                    "adjusted_contract_flag": float(item.multiplier) != instrument.default_multiplier,
                    "underlying_type": instrument.underlying_type,
                    "source": "wind",
                })
        contracts = pd.DataFrame(rows)
        if contracts["option_code"].duplicated().any():
            raise OptionDataError(f"Wind returned duplicate option codes for {product} on {day.date()}")
        return contracts

    def get_option_eod(self, codes: Sequence[str], trade_date) -> pd.DataFrame:
        fields = ["open", "high", "low", "close", "settle", "volume", "oi", "us_impliedvol"]
        quotes = self._eod(codes, fields, trade_date)
        if quotes[["close", "settle"]].isna().all(axis=1).any() or quotes["oi"].isna().any():
            raise OptionDataError(f"Incomplete Wind option EOD prices or open interest for {trade_date}")
        return quotes.rename(columns={"symbol": "option_code", "oi": "open_interest", "us_impliedvol": "implied_vol"})

    def get_underlying_eod(self, codes: Sequence[str], trade_date) -> pd.DataFrame:
        prices = self._eod(codes, ["open", "high", "low", "close", "volume", "amt"], trade_date)
        if not prices["close"].gt(0).fillna(False).all():
            raise OptionDataError(f"Missing Wind underlying or index close on {trade_date}: {codes}")
        return prices.rename(columns={"amt": "amount"})

    def get_index_eod(self, codes: Sequence[str], trade_date) -> pd.DataFrame:
        return self.get_underlying_eod(codes, trade_date)

    def get_futures_eod(self, prefix: str, trade_date) -> pd.DataFrame:
        fields = ["open", "high", "low", "close", "volume", "oi"]
        return self._eod([f"{prefix.upper()}.CFE"], fields, trade_date).rename(columns={"oi": "open_interest"})

    def get_rates(self, trade_date) -> pd.DataFrame:
        frame = self._eod(["SHIBOR1W.IR"], ["close"], trade_date)
        rate = frame.at[0, "close"]
        if pd.isna(rate):
            raise OptionDataError(f"Wind returned no SHIBOR1W.IR close for {trade_date}")
        return frame.assign(risk_free_rate=float(rate) / 100.0, dividend_yield=0.0).drop(columns=["symbol", "close"])

    def get_trading_calendar(self, start, end) -> pd.DatetimeIndex:
        first, last = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
        result = get_wind_session().tdays(str(first.date()), str(last.date()), "")
        _check(result, "tdays")
        dates = pd.DatetimeIndex(pd.to_datetime(result.Data[0] if result.Data else [])).normalize()
        return dates[(dates >= first) & (dates <= last)]

    def _eod(self, codes: Sequence[str], fields: Sequence[str], trade_date) -> pd.DataFrame:
        day = pd.Timestamp(trade_date).normalize()
        options = f"tradeDate={day:%Y%m%d};{self.options}"
        frames = []
        for start in range(0, len(codes), 100):
            chunk = codes[start:start + 100]
            result = get_wind_session().wss(",".join(chunk), ",".join(fields), options)
            table = _wind_table(result, f"WSS {chunk[0]}..{chunk[-1]} {day.date()}")
            if (set(table.columns) != set(fields) or len(table) != len(chunk)
                    or set(result.Codes) != set(chunk) or len(result.Codes) != len(table)):
                raise OptionDataError(f"Incomplete Wind WSS response for {day.date()} ({chunk[0]}..{chunk[-1]})")
            table["symbol"] = result.Codes
            frames.append(table)
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=[*fields, "symbol"])
        return frame.assign(trade_date=day, source="wind", asof_time=self.asof_time)


def _check(result: Any, request: str) -> None:
    try:
        check_wind_result(result, request)
    except MarketDataError as exc:
        raise OptionDataError(str(exc)) from exc


def _wind_table(result: Any, request: str) -> pd.DataFrame:
    _check(result, request)
    fields = [str(field).lower() for field in result.Fields]
    if len(fields) != len(result.Data):
        raise OptionDataError(f"Wind {request} returned inconsistent field dimensions")
    return pd.DataFrame(dict(zip(fields, result.Data)))
