"""Wind data interfaces and deterministic mock implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from daily_bias_engine.data.cache import RawDataCache


def _date_range(start_date: str | pd.Timestamp, end_date: str | pd.Timestamp) -> pd.DatetimeIndex:
    dates = pd.bdate_range(pd.Timestamp(start_date), pd.Timestamp(end_date))
    if dates.empty:
        raise ValueError("Date range produced no business days.")
    return dates


def _symbol_seed(symbol: str) -> int:
    return sum((index + 1) * ord(char) for index, char in enumerate(symbol))


class WindDataClient(ABC):
    """Interface for Wind-like market data clients.

    Real Wind API bindings are intentionally not implemented in v1.
    """

    @abstractmethod
    def get_daily_ohlcv(
        self,
        symbols: Sequence[str],
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
    ) -> pd.DataFrame:
        """Return daily OHLCV bars."""

    @abstractmethod
    def get_futures_open_interest(
        self,
        symbols: Sequence[str],
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
    ) -> pd.DataFrame:
        """Return daily futures open interest."""

    @abstractmethod
    def get_interest_rates(
        self,
        series: Sequence[str],
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
    ) -> pd.DataFrame:
        """Return daily interest-rate series."""


class WindDataError(RuntimeError):
    """Raised when WindPy is unavailable, disconnected, or returns an error."""


@dataclass
class MockWindDataClient(WindDataClient):
    """Deterministic mock client for unit tests and demos."""

    cache: RawDataCache | None = None
    asof_time: str = "16:30:00"

    def get_daily_ohlcv(
        self,
        symbols: Sequence[str],
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
    ) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        dates = _date_range(start_date, end_date)
        for symbol in symbols:
            seed = _symbol_seed(symbol)
            base = 80.0 + seed % 60
            drift = ((seed % 9) - 4) * 0.015
            phase = (seed % 11) / 5.0
            for index, date in enumerate(dates):
                wave = np.sin(index / 4.0 + phase) * 1.5
                close = base + index * drift + wave
                open_price = close * (1.0 - 0.002 + ((seed + index) % 5) * 0.001)
                high = max(open_price, close) * (1.004 + ((seed + index) % 3) * 0.001)
                low = min(open_price, close) * (0.996 - ((seed + index) % 2) * 0.001)
                volume = 1_000_000 + (seed % 1000) * 100 + index * 2_500
                rows.append(
                    {
                        "date": date.normalize(),
                        "symbol": symbol,
                        "open": round(open_price, 4),
                        "high": round(high, 4),
                        "low": round(low, 4),
                        "close": round(close, 4),
                        "volume": int(volume),
                        "amount": round(close * volume, 2),
                        "asof_time": self.asof_time,
                        "source": "mock",
                    }
                )
        frame = pd.DataFrame(rows)
        self._cache("daily_ohlcv", symbols, start_date, end_date, frame)
        return frame

    def get_futures_open_interest(
        self,
        symbols: Sequence[str],
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
    ) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        dates = _date_range(start_date, end_date)
        for symbol in symbols:
            seed = _symbol_seed(symbol)
            base = 120_000 + seed % 20_000
            for index, date in enumerate(dates):
                open_interest = base + index * (80 + seed % 30) + np.cos(index / 5.0) * 500
                rows.append(
                    {
                        "date": date.normalize(),
                        "symbol": symbol,
                        "open_interest": int(round(open_interest)),
                        "volume": int(40_000 + seed % 5_000 + index * 120),
                        "asof_time": self.asof_time,
                        "source": "mock",
                    }
                )
        frame = pd.DataFrame(rows)
        self._cache("futures_open_interest", symbols, start_date, end_date, frame)
        return frame

    def get_interest_rates(
        self,
        series: Sequence[str],
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
    ) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        dates = _date_range(start_date, end_date)
        for name in series:
            seed = _symbol_seed(name)
            base = 1.8 + (seed % 120) / 100.0
            drift = ((seed % 7) - 3) * 0.001
            for index, date in enumerate(dates):
                rate = base + drift * index + np.sin(index / 6.0 + seed % 3) * 0.03
                rows.append(
                    {
                        "date": date.normalize(),
                        "series": name,
                        "rate": round(rate, 4),
                        "asof_time": self.asof_time,
                        "source": "mock",
                    }
                )
        frame = pd.DataFrame(rows)
        self._cache("interest_rates", series, start_date, end_date, frame)
        return frame

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
            "start_date": str(pd.Timestamp(start_date).date()),
            "end_date": str(pd.Timestamp(end_date).date()),
        }
        self.cache.write_snapshot(dataset, request, frame)


@dataclass
class WindPyDataClient(WindDataClient):
    """WindPy-backed data client.

    The Wind terminal must be installed, running, and logged in before calls can
    succeed. This class keeps the same public interface as ``MockWindDataClient``.
    """

    cache: RawDataCache | None = None
    asof_time: str = "16:30:00"
    options: str = "PriceAdj=F"

    def get_daily_ohlcv(
        self,
        symbols: Sequence[str],
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
    ) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for symbol in symbols:
            result = self._wsd(symbol, ["open", "high", "low", "close", "volume", "amt"], start_date, end_date)
            for index, date in enumerate(result.Times):
                rows.append(
                    {
                        "date": pd.Timestamp(date).normalize(),
                        "symbol": symbol,
                        "open": _value_at(result.Data, 0, index),
                        "high": _value_at(result.Data, 1, index),
                        "low": _value_at(result.Data, 2, index),
                        "close": _value_at(result.Data, 3, index),
                        "volume": _value_at(result.Data, 4, index),
                        "amount": _value_at(result.Data, 5, index),
                        "asof_time": self.asof_time,
                        "source": "wind",
                    }
                )
        frame = pd.DataFrame(rows)
        self._cache("daily_ohlcv", symbols, start_date, end_date, frame)
        return frame

    def get_futures_open_interest(
        self,
        symbols: Sequence[str],
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
    ) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for symbol in symbols:
            result = self._wsd(symbol, ["oi", "volume"], start_date, end_date)
            for index, date in enumerate(result.Times):
                rows.append(
                    {
                        "date": pd.Timestamp(date).normalize(),
                        "symbol": symbol,
                        "open_interest": _value_at(result.Data, 0, index),
                        "volume": _value_at(result.Data, 1, index),
                        "asof_time": self.asof_time,
                        "source": "wind",
                    }
                )
        frame = pd.DataFrame(rows)
        self._cache("futures_open_interest", symbols, start_date, end_date, frame)
        return frame

    def get_interest_rates(
        self,
        series: Sequence[str],
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
    ) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for name in series:
            result = self._rate_series(name, start_date, end_date)
            for index, date in enumerate(result.Times):
                rows.append(
                    {
                        "date": pd.Timestamp(date).normalize(),
                        "series": name,
                        "rate": _value_at(result.Data, 0, index),
                        "asof_time": self.asof_time,
                        "source": "wind",
                    }
                )
        frame = pd.DataFrame(rows)
        self._cache("interest_rates", series, start_date, end_date, frame)
        return frame

    def _wsd(
        self,
        symbol: str,
        fields: Sequence[str],
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
        options: str | None = None,
    ) -> Any:
        wind = self._wind()
        result = wind.wsd(
            symbol,
            ",".join(fields),
            str(pd.Timestamp(start_date).date()),
            str(pd.Timestamp(end_date).date()),
            options if options is not None else self.options,
        )
        self._raise_for_error("wsd", symbol, result)
        return result

    def _rate_series(
        self,
        name: str,
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
    ) -> Any:
        try:
            return self._wsd(name, ["close"], start_date, end_date, options="")
        except WindDataError as wsd_error:
            wind = self._wind()
            result = wind.edb(
                name,
                str(pd.Timestamp(start_date).date()),
                str(pd.Timestamp(end_date).date()),
                "",
            )
            if getattr(result, "ErrorCode", 0) != 0:
                raise WindDataError(
                    f"Wind rate request failed for {name}: wsd={wsd_error}; edb ErrorCode={result.ErrorCode}"
                ) from wsd_error
            return result

    def _wind(self) -> Any:
        try:
            from WindPy import w
        except ImportError as exc:
            raise WindDataError("WindPy is not installed or not importable.") from exc

        start_result = w.start()
        if getattr(start_result, "ErrorCode", 0) != 0:
            raise WindDataError(f"WindPy login/start failed: ErrorCode={start_result.ErrorCode}; Data={start_result.Data}")
        return w

    @staticmethod
    def _raise_for_error(method: str, symbol: str, result: Any) -> None:
        if getattr(result, "ErrorCode", 0) != 0:
            raise WindDataError(f"Wind {method} failed for {symbol}: ErrorCode={result.ErrorCode}")

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
            "start_date": str(pd.Timestamp(start_date).date()),
            "end_date": str(pd.Timestamp(end_date).date()),
            "source": "wind",
        }
        self.cache.write_snapshot(dataset, request, frame)


def _value_at(data: Sequence[Sequence[Any]], field_index: int, row_index: int) -> Any:
    value = data[field_index][row_index]
    if value is None:
        return pd.NA
    return value
