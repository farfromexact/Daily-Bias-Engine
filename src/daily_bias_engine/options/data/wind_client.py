"""Wind-like option data clients backed by WindPy."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

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
    """WindPy-backed option client.

    This class intentionally keeps credentials outside code. Wind terminal
    login/session state is expected to be managed by the local Wind install.
    """

    asof_time: str = "16:30:00"
    options: str = "PriceAdj=F"

    def get_option_contracts(self, product: str, trade_date: str | pd.Timestamp) -> pd.DataFrame:
        trade_ts = _normalize_date(trade_date)
        rows: list[dict[str, object]] = []
        wind = self._wind()
        metadata = get_product_metadata(product)
        for instrument in metadata.instruments:
            result = wind.wset(
                "optionchain",
                f"date={trade_ts.date()};us_code={instrument.underlying_code};option_var={instrument.option_product_code}",
            )
            if getattr(result, "ErrorCode", 0) != 0:
                if _is_wset_quota_error(result) and instrument.venue.upper() == "CFFEX":
                    rows.extend(self._generated_cffex_contracts(instrument, trade_ts))
                    continue
                if _is_wset_quota_error(result):
                    continue
                self._raise_for_error("wset optionchain", instrument.underlying_code, result)
            table = _wind_table(result)
            for _, item in table.iterrows():
                option_code = item.get("wind_code") or item.get("option_code") or item.get("sec_code")
                if pd.isna(option_code):
                    continue
                rows.append(
                    {
                        "trade_date": trade_ts,
                        "option_code": str(option_code),
                        "product_group": metadata.product_group,
                        "venue": instrument.venue,
                        "option_product_code": instrument.option_product_code,
                        "underlying_code": instrument.underlying_code,
                        "reference_index_code": instrument.reference_index_code,
                        "option_type": _normalize_option_type(item.get("call_or_put") or item.get("option_type")),
                        "strike": float(item.get("exercise_price") or item.get("strike")),
                        "expiry_date": pd.Timestamp(item.get("expire_date") or item.get("expiry_date")).normalize(),
                        "multiplier_or_contract_unit": float(
                            item.get("contract_unit") or item.get("multiplier") or instrument.default_multiplier
                        ),
                        "settlement_type": instrument.settlement_type,
                        "option_style": instrument.option_style,
                        "adjusted_contract_flag": bool(item.get("is_adjusted", False)),
                        "underlying_type": instrument.underlying_type,
                        "source": "wind",
                    }
                )
        if not rows:
            raise OptionDataError(f"Wind returned no option contracts for {product} on {trade_ts.date()}.")
        return pd.DataFrame(rows)

    def get_option_eod(self, codes: Sequence[str], trade_date: str | pd.Timestamp) -> pd.DataFrame:
        fields = ["open", "high", "low", "close", "settle", "volume", "oi", "us_impliedvol"]
        frame = self._wsd_frame(codes, fields, trade_date)
        return frame.rename(columns={"oi": "open_interest", "us_impliedvol": "implied_vol"})

    def get_underlying_eod(self, codes: Sequence[str], trade_date: str | pd.Timestamp) -> pd.DataFrame:
        return self._wsd_frame(codes, ["open", "high", "low", "close", "volume", "amt"], trade_date).rename(columns={"amt": "amount"})

    def get_index_eod(self, codes: Sequence[str], trade_date: str | pd.Timestamp) -> pd.DataFrame:
        return self.get_underlying_eod(codes, trade_date)

    def get_futures_eod(self, prefix: str, trade_date: str | pd.Timestamp) -> pd.DataFrame:
        return self._wsd_frame([f"{prefix.upper()}.CFE"], ["open", "high", "low", "close", "volume", "oi"], trade_date).rename(
            columns={"oi": "open_interest"}
        )

    def get_rates(self, trade_date: str | pd.Timestamp) -> pd.DataFrame:
        frame = self._wsd_frame(["SHIBOR1W.IR"], ["close"], trade_date)
        rate = float(frame["close"].iloc[0]) / 100.0 if not frame.empty else 0.02
        return pd.DataFrame(
            [
                {
                    "trade_date": _normalize_date(trade_date),
                    "risk_free_rate": rate,
                    "dividend_yield": 0.0,
                    "source": "wind",
                    "asof_time": self.asof_time,
                }
            ]
        )

    def get_trading_calendar(self, start: str | pd.Timestamp, end: str | pd.Timestamp) -> pd.DatetimeIndex:
        wind = self._wind()
        result = wind.tdays(str(_normalize_date(start).date()), str(_normalize_date(end).date()), "")
        self._raise_for_error("tdays", "calendar", result)
        return pd.DatetimeIndex(pd.to_datetime(result.Times)).normalize()

    def _wsd_frame(self, codes: Sequence[str], fields: Sequence[str], trade_date: str | pd.Timestamp) -> pd.DataFrame:
        wind = self._wind()
        date = str(_normalize_date(trade_date).date())
        rows = []
        for chunk in _chunks([str(code) for code in codes], 100):
            result = wind.wsd(",".join(chunk), ",".join(fields), date, date, self.options)
            if getattr(result, "ErrorCode", 0) != 0:
                rows.extend(self._wsd_frame_one_by_one(wind, chunk, fields, date, trade_date))
                continue
            rows.extend(_rows_from_wsd_result(result, chunk, fields, trade_date, self.asof_time))
        return pd.DataFrame(rows)

    def _wsd_frame_one_by_one(
        self,
        wind: Any,
        codes: Sequence[str],
        fields: Sequence[str],
        date: str,
        trade_date: str | pd.Timestamp,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for code in codes:
            result = wind.wsd(str(code), ",".join(fields), date, date, self.options)
            if getattr(result, "ErrorCode", 0) != 0:
                continue
            rows.extend(_rows_from_wsd_result(result, [str(code)], fields, trade_date, self.asof_time))
        return rows

    def _generated_cffex_contracts(self, instrument: Any, trade_date: pd.Timestamp) -> list[dict[str, object]]:
        spot = self._reference_close(instrument.reference_index_code, trade_date)
        candidate_codes = _generate_cffex_option_codes(
            prefix=instrument.option_product_code,
            spot=spot,
            trade_date=trade_date,
        )
        rows: list[dict[str, object]] = []
        wind = self._wind()
        fields = ["windcode", "sec_name", "exe_price", "exe_enddate", "contractmultiplier", "underlyingwindcode"]
        for chunk in _chunks(candidate_codes, 300):
            result = wind.wss(",".join(chunk), ",".join(fields))
            self._raise_for_error("wss generated CFFEX contracts", instrument.option_product_code, result)
            table = _wind_table(result)
            for _, item in table.iterrows():
                option_code = item.get("windcode")
                sec_name = item.get("sec_name")
                expiry = item.get("exe_enddate")
                strike = item.get("exe_price")
                if pd.isna(option_code) or pd.isna(sec_name) or pd.isna(strike) or _is_null_wind_date(expiry):
                    continue
                option_code_text = str(option_code)
                rows.append(
                    {
                        "trade_date": trade_date,
                        "option_code": option_code_text,
                        "product_group": instrument.product_group,
                        "venue": instrument.venue,
                        "option_product_code": instrument.option_product_code,
                        "underlying_code": instrument.underlying_code,
                        "reference_index_code": instrument.reference_index_code,
                        "option_type": "call" if "-C-" in option_code_text else "put",
                        "strike": float(strike),
                        "expiry_date": pd.Timestamp(expiry).normalize(),
                        "multiplier_or_contract_unit": float(item.get("contractmultiplier") or instrument.default_multiplier),
                        "settlement_type": instrument.settlement_type,
                        "option_style": instrument.option_style,
                        "adjusted_contract_flag": False,
                        "underlying_type": instrument.underlying_type,
                        "source": "wind_generated_cffex",
                    }
                )
        return rows

    def _reference_close(self, code: str, trade_date: pd.Timestamp) -> float:
        frame = self._wsd_frame([code], ["close"], trade_date)
        close = pd.to_numeric(frame["close"], errors="coerce").dropna()
        if close.empty or float(close.iloc[0]) <= 0:
            raise OptionDataError(f"Cannot get reference close for {code} on {trade_date.date()}.")
        return float(close.iloc[0])

    def _wind(self) -> Any:
        try:
            from WindPy import w
        except ImportError as exc:
            raise OptionDataError("WindPy is not installed or not importable.") from exc
        result = w.start()
        if getattr(result, "ErrorCode", 0) != 0:
            raise OptionDataError(f"WindPy start/login failed: ErrorCode={result.ErrorCode}; Data={result.Data}")
        return w

    @staticmethod
    def _raise_for_error(method: str, symbol: str, result: Any) -> None:
        if getattr(result, "ErrorCode", 0) != 0:
            raise OptionDataError(f"Wind {method} failed for {symbol}: ErrorCode={result.ErrorCode}")


def _normalize_date(value: str | pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _is_wset_quota_error(result: Any) -> bool:
    if getattr(result, "ErrorCode", 0) != -40522017:
        return False
    data = getattr(result, "Data", []) or []
    text = " ".join(str(item) for column in data for item in column)
    return "quota exceeded" in text.lower()


def _generate_cffex_option_codes(prefix: str, spot: float, trade_date: pd.Timestamp) -> list[str]:
    code_prefix = prefix.upper()
    step = 100.0 if code_prefix == "MO" else 50.0
    lower = np.floor((spot * 0.70) / step) * step
    upper = np.ceil((spot * 1.30) / step) * step
    strikes = [int(value) for value in np.arange(lower, upper + step, step)]
    months = []
    current = trade_date.replace(day=1)
    for offset in range(12):
        month = current + pd.DateOffset(months=offset)
        months.append(month.strftime("%y%m"))
    return [f"{code_prefix}{month}-{cp}-{strike}.CFE" for month in months for cp in ("C", "P") for strike in strikes]


def _is_null_wind_date(value: object) -> bool:
    if pd.isna(value):
        return True
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return True
    return timestamp.year <= 1900


def _chunks(values: Sequence[str], size: int) -> list[list[str]]:
    return [list(values[index : index + size]) for index in range(0, len(values), size)]


def _normalize_option_type(value: object) -> str:
    text = str(value).lower()
    if text in {"认购", "call", "c", "1"}:
        return "call"
    if text in {"认沽", "put", "p", "2"}:
        return "put"
    raise OptionDataError(f"Cannot normalize option type: {value!r}")


def _wind_table(result: Any) -> pd.DataFrame:
    fields = [str(field).lower() for field in getattr(result, "Fields", [])]
    if not fields:
        raise OptionDataError("Wind result did not include field names.")
    data = getattr(result, "Data", [])
    return pd.DataFrame({field: values for field, values in zip(fields, data)})


def _rows_from_wsd_result(
    result: Any,
    codes: Sequence[str],
    fields: Sequence[str],
    trade_date: str | pd.Timestamp,
    asof_time: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row_index, code in enumerate(codes):
        row = {
            "trade_date": _normalize_date(trade_date),
            "symbol": str(code),
            "option_code": str(code),
            "asof_time": asof_time,
            "source": "wind",
        }
        for field_index, field_name in enumerate(fields):
            row[field_name] = _value_at(result.Data, field_index, row_index)
        rows.append(row)
    return rows


def _value_at(data: Sequence[Sequence[Any]], field_index: int, row_index: int) -> Any:
    value = data[field_index][row_index]
    if value is None:
        return pd.NA
    return value
