"""Market-data interfaces and the local WindPy daily history client."""

from __future__ import annotations

import atexit
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cache
from typing import Any, Sequence

import pandas as pd

from daily_bias_engine.data.cache import RawDataCache


DateLike = str | pd.Timestamp


class MarketDataClient(ABC):
    """Interface for localizable market data clients."""

    @abstractmethod
    def get_daily_ohlcv(self, symbols: Sequence[str], start_date: DateLike, end_date: DateLike) -> pd.DataFrame:
        """Return daily OHLCV bars."""

    @abstractmethod
    def get_futures_open_interest(self, symbols: Sequence[str], start_date: DateLike, end_date: DateLike) -> pd.DataFrame:
        """Return daily futures open interest."""

    @abstractmethod
    def get_interest_rates(self, series: Sequence[str], start_date: DateLike, end_date: DateLike) -> pd.DataFrame:
        """Return daily interest-rate series."""


class MarketDataError(RuntimeError):
    """Raised when a market-data provider is unavailable or returns an error."""


@cache
def get_wind_session() -> Any:
    """Start one SDK session per fetch process. Dashboard imports stay offline."""
    try:
        from WindPy import w
    except (ImportError, OSError) as exc:
        raise MarketDataError(
            "Cannot load the official WindPy SDK. Run scripts/configure_wind.py "
            "with the project virtual environment and check the native library architecture."
        ) from exc
    result = w.start(waitTime=15)
    check_wind_result(result, "start (check the local Wind API login)")
    atexit.register(w.stop)
    return w


def check_wind_result(result: Any, request: str) -> None:
    code = getattr(result, "ErrorCode", None)
    if code != 0:
        raise MarketDataError(f"Wind {request} failed: ErrorCode={code}, {getattr(result, 'Data', None)}")


# Wind EDB ChinaBond government bond yields to maturity, in percent.
YIELD_CODES = {"CGB10Y": "S0059749", "CGB30Y": "S0059752"}


@dataclass
class WindPyDataClient(MarketDataClient):
    cache: RawDataCache | None = None
    asof_time: str = "16:30:00"
    options: str = "PriceAdj=F;Days=Trading;Fill=Blank"

    def get_daily_ohlcv(self, symbols: Sequence[str], start_date: DateLike, end_date: DateLike) -> pd.DataFrame:
        fields = ["open", "high", "low", "close", "volume", "amt"]
        frames = []
        for symbol in symbols:
            last = pd.Timestamp(end_date)
            if symbol == "SPX.GI":
                now = pd.Timestamp.now(tz="America/New_York")
                last_closed = now.tz_localize(None).normalize()
                if now.hour < 16:
                    last_closed -= pd.Timedelta(days=1)
                if last_closed.weekday() >= 5:
                    last_closed -= pd.offsets.BDay(1)
                last = min(last, last_closed)
            if last < pd.Timestamp(start_date):
                continue
            bars = self._wsd(symbol, fields, start_date, last)
            # Wind can carry the previous CLOSE on a holiday even with Fill=Blank.
            bars = bars.dropna(subset=["open", "high", "low", "close"])
            frames.append(bars.assign(symbol=symbol, source="wind"))
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["date", *fields, "symbol", "source"])
        frame = frame.rename(columns={"amt": "amount"})
        return self._finish("daily_ohlcv", symbols, start_date, end_date, frame)

    def get_futures_open_interest(self, symbols: Sequence[str], start_date: DateLike, end_date: DateLike) -> pd.DataFrame:
        frames = []
        for symbol in symbols:
            data = self._wsd(symbol, ["oi", "volume"], start_date, end_date)
            frames.append(data.dropna(subset=["oi"]).assign(symbol=symbol, source="wind"))
        columns = ["date", "oi", "volume", "symbol", "source"]
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)
        frame = frame.rename(columns={"oi": "open_interest"})
        return self._finish("futures_open_interest", symbols, start_date, end_date, frame)

    def get_interest_rates(self, series: Sequence[str], start_date: DateLike, end_date: DateLike) -> pd.DataFrame:
        frames = []
        for name in series:
            if name in YIELD_CODES or name in YIELD_CODES.values():
                code = YIELD_CODES.get(name, name)
                result = get_wind_session().edb(code, _date(start_date), _date(end_date), "")
                check_wind_result(result, f"EDB {name} ({code})")
                values = _history_frame(result, ["close"], start_date, end_date).rename(columns={"close": "rate"})
                source = "wind_edb"
            else:
                code = name
                values = self._wsd(code, ["close"], start_date, end_date).rename(columns={"close": "rate"})
                source = "wind"
            frames.append(values.dropna(subset=["rate"]).assign(series=name, wind_code=code, source=source))
        columns = ["date", "rate", "series", "wind_code", "source"]
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)
        return self._finish("interest_rates", series, start_date, end_date, frame)

    def _wsd(self, symbol: str, fields: Sequence[str], start_date: DateLike, end_date: DateLike) -> pd.DataFrame:
        result = get_wind_session().wsd(symbol, ",".join(fields), _date(start_date), _date(end_date), self.options)
        check_wind_result(result, f"WSD {symbol} {','.join(fields)}")
        return _history_frame(result, fields, start_date, end_date)

    def _finish(self, dataset: str, names: Sequence[str], start_date: DateLike, end_date: DateLike,
                frame: pd.DataFrame) -> pd.DataFrame:
        frame["asof_time"] = self.asof_time
        if self.cache is not None and not frame.empty:
            request = {"dataset": dataset, "names": list(names), "start_date": _date(start_date),
                       "end_date": _date(end_date), "source": "wind"}
            self.cache.write_snapshot(dataset, request, frame)
        return frame


def _history_frame(result: Any, fields: Sequence[str], start_date: DateLike, end_date: DateLike) -> pd.DataFrame:
    dates = pd.DatetimeIndex(pd.to_datetime(result.Times)).normalize()
    frame = pd.DataFrame({"date": dates})
    if len(dates) and (len(result.Data) != len(fields) or any(len(column) != len(dates) for column in result.Data)):
        raise MarketDataError(f"Wind returned inconsistent time series dimensions for {fields}")
    returned_fields = [{"amount": "amt"}.get(str(f).lower(), str(f).lower()) for f in result.Fields]
    if len(dates) and returned_fields != list(fields):
        raise MarketDataError(f"Wind returned fields {result.Fields} for requested {fields}")
    for i, field in enumerate(fields):
        frame[field] = pd.to_numeric(result.Data[i] if len(dates) else [], errors="coerce")
    return frame.loc[frame.date.between(pd.Timestamp(start_date), pd.Timestamp(end_date))].copy()


def _date(value: DateLike) -> str:
    return str(pd.Timestamp(value).date())


WindDataClient = MarketDataClient
WindDataError = MarketDataError
