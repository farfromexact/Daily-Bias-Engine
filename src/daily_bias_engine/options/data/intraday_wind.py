"""Read-only Wind intraday queries and a local cache of classified five-minute buckets."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile

import pandas as pd

from daily_bias_engine.data.client import MarketDataError, check_wind_result, get_wind_session
from daily_bias_engine.options.analytics.intraday_gex import BAR, FLOW_COLUMNS, TICK_FIELDS, classify_ticks


def _frame(result, code: str, fields: list[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    empty = pd.DataFrame(columns=fields, index=pd.DatetimeIndex([], name="time"), dtype=float)
    if result.ErrorCode == -40520007:  # Wind no data
        return empty
    check_wind_result(result, f"intraday {code}")
    if not len(result.Times):
        return empty
    names = [{"amount": "amt"}.get(str(x).lower(), str(x).lower()) for x in result.Fields]
    if (names != fields or list(result.Codes) != [code]
            or len(result.Data) != len(fields) or any(len(x) != len(result.Times) for x in result.Data)):
        raise MarketDataError(f"Unexpected Wind intraday response for {code}: codes={result.Codes[:3]}, "
                              f"fields={result.Fields}, timestamps={len(result.Times)}, lengths={[len(x) for x in result.Data]}")
    frame = pd.DataFrame(dict(zip(fields, result.Data)), index=pd.DatetimeIndex(result.Times, name="time"))
    frame = frame.loc[(frame.index >= start) & (frame.index <= end)].sort_index(kind="stable")
    return frame.apply(pd.to_numeric, errors="coerce")


class WindIntradayClient:
    def prices(self, code: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
        result = get_wind_session().wsi(code, "close", str(start), str(end), "BarSize=1")
        prices = _frame(result, code, ["close"], start, end)["close"].dropna()
        return prices[~prices.index.duplicated(keep="last") & prices.gt(0)]

    def ticks(self, code: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        result = get_wind_session().wst(code, ",".join(TICK_FIELDS), str(start), str(end), "")
        return _frame(result, code, TICK_FIELDS, start, end)


class IntradayCache:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.db = root / "touch_flow_prior_second_v1.sqlite3"
        with sqlite3.connect(self.db, timeout=20) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS flow (symbol TEXT, stamp TEXT, multiplier REAL, payload TEXT, "
                         "PRIMARY KEY (symbol, stamp, multiplier))")

    def previous_prices(self, client: WindIntradayClient, code: str, days: pd.DatetimeIndex) -> pd.Series:
        path = self.root / f"{code}_{days[0].date()}_{days[-1].date()}_1m.parquet"
        if path.exists():
            return pd.read_parquet(path)["close"]
        frames = []
        # Keep each WSI response comfortably below the SDK's intraday row limits.
        for i in range(0, len(days), 5):
            chunk = days[i:i + 5]
            frames.append(client.prices(code, chunk[0] + pd.Timedelta(hours=9, minutes=30),
                                        chunk[-1] + pd.Timedelta(hours=15)))
        prices = pd.concat(frames).sort_index()
        prices = prices[prices.index.normalize().isin(days)]
        if set(prices.index.normalize()) == set(days):
            with NamedTemporaryFile(dir=self.root, delete=False) as f:
                stage = Path(f.name)
            try:
                prices.rename("close").to_frame().to_parquet(stage)
                stage.replace(path)
            finally:
                stage.unlink(missing_ok=True)
        return prices

    def flow_buckets(self, client: WindIntradayClient, code: str, multiplier: float,
                     ends: pd.DatetimeIndex) -> pd.DataFrame:
        with sqlite3.connect(self.db, timeout=20) as conn:
            rows = conn.execute("SELECT stamp, payload FROM flow WHERE symbol=? AND multiplier=? AND stamp BETWEEN ? AND ?",
                                (code, multiplier, str(ends[0]), str(ends[-1]))).fetchall()
        cached = {pd.Timestamp(stamp): json.loads(payload) for stamp, payload in rows}
        missing = [stamp for stamp in ends if stamp not in cached]
        while missing:
            count = 1
            while count < min(len(missing), 6) and missing[count] - missing[count - 1] == BAR:
                count += 1
            chunk = pd.DatetimeIndex(missing[:count])
            missing = missing[count:]
            start = chunk[0] - BAR
            session_start = start.normalize() + (pd.Timedelta(hours=13) if start.hour >= 13 else pd.Timedelta(hours=9, minutes=30))
            ticks = client.ticks(code, max(session_start, start - pd.Timedelta(seconds=5)), chunk[-1])
            aggregates = classify_ticks(ticks, chunk, multiplier)
            records = aggregates.to_dict("index")
            cached.update(records)
            with sqlite3.connect(self.db, timeout=20) as conn:
                conn.executemany("INSERT OR REPLACE INTO flow VALUES (?, ?, ?, ?)",
                                 [(code, str(stamp), multiplier, json.dumps(row)) for stamp, row in records.items() if row["complete"]])
        return pd.DataFrame.from_dict(cached, orient="index").reindex(index=ends, columns=FLOW_COLUMNS)
