"""Wind data interfaces and deterministic mock implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence

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
