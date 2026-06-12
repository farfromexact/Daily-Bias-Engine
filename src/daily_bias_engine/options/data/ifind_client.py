"""iFinD-backed option data client."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from typing import Any, Sequence

import numpy as np
import pandas as pd

from daily_bias_engine.options.data.contract_master import get_product_metadata
from daily_bias_engine.options.data.wind_client import OptionDataError, OptionWindClient

IFIND_HQ_CHUNK_SIZE = 800


@dataclass
class IFindOptionClient(OptionWindClient):
    """iFinD-backed option client.

    Credentials are read from environment variables by default and are never
    persisted by this class. Set IFIND_USERNAME and IFIND_PASSWORD before use.
    """

    username: str | None = None
    password: str | None = None
    asof_time: str = "16:30:00"
    _logged_in: bool = field(default=False, init=False, repr=False)
    _quote_cache: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict, init=False, repr=False)
    _calendar_cache: dict[tuple[str, str], pd.DatetimeIndex] = field(default_factory=dict, init=False, repr=False)

    def get_option_contracts(self, product: str, trade_date: str | pd.Timestamp) -> pd.DataFrame:
        trade_ts = _normalize_date(trade_date)
        metadata = get_product_metadata(product)
        rows: list[dict[str, object]] = []
        for instrument in metadata.instruments:
            if instrument.venue.upper() != "CFFEX":
                continue
            spot = self._reference_close(instrument.reference_index_code, trade_ts)
            candidate_codes = _generate_cffex_option_codes(instrument.option_product_code, spot, trade_ts)
            quotes = self._ifind_hq_frame(
                candidate_codes,
                ["open", "high", "low", "close", "settlement", "volume", "amount", "openInterest"],
                trade_ts,
                ignore_invalid_errors=True,
            )
            for _, item in quotes.iterrows():
                option_code = str(item.get("thscode") or item.get("symbol") or "")
                if not option_code or not _has_positive_market_value(item):
                    continue
                strike = _strike_from_cffex_code(option_code)
                expiry = self._expiry_from_cffex_code(option_code)
                if strike is None or expiry is None:
                    continue
                rows.append(
                    {
                        "trade_date": trade_ts,
                        "option_code": option_code,
                        "product_group": instrument.product_group,
                        "venue": instrument.venue,
                        "option_product_code": instrument.option_product_code,
                        "underlying_code": instrument.underlying_code,
                        "reference_index_code": instrument.reference_index_code,
                        "option_type": "call" if "-C-" in option_code else "put",
                        "strike": float(strike),
                        "expiry_date": expiry,
                        "multiplier_or_contract_unit": instrument.default_multiplier,
                        "settlement_type": instrument.settlement_type,
                        "option_style": instrument.option_style,
                        "adjusted_contract_flag": False,
                        "underlying_type": instrument.underlying_type,
                        "source": "ifind_generated_cffex",
                    }
                )
        if not rows:
            raise OptionDataError(f"iFinD returned no option contracts for {product} on {trade_ts.date()}.")
        return pd.DataFrame(rows)

    def get_option_eod(self, codes: Sequence[str], trade_date: str | pd.Timestamp) -> pd.DataFrame:
        frame = self._ifind_hq_frame(
            codes,
            ["open", "high", "low", "close", "settlement", "volume", "amount", "openInterest"],
            trade_date,
            ignore_invalid_errors=True,
        )
        if frame.empty:
            return pd.DataFrame()
        return frame.rename(columns={"thscode": "option_code", "settlement": "settle", "openInterest": "open_interest"})

    def get_underlying_eod(self, codes: Sequence[str], trade_date: str | pd.Timestamp) -> pd.DataFrame:
        frame = self._ifind_hq_frame(codes, ["open", "high", "low", "close", "volume", "amount"], trade_date)
        if frame.empty:
            return pd.DataFrame()
        return frame.rename(columns={"thscode": "symbol"})

    def get_index_eod(self, codes: Sequence[str], trade_date: str | pd.Timestamp) -> pd.DataFrame:
        return self.get_underlying_eod(codes, trade_date)

    def get_futures_eod(self, prefix: str, trade_date: str | pd.Timestamp) -> pd.DataFrame:
        frame = self._ifind_hq_frame([f"{prefix.upper()}.CFE"], ["open", "high", "low", "close", "volume", "openInterest"], trade_date)
        if frame.empty:
            return pd.DataFrame()
        return frame.rename(columns={"thscode": "symbol", "openInterest": "open_interest"})

    def get_rates(self, trade_date: str | pd.Timestamp) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "trade_date": _normalize_date(trade_date),
                    "risk_free_rate": 0.02,
                    "dividend_yield": 0.0,
                    "source": "ifind_default",
                    "asof_time": self.asof_time,
                }
            ]
        )

    def get_trading_calendar(self, start: str | pd.Timestamp, end: str | pd.Timestamp) -> pd.DatetimeIndex:
        start_part = _normalize_date(start).strftime("%Y-%m-%d")
        end_part = _normalize_date(end).strftime("%Y-%m-%d")
        key = (start_part, end_part)
        if key in self._calendar_cache:
            return self._calendar_cache[key]
        self._login()
        from iFinDPy import THS_DateQuery

        result = THS_DateQuery("SSE", "dateType:0", start_part, end_part)
        _raise_ifind_error("THS_DateQuery", result)
        times = (result.get("tables") or {}).get("time") or []
        calendar = pd.DatetimeIndex(pd.to_datetime(times)).normalize()
        self._calendar_cache[key] = calendar
        return calendar

    def close(self) -> None:
        if not self._logged_in:
            return
        from iFinDPy import THS_iFinDLogout

        THS_iFinDLogout()
        self._logged_in = False

    def _ifind_hq_frame(
        self,
        codes: Sequence[str],
        fields: Sequence[str],
        trade_date: str | pd.Timestamp,
        *,
        ignore_invalid_errors: bool = False,
    ) -> pd.DataFrame:
        trade_ts = _normalize_date(trade_date)
        date_part = trade_ts.strftime("%Y-%m-%d")
        missing = [str(code) for code in codes if (date_part, str(code)) not in self._quote_cache]
        if missing:
            self._login()
            from iFinDPy import THS_HQ

            for chunk in _chunks(missing, IFIND_HQ_CHUNK_SIZE):
                result = THS_HQ(chunk, ";".join(fields), "", date_part, date_part)
                if _is_ifind_invalid_parameter(result) and ignore_invalid_errors:
                    for code in chunk:
                        self._quote_cache.setdefault((date_part, str(code)), {"time": date_part, "thscode": str(code)})
                    continue
                _raise_ifind_error("THS_HQ", result)
                data = getattr(result, "data", None)
                if isinstance(data, pd.DataFrame) and not data.empty:
                    for _, row in data.iterrows():
                        code = str(row.get("thscode") or "")
                        if code:
                            self._quote_cache[(date_part, code)] = row.to_dict()
                for code in chunk:
                    self._quote_cache.setdefault((date_part, str(code)), {"time": date_part, "thscode": str(code)})
        rows = [self._quote_cache[(date_part, str(code))] for code in codes if (date_part, str(code)) in self._quote_cache]
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        frame["trade_date"] = trade_ts
        frame["asof_time"] = self.asof_time
        frame["source"] = "ifind"
        return frame

    def _reference_close(self, code: str, trade_date: pd.Timestamp) -> float:
        frame = self.get_index_eod([code], trade_date)
        close = pd.to_numeric(frame.get("close", pd.Series(dtype=float)), errors="coerce").dropna()
        if close.empty or float(close.iloc[0]) <= 0:
            raise OptionDataError(f"Cannot get iFinD reference close for {code} on {trade_date.date()}.")
        return float(close.iloc[0])

    def _expiry_from_cffex_code(self, code: str) -> pd.Timestamp | None:
        match = re.match(r"^[A-Z]+(?P<yymm>\d{4})-[CP]-\d+\.CFE$", code.upper())
        if not match:
            return None
        year = 2000 + int(match.group("yymm")[:2])
        month = int(match.group("yymm")[2:])
        month_start = pd.Timestamp(year=year, month=month, day=1)
        month_end = month_start + pd.offsets.MonthEnd(0)
        third_friday = month_start + pd.offsets.WeekOfMonth(week=2, weekday=4)
        calendar = self.get_trading_calendar(month_start, month_end)
        valid = calendar[calendar >= third_friday.normalize()]
        if valid.empty:
            return None
        return pd.Timestamp(valid[0]).normalize()

    def _login(self) -> None:
        if self._logged_in:
            return
        username = self.username or os.environ.get("IFIND_USERNAME")
        password = self.password or os.environ.get("IFIND_PASSWORD")
        if not username or not password:
            raise OptionDataError("iFinD credentials are required. Set IFIND_USERNAME and IFIND_PASSWORD.")
        from iFinDPy import THS_GetErrorInfo, THS_iFinDLogin

        code = THS_iFinDLogin(username, password)
        if code != 0:
            raise OptionDataError(f"iFinD login failed: {THS_GetErrorInfo(code)}")
        self._logged_in = True


def _normalize_date(value: str | pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _generate_cffex_option_codes(prefix: str, spot: float, trade_date: pd.Timestamp) -> list[str]:
    code_prefix = prefix.upper()
    step = 100.0 if code_prefix == "MO" else 50.0
    lower = np.floor((spot * 0.70) / step) * step
    upper = np.ceil((spot * 1.30) / step) * step
    strikes = [int(value) for value in np.arange(lower, upper + step, step)]
    months = _cffex_active_contract_months(trade_date)
    return [f"{code_prefix}{month}-{cp}-{strike}.CFE" for month in months for cp in ("C", "P") for strike in strikes]


def _cffex_active_contract_months(trade_date: pd.Timestamp) -> list[str]:
    current = trade_date.replace(day=1)
    months = [current + pd.DateOffset(months=offset) for offset in range(3)]
    cursor = months[-1] + pd.DateOffset(months=1)
    while len(months) < 6:
        if cursor.month in {3, 6, 9, 12}:
            months.append(cursor)
        cursor += pd.DateOffset(months=1)
    return [month.strftime("%y%m") for month in months]


def _strike_from_cffex_code(code: str) -> float | None:
    match = re.match(r"^[A-Z]+\d{4}-[CP]-(?P<strike>\d+)\.CFE$", code.upper())
    if not match:
        return None
    return float(match.group("strike"))


def _has_positive_market_value(row: pd.Series) -> bool:
    for column in ("close", "settlement", "openInterest", "volume"):
        value = pd.to_numeric(pd.Series([row.get(column)]), errors="coerce").iloc[0]
        if pd.notna(value) and float(value) > 0:
            return True
    return False


def _raise_ifind_error(method: str, result: Any) -> None:
    errorcode = result.get("errorcode") if isinstance(result, dict) else getattr(result, "errorcode", 0)
    if errorcode not in (0, None):
        errmsg = result.get("errmsg") if isinstance(result, dict) else getattr(result, "errmsg", "")
        raise OptionDataError(f"iFinD {method} failed: errorcode={errorcode}; errmsg={errmsg}")


def _is_ifind_invalid_parameter(result: Any) -> bool:
    errorcode = result.get("errorcode") if isinstance(result, dict) else getattr(result, "errorcode", 0)
    return int(errorcode or 0) == -4210


def _chunks(values: Sequence[str], size: int) -> list[list[str]]:
    return [list(values[index : index + size]) for index in range(0, len(values), size)]
