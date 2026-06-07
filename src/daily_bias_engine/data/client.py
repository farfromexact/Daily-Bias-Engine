"""Wind data interfaces and WindPy implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Sequence

import pandas as pd

from daily_bias_engine.data.cache import RawDataCache


class WindDataClient(ABC):
    """Interface for Wind-like market data clients."""

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
class WindPyDataClient(WindDataClient):
    """WindPy-backed data client.

    The Wind terminal must be installed, running, and logged in before calls can
    succeed. The rest of the engine should normally read persisted snapshots
    rather than calling this class inside dashboard/model processes.
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
