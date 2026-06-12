"""iFinD-backed data client for the main Daily Bias Engine snapshot."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Sequence

import pandas as pd

from daily_bias_engine.data.cache import RawDataCache
from daily_bias_engine.data.client import WindDataClient, WindDataError


SYMBOL_MAP = {
    "IF.CFE": "IF00.CFE",
    "HSI.HI": "HSI.HK",
}


@dataclass
class IFindDataClient(WindDataClient):
    """iFinD-backed implementation of the Wind-like market data interface."""

    cache: RawDataCache | None = None
    username: str | None = None
    password: str | None = None
    asof_time: str = "16:30:00"
    _logged_in: bool = False

    def get_daily_ohlcv(
        self,
        symbols: Sequence[str],
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
    ) -> pd.DataFrame:
        fields = ["open", "high", "low", "close", "volume", "amount"]
        frame = self._hq_frame(symbols, fields, start_date, end_date)
        self._cache("daily_ohlcv", symbols, start_date, end_date, frame)
        return frame

    def get_futures_open_interest(
        self,
        symbols: Sequence[str],
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
    ) -> pd.DataFrame:
        frame = self._hq_frame(symbols, ["openInterest", "volume"], start_date, end_date)
        if frame.empty:
            return pd.DataFrame(columns=["date", "symbol", "open_interest", "volume", "asof_time", "source"])
        output = frame.rename(columns={"openInterest": "open_interest"})
        columns = ["date", "symbol", "open_interest", "volume", "asof_time", "source"]
        return output[columns]

    def get_interest_rates(
        self,
        series: Sequence[str],
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
    ) -> pd.DataFrame:
        rows: list[pd.DataFrame] = []
        for name in series:
            try:
                frame = self._hq_frame([name], ["close"], start_date, end_date)
            except WindDataError:
                continue
            if frame.empty:
                continue
            rows.append(
                frame.rename(columns={"symbol": "series", "close": "rate"})[
                    ["date", "series", "rate", "asof_time", "source"]
                ]
            )
        output = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["date", "series", "rate", "asof_time", "source"])
        self._cache("interest_rates", series, start_date, end_date, output)
        return output

    def close(self) -> None:
        if not self._logged_in:
            return
        from iFinDPy import THS_iFinDLogout

        THS_iFinDLogout()
        self._logged_in = False

    def _hq_frame(
        self,
        symbols: Sequence[str],
        fields: Sequence[str],
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
    ) -> pd.DataFrame:
        self._login()
        from iFinDPy import THS_HQ

        rows: list[pd.DataFrame] = []
        for symbol in symbols:
            query_code = SYMBOL_MAP.get(str(symbol), str(symbol))
            result = THS_HQ(
                query_code,
                ";".join(fields),
                "",
                _date_part(start_date),
                _date_part(end_date),
            )
            _raise_ifind_error("THS_HQ", query_code, result)
            data = getattr(result, "data", None)
            if not isinstance(data, pd.DataFrame) or data.empty:
                continue
            frame = data.copy()
            frame["date"] = pd.to_datetime(frame["time"]).dt.normalize()
            frame["symbol"] = str(symbol)
            frame["asof_time"] = self.asof_time
            frame["source"] = "ifind"
            rows.append(frame)
        if not rows:
            return pd.DataFrame(columns=["date", "symbol", *fields, "asof_time", "source"])
        output = pd.concat(rows, ignore_index=True)
        output = output.rename(columns={"thscode": "ifind_code"})
        for column in fields:
            if column not in output.columns:
                output[column] = pd.NA
            output[column] = pd.to_numeric(output[column], errors="coerce")
        columns = ["date", "symbol", *fields, "asof_time", "source"]
        return output[columns].sort_values(["symbol", "date"]).reset_index(drop=True)

    def _login(self) -> None:
        if self._logged_in:
            return
        username = self.username or os.environ.get("IFIND_USERNAME")
        password = self.password or os.environ.get("IFIND_PASSWORD")
        if not username or not password:
            raise WindDataError("iFinD credentials are required. Set IFIND_USERNAME and IFIND_PASSWORD.")
        from iFinDPy import THS_GetErrorInfo, THS_iFinDLogin

        code = THS_iFinDLogin(username, password)
        if code != 0:
            raise WindDataError(f"iFinD login failed: {THS_GetErrorInfo(code)}")
        self._logged_in = True

    def _cache(
        self,
        dataset: str,
        names: Sequence[str],
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
        frame: pd.DataFrame,
    ) -> None:
        if self.cache is None:
            return
        request = {
            "dataset": dataset,
            "names": list(names),
            "start_date": _date_part(start_date),
            "end_date": _date_part(end_date),
            "source": "ifind",
        }
        self.cache.write_snapshot(dataset, request, frame)


def _date_part(value: str | pd.Timestamp) -> str:
    return str(pd.Timestamp(value).date())


def _raise_ifind_error(method: str, symbol: str, result: Any) -> None:
    errorcode = getattr(result, "errorcode", 0)
    if errorcode not in (0, None):
        errmsg = getattr(result, "errmsg", "")
        raise WindDataError(f"iFinD {method} failed for {symbol}: errorcode={errorcode}; errmsg={errmsg}")
