"""Probe global USD liquidity data availability across multiple providers.

This script is intentionally a data-source smoke test, not a model. It tries
sources in this order for each indicator:

1. iFinD
2. Wind
3. FRED via pandas_datareader, then FRED public CSV
4. yfinance, then Yahoo public chart API
5. Other stable public CSV sources

Failures are recorded per indicator instead of stopping the run. Outputs:

- data/liquidity_data_availability.csv
- data/liquidity_raw_panel.csv
- data/liquidity_charts/*.svg, when enough data is available
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import html
from io import StringIO
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable
from urllib.parse import quote

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from daily_bias_engine.env import load_local_env


load_local_env(PROJECT_ROOT)


@dataclass(frozen=True)
class IndicatorSpec:
    name: str
    preferred_source: str = "iFinD"
    frequency_hint: str = ""
    fred_ids: tuple[str, ...] = ()
    yahoo_tickers: tuple[str, ...] = ()
    stooq_symbols: tuple[str, ...] = ()
    ifind_edb_candidates: tuple[str, ...] = ()
    ifind_hq_candidates: tuple[str, ...] = ()
    wind_candidates: tuple[str, ...] = ()
    comments: str = ""
    is_proxy: bool = False
    proxy_components: tuple[str, ...] = ()


@dataclass
class FetchResult:
    indicator_name: str
    source: str
    code: str
    series: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    frequency: str = ""
    success: bool = False
    error_message: str = ""
    comments: str = ""


INDICATORS: list[IndicatorSpec] = [
    IndicatorSpec(
        name="Fed Balance Sheet / Total Assets",
        frequency_hint="weekly",
        fred_ids=("WALCL",),
        ifind_edb_candidates=("WALCL",),
        wind_candidates=("WALCL",),
        comments="Quantity of liquidity. FRED WALCL is in millions of USD.",
    ),
    IndicatorSpec(
        name="ON RRP",
        frequency_hint="daily",
        fred_ids=("RRPONTSYD",),
        ifind_edb_candidates=("RRPONTSYD",),
        wind_candidates=("RRPONTSYD",),
        comments="Quantity of liquidity. Falling ON RRP usually releases liquidity, so modeling direction should be inverted.",
    ),
    IndicatorSpec(
        name="TGA",
        frequency_hint="weekly",
        fred_ids=("WTREGEN",),
        ifind_edb_candidates=("WTREGEN",),
        wind_candidates=("WTREGEN",),
        comments="Treasury General Account. Rising TGA usually drains liquidity, so modeling direction should be inverted.",
    ),
    IndicatorSpec(
        name="SOFR",
        frequency_hint="daily",
        fred_ids=("SOFR",),
        ifind_edb_candidates=("SOFR",),
        wind_candidates=("SOFR",),
        comments="Funding price, not funding quantity.",
    ),
    IndicatorSpec(
        name="Effective Fed Funds Rate",
        frequency_hint="daily",
        fred_ids=("DFF", "FEDFUNDS"),
        ifind_edb_candidates=("DFF", "FEDFUNDS"),
        wind_candidates=("DFF", "FEDFUNDS"),
        comments="Funding price, not funding quantity.",
    ),
    IndicatorSpec(
        name="3M Treasury Yield",
        frequency_hint="daily",
        fred_ids=("DGS3MO", "DTB3", "TB3MS"),
        ifind_edb_candidates=("DGS3MO", "DTB3", "TB3MS"),
        wind_candidates=("DGS3MO", "DTB3", "TB3MS", "USGG3M.GBM"),
        comments="Funding price / front-end rate.",
    ),
    IndicatorSpec(
        name="2Y Treasury Yield",
        frequency_hint="daily",
        fred_ids=("DGS2",),
        ifind_edb_candidates=("DGS2",),
        wind_candidates=("DGS2", "USGG2YR.GBM"),
        comments="Treasury yield curve point.",
    ),
    IndicatorSpec(
        name="10Y Treasury Yield",
        frequency_hint="daily",
        fred_ids=("DGS10",),
        ifind_edb_candidates=("DGS10",),
        wind_candidates=("DGS10", "USGG10YR.GBM"),
        comments="Treasury yield curve point.",
    ),
    IndicatorSpec(
        name="30Y Treasury Yield",
        frequency_hint="daily",
        fred_ids=("DGS30",),
        ifind_edb_candidates=("DGS30",),
        wind_candidates=("DGS30", "USGG30YR.GBM"),
        comments="Treasury yield curve point.",
    ),
    IndicatorSpec(
        name="10Y TIPS Yield / real yield",
        frequency_hint="daily",
        fred_ids=("DFII10",),
        ifind_edb_candidates=("DFII10",),
        wind_candidates=("DFII10",),
        comments="Real yield. Useful for liquidity/financial-conditions dashboarding.",
    ),
    IndicatorSpec(
        name="DXY",
        frequency_hint="daily",
        yahoo_tickers=("DX-Y.NYB", "DX=F"),
        stooq_symbols=("dxy", "dx.f"),
        ifind_hq_candidates=("DXY.NYB", "DX-Y.NYB", "DX=F"),
        wind_candidates=("DXY.NYB", "DX-Y.NYB", "DX=F"),
        comments="Exact DXY preferred. FRED broad trade-weighted USD is not treated as DXY success.",
    ),
    IndicatorSpec(
        name="VIX",
        frequency_hint="daily",
        fred_ids=("VIXCLS",),
        yahoo_tickers=("^VIX",),
        stooq_symbols=("vix",),
        ifind_hq_candidates=("VIX.GI", "^VIX"),
        wind_candidates=("VIX.GI", "^VIX", "VIXCLS"),
        comments="Risk appetite / financial conditions.",
    ),
    IndicatorSpec(
        name="MOVE Index",
        frequency_hint="daily",
        yahoo_tickers=("^MOVE", "MOVE"),
        stooq_symbols=("move",),
        ifind_hq_candidates=("MOVE.GI", "^MOVE"),
        wind_candidates=("MOVE.GI", "^MOVE"),
        comments="Rates volatility / financial conditions. Public availability may be weaker than VIX.",
    ),
    IndicatorSpec(
        name="HY OAS / High Yield Spread",
        frequency_hint="daily",
        fred_ids=("BAMLH0A0HYM2",),
        ifind_edb_candidates=("BAMLH0A0HYM2",),
        wind_candidates=("BAMLH0A0HYM2",),
        comments="Credit spread / risk appetite.",
    ),
    IndicatorSpec(
        name="Investment Grade OAS / BBB OAS",
        frequency_hint="daily",
        fred_ids=("BAMLC0A4CBBB", "BAMLC0A0CM"),
        ifind_edb_candidates=("BAMLC0A4CBBB", "BAMLC0A0CM"),
        wind_candidates=("BAMLC0A4CBBB", "BAMLC0A0CM"),
        comments="Credit spread / risk appetite. BBB OAS is tried before broad IG OAS.",
    ),
    IndicatorSpec(
        name="Dollar liquidity proxy / Fed Net Liquidity proxy",
        preferred_source="derived_proxy",
        frequency_hint="daily/weekly",
        is_proxy=True,
        proxy_components=("Fed Balance Sheet / Total Assets", "TGA", "ON RRP"),
        comments="Derived proxy: Fed Total Assets - TGA - ON RRP. Components should be aligned and forward-filled.",
    ),
]


BENCHMARKS: list[IndicatorSpec] = [
    IndicatorSpec(
        name="SPX benchmark",
        preferred_source="yfinance",
        frequency_hint="daily",
        fred_ids=("SP500",),
        yahoo_tickers=("^GSPC",),
        stooq_symbols=("^spx", "spx"),
        comments="Supplemental benchmark for charting only.",
    ),
    IndicatorSpec(
        name="Nasdaq benchmark",
        preferred_source="yfinance",
        frequency_hint="daily",
        yahoo_tickers=("^IXIC",),
        stooq_symbols=("^ndq", "ndq"),
        comments="Supplemental benchmark for charting only.",
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Test global USD liquidity data availability.")
    parser.add_argument("--start", default="1990-01-01", help="Start date for provider probes. Default: 1990-01-01.")
    parser.add_argument("--end", default=None, help="End date. Default: today.")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "data"), help="Directory for CSV outputs.")
    parser.add_argument("--chart-dir", default=None, help="Directory for SVG charts. Default: data/liquidity_charts.")
    parser.add_argument("--skip-ifind", action="store_true", help="Skip iFinD attempts.")
    parser.add_argument("--skip-wind", action="store_true", help="Skip Wind attempts.")
    parser.add_argument("--skip-fred", action="store_true", help="Skip FRED attempts.")
    parser.add_argument("--skip-yahoo", action="store_true", help="Skip Yahoo/yfinance attempts.")
    parser.add_argument("--skip-public", action="store_true", help="Skip other public CSV attempts.")
    parser.add_argument("--no-charts", action="store_true", help="Do not create SVG charts.")
    args = parser.parse_args()

    start = pd.Timestamp(args.start).normalize()
    end = pd.Timestamp(args.end).normalize() if args.end else pd.Timestamp.today().normalize()
    output_dir = Path(args.output_dir)
    chart_dir = Path(args.chart_dir) if args.chart_dir else output_dir / "liquidity_charts"
    output_dir.mkdir(parents=True, exist_ok=True)

    availability_rows: list[dict[str, Any]] = []
    raw_series: dict[str, pd.Series] = {}

    for spec in INDICATORS:
        if spec.is_proxy:
            continue
        result = probe_indicator(
            spec,
            start,
            end,
            skip_ifind=args.skip_ifind,
            skip_wind=args.skip_wind,
            skip_fred=args.skip_fred,
            skip_yahoo=args.skip_yahoo,
            skip_public=args.skip_public,
        )
        availability_rows.append(availability_row(spec, result))
        if result.success:
            raw_series[spec.name] = result.series

    proxy_spec = next(item for item in INDICATORS if item.is_proxy)
    proxy_result = build_net_liquidity_proxy(proxy_spec, raw_series)
    availability_rows.append(availability_row(proxy_spec, proxy_result))
    if proxy_result.success:
        raw_series[proxy_spec.name] = proxy_result.series

    availability = pd.DataFrame(availability_rows)
    raw_panel = build_raw_panel(raw_series)

    availability_path = output_dir / "liquidity_data_availability.csv"
    raw_panel_path = output_dir / "liquidity_raw_panel.csv"
    availability.to_csv(availability_path, index=False, encoding="utf-8-sig")
    raw_panel.to_csv(raw_panel_path, index=False, encoding="utf-8-sig")

    chart_manifest = pd.DataFrame()
    if not args.no_charts:
        benchmark_series = fetch_benchmarks(start, end, args)
        chart_manifest = create_charts(raw_panel, benchmark_series, chart_dir)

    print_summary(availability, raw_panel, availability_path, raw_panel_path, chart_manifest)


def probe_indicator(
    spec: IndicatorSpec,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    skip_ifind: bool,
    skip_wind: bool,
    skip_fred: bool,
    skip_yahoo: bool,
    skip_public: bool,
) -> FetchResult:
    attempts: list[str] = []
    source_calls: list[tuple[str, Callable[[], FetchResult]]] = []

    if not skip_ifind:
        source_calls.append(("iFinD", lambda: fetch_ifind_series(spec, start, end)))
    if not skip_wind:
        source_calls.append(("Wind", lambda: fetch_wind_series(spec, start, end)))
    if not skip_fred:
        source_calls.append(("FRED", lambda: fetch_fred_series(spec, start, end)))
    if not skip_yahoo:
        source_calls.append(("Yahoo", lambda: fetch_yahoo_series(spec, start, end)))
    if not skip_public:
        source_calls.append(("public_csv", lambda: fetch_public_csv_series(spec, start, end)))

    for source_name, fetcher in source_calls:
        try:
            result = fetcher()
        except Exception as exc:  # pragma: no cover - defensive safety for provider clients
            result = FetchResult(
                indicator_name=spec.name,
                source=source_name,
                code="",
                success=False,
                error_message=f"Unhandled {type(exc).__name__}: {exc}",
                comments=spec.comments,
            )
        if result.success and not result.series.empty:
            return result
        attempts.append(f"{source_name}: {result.error_message or 'no data'}")
    return FetchResult(
        indicator_name=spec.name,
        source="",
        code="",
        success=False,
        error_message=" | ".join(attempts),
        comments=spec.comments,
    )


def fetch_ifind_series(spec: IndicatorSpec, start: pd.Timestamp, end: pd.Timestamp) -> FetchResult:
    candidates = list(spec.ifind_edb_candidates) + list(spec.ifind_hq_candidates)
    if not candidates:
        return failure(spec, "iFinD", "", "No iFinD candidates configured.")
    username = os.environ.get("IFIND_USERNAME")
    password = os.environ.get("IFIND_PASSWORD")
    if not username or not password:
        return failure(spec, "iFinD", ",".join(candidates), "Missing IFIND_USERNAME/IFIND_PASSWORD.")
    try:
        from iFinDPy import THS_EDB, THS_HQ, THS_GetErrorInfo, THS_iFinDLogin, THS_iFinDLogout
    except Exception as exc:
        return failure(spec, "iFinD", ",".join(candidates), f"iFinDPy unavailable: {type(exc).__name__}: {exc}")

    login_code = THS_iFinDLogin(username, password)
    if login_code != 0:
        try:
            message = THS_GetErrorInfo(login_code)
        except Exception:
            message = str(login_code)
        return failure(spec, "iFinD", ",".join(candidates), f"iFinD login failed: {message}")

    errors: list[str] = []
    try:
        for code in spec.ifind_edb_candidates:
            result = THS_EDB(code, "", date_text(start), date_text(end))
            series, error = parse_ifind_result(result, code)
            if error:
                errors.append(f"EDB {code}: {error}")
                continue
            return success(spec, "iFinD", code, series, comments=spec.comments)
        for code in spec.ifind_hq_candidates:
            result = THS_HQ(code, "close", "", date_text(start), date_text(end))
            series, error = parse_ifind_result(result, code)
            if error:
                errors.append(f"HQ {code}: {error}")
                continue
            return success(spec, "iFinD", code, series, comments=spec.comments)
    finally:
        try:
            THS_iFinDLogout()
        except Exception:
            pass
    return failure(spec, "iFinD", ",".join(candidates), "; ".join(errors) or "No iFinD data returned.")


def fetch_wind_series(spec: IndicatorSpec, start: pd.Timestamp, end: pd.Timestamp) -> FetchResult:
    candidates = list(spec.wind_candidates)
    if not candidates:
        return failure(spec, "Wind", "", "No Wind candidates configured.")
    try:
        from WindPy import w
    except Exception as exc:
        return failure(spec, "Wind", ",".join(candidates), f"WindPy unavailable: {type(exc).__name__}: {exc}")

    try:
        start_result = w.start()
        if getattr(start_result, "ErrorCode", 0) != 0:
            return failure(spec, "Wind", ",".join(candidates), f"Wind start failed: {wind_error(start_result)}")
        errors = []
        for code in candidates:
            for method in ("wsd", "edb"):
                try:
                    if method == "wsd":
                        result = w.wsd(code, "close", date_text(start), date_text(end), "PriceAdj=F")
                    else:
                        result = w.edb(code, date_text(start), date_text(end), "")
                    series, error = parse_wind_result(result, code)
                    if error:
                        errors.append(f"{method} {code}: {error}")
                        continue
                    return success(spec, "Wind", code, series, comments=spec.comments)
                except Exception as exc:
                    errors.append(f"{method} {code}: {type(exc).__name__}: {exc}")
        return failure(spec, "Wind", ",".join(candidates), "; ".join(errors) or "No Wind data returned.")
    finally:
        try:
            w.stop()
        except Exception:
            pass


def fetch_fred_series(spec: IndicatorSpec, start: pd.Timestamp, end: pd.Timestamp) -> FetchResult:
    if not spec.fred_ids:
        return failure(spec, "FRED", "", "No FRED series configured.")
    errors: list[str] = []
    for fred_id in spec.fred_ids:
        try:
            series = fetch_fred_with_pandas_datareader(fred_id, start, end)
            if not series.empty:
                return success(spec, "FRED/pandas_datareader", fred_id, series, comments=spec.comments)
        except Exception as exc:
            errors.append(f"pandas_datareader {fred_id}: {type(exc).__name__}: {exc}")
        try:
            series = fetch_fred_public_csv(fred_id)
            series = series[(series.index >= start) & (series.index <= end)]
            if not series.empty:
                return success(spec, "FRED/public_csv", fred_id, series, comments=spec.comments)
            errors.append(f"public_csv {fred_id}: empty after date filter")
        except Exception as exc:
            errors.append(f"public_csv {fred_id}: {type(exc).__name__}: {exc}")
    return failure(spec, "FRED", ",".join(spec.fred_ids), "; ".join(errors))


def fetch_yahoo_series(spec: IndicatorSpec, start: pd.Timestamp, end: pd.Timestamp) -> FetchResult:
    if not spec.yahoo_tickers:
        return failure(spec, "Yahoo", "", "No Yahoo tickers configured.")
    errors: list[str] = []
    for ticker in spec.yahoo_tickers:
        try:
            series = fetch_yfinance_package(ticker, start, end)
            if not series.empty:
                return success(spec, "yfinance", ticker, series, comments=spec.comments)
        except Exception as exc:
            errors.append(f"yfinance {ticker}: {type(exc).__name__}: {exc}")
        try:
            series = fetch_yahoo_chart_api(ticker, start, end)
            if not series.empty:
                return success(spec, "Yahoo/chart_api", ticker, series, comments=spec.comments)
            errors.append(f"chart_api {ticker}: empty")
        except Exception as exc:
            errors.append(f"chart_api {ticker}: {type(exc).__name__}: {exc}")
    return failure(spec, "Yahoo", ",".join(spec.yahoo_tickers), "; ".join(errors))


def fetch_public_csv_series(spec: IndicatorSpec, start: pd.Timestamp, end: pd.Timestamp) -> FetchResult:
    if not spec.stooq_symbols:
        return failure(spec, "public_csv", "", "No public CSV candidates configured.")
    errors = []
    for symbol in spec.stooq_symbols:
        try:
            series = fetch_stooq_csv(symbol, start, end)
            if not series.empty:
                return success(spec, "Stooq/public_csv", symbol, series, comments=spec.comments)
            errors.append(f"{symbol}: empty")
        except Exception as exc:
            errors.append(f"{symbol}: {type(exc).__name__}: {exc}")
    return failure(spec, "public_csv", ",".join(spec.stooq_symbols), "; ".join(errors))


def build_net_liquidity_proxy(spec: IndicatorSpec, raw_series: dict[str, pd.Series]) -> FetchResult:
    missing = [name for name in spec.proxy_components if name not in raw_series or raw_series[name].empty]
    if missing:
        return failure(spec, "derived_proxy", "Fed Total Assets - TGA - ON RRP", f"Missing components: {missing}")
    panel = build_raw_panel({name: raw_series[name] for name in spec.proxy_components})
    if panel.empty:
        return failure(spec, "derived_proxy", "Fed Total Assets - TGA - ON RRP", "Component panel is empty.")
    panel = panel.set_index("date").sort_index().ffill()
    value = panel["Fed Balance Sheet / Total Assets"] - panel["TGA"] - panel["ON RRP"]
    value = clean_series(value)
    if value.empty:
        return failure(spec, "derived_proxy", "Fed Total Assets - TGA - ON RRP", "Derived series is empty.")
    return success(spec, "derived_proxy", "Fed Total Assets - TGA - ON RRP", value, comments=spec.comments)


def fetch_benchmarks(start: pd.Timestamp, end: pd.Timestamp, args: argparse.Namespace) -> dict[str, pd.Series]:
    benchmarks: dict[str, pd.Series] = {}
    for spec in BENCHMARKS:
        result = probe_indicator(
            spec,
            start,
            end,
            skip_ifind=True,
            skip_wind=True,
            skip_fred=args.skip_fred,
            skip_yahoo=args.skip_yahoo,
            skip_public=args.skip_public,
        )
        if result.success:
            benchmarks[spec.name] = result.series
    return benchmarks


def fetch_fred_with_pandas_datareader(fred_id: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    from pandas_datareader import data as pdr

    frame = pdr.DataReader(fred_id, "fred", start, end)
    if frame.empty:
        return pd.Series(dtype=float)
    return normalize_series(frame.iloc[:, 0], fred_id)


def fetch_fred_public_csv(fred_id: str) -> pd.Series:
    import requests

    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={quote(fred_id)}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    frame = pd.read_csv(StringIO(response.text))
    if "observation_date" in frame.columns:
        date_col = "observation_date"
    elif "DATE" in frame.columns:
        date_col = "DATE"
    else:
        date_col = frame.columns[0]
    value_col = fred_id if fred_id in frame.columns else frame.columns[-1]
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    values = pd.to_numeric(frame[value_col].replace(".", pd.NA), errors="coerce")
    series = pd.Series(values.to_numpy(), index=frame[date_col], name=fred_id)
    return clean_series(series)


def fetch_yfinance_package(ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    import yfinance as yf

    frame = yf.download(ticker, start=date_text(start), end=date_text(end + pd.Timedelta(days=1)), progress=False, auto_adjust=False)
    if frame.empty:
        return pd.Series(dtype=float)
    for column in ("Adj Close", "Close"):
        if column in frame.columns:
            return normalize_series(frame[column], ticker)
    return pd.Series(dtype=float)


def fetch_yahoo_chart_api(ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    import requests

    period1 = int(start.replace(tzinfo=timezone.utc).timestamp())
    period2 = int((end + pd.Timedelta(days=1)).replace(tzinfo=timezone.utc).timestamp())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote(ticker, safe='')}?period1={period1}&period2={period2}&interval=1d&events=history&includeAdjustedClose=true"
    )
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    payload = response.json()
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(chart["error"])
    results = chart.get("result") or []
    if not results:
        return pd.Series(dtype=float)
    result = results[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators", {})
    quote_data = (indicators.get("adjclose") or indicators.get("quote") or [{}])[0]
    values = quote_data.get("adjclose") or quote_data.get("close") or []
    if not timestamps or not values:
        return pd.Series(dtype=float)
    dates = pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None).normalize()
    return clean_series(pd.Series(values, index=dates, name=ticker))


def fetch_stooq_csv(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    import requests

    url = f"https://stooq.com/q/d/l/?s={quote(symbol.lower())}&d1={start:%Y%m%d}&d2={end:%Y%m%d}&i=d"
    response = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    if "No data" in response.text or not response.text.strip():
        return pd.Series(dtype=float)
    frame = pd.read_csv(StringIO(response.text))
    if frame.empty or "Date" not in frame.columns:
        return pd.Series(dtype=float)
    close_col = "Close" if "Close" in frame.columns else frame.columns[-1]
    dates = pd.to_datetime(frame["Date"], errors="coerce")
    values = pd.to_numeric(frame[close_col], errors="coerce")
    return clean_series(pd.Series(values.to_numpy(), index=dates, name=symbol))


def parse_ifind_result(result: Any, code: str) -> tuple[pd.Series, str]:
    errorcode = getattr(result, "errorcode", 0)
    if errorcode not in (0, None):
        errmsg = getattr(result, "errmsg", "")
        return pd.Series(dtype=float), f"errorcode={errorcode}; errmsg={errmsg}"
    data = getattr(result, "data", None)
    if not isinstance(data, pd.DataFrame) or data.empty:
        return pd.Series(dtype=float), "empty data"
    frame = data.copy()
    date_col = pick_column(frame, ("time", "date", "datetime", "trade_date"))
    value_col = pick_column(frame, ("value", "close", "CLOSE", code))
    if date_col is None or value_col is None:
        return pd.Series(dtype=float), f"cannot identify date/value columns: {list(frame.columns)}"
    series = pd.Series(pd.to_numeric(frame[value_col], errors="coerce").to_numpy(), index=pd.to_datetime(frame[date_col], errors="coerce"), name=code)
    series = clean_series(series)
    if series.empty:
        return series, "all values are empty"
    return series, ""


def parse_wind_result(result: Any, code: str) -> tuple[pd.Series, str]:
    if getattr(result, "ErrorCode", 0) != 0:
        return pd.Series(dtype=float), wind_error(result)
    times = getattr(result, "Times", None) or []
    data = getattr(result, "Data", None) or []
    if not times or not data:
        return pd.Series(dtype=float), "empty Times/Data"
    values = data[0] if isinstance(data[0], list) else data
    series = pd.Series(values, index=pd.to_datetime(times, errors="coerce"), name=code)
    series = clean_series(series)
    if series.empty:
        return series, "all values are empty"
    return series, ""


def success(spec: IndicatorSpec, source: str, code: str, series: pd.Series, comments: str = "") -> FetchResult:
    cleaned = clean_series(series)
    return FetchResult(
        indicator_name=spec.name,
        source=source,
        code=code,
        series=cleaned,
        frequency=infer_frequency(cleaned, spec.frequency_hint),
        success=not cleaned.empty,
        comments=comments,
    )


def failure(spec: IndicatorSpec, source: str, code: str, message: str) -> FetchResult:
    return FetchResult(
        indicator_name=spec.name,
        source=source,
        code=code,
        success=False,
        error_message=message,
        comments=spec.comments,
        frequency=spec.frequency_hint,
    )


def availability_row(spec: IndicatorSpec, result: FetchResult) -> dict[str, Any]:
    series = result.series if result.success else pd.Series(dtype=float)
    latest_value = ""
    if result.success and not series.empty:
        latest_value = float(series.iloc[-1])
    return {
        "indicator_name": spec.name,
        "preferred_source": spec.preferred_source,
        "actual_source_found": result.source if result.success else "",
        "ticker_or_code": result.code,
        "frequency": result.frequency or spec.frequency_hint,
        "start_date_available": date_text(series.index.min()) if result.success and not series.empty else "",
        "latest_date": date_text(series.index.max()) if result.success and not series.empty else "",
        "latest_value": latest_value,
        "success / fail": "success" if result.success else "fail",
        "error_message": "" if result.success else result.error_message,
        "comments": result.comments or spec.comments,
    }


def build_raw_panel(series_map: dict[str, pd.Series]) -> pd.DataFrame:
    cleaned: dict[str, pd.Series] = {}
    for name, series in series_map.items():
        values = clean_series(series)
        if not values.empty:
            cleaned[name] = values
    if not cleaned:
        return pd.DataFrame(columns=["date"])
    panel = pd.concat(cleaned, axis=1, sort=True).sort_index()
    panel.index = pd.to_datetime(panel.index).normalize()
    panel = panel[~panel.index.duplicated(keep="last")]
    panel.index.name = "date"
    panel = panel.reset_index().rename(columns={"index": "date"})
    panel["date"] = pd.to_datetime(panel["date"]).dt.date.astype(str)
    return panel


def create_charts(raw_panel: pd.DataFrame, benchmarks: dict[str, pd.Series], chart_dir: Path) -> pd.DataFrame:
    chart_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []

    panel = raw_panel.copy()
    if not panel.empty and "date" in panel.columns:
        panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
        panel = panel.set_index("date").sort_index()

    def add_chart(chart_name: str, columns: dict[str, pd.Series | pd.DataFrame | pd.Series]) -> None:
        path = chart_dir / f"{slug(chart_name)}.svg"
        try:
            svg = render_svg_chart(chart_name, columns)
            path.write_text(svg, encoding="utf-8")
            rows.append({"chart_name": chart_name, "path": str(path), "success / fail": "success", "error_message": ""})
        except Exception as exc:
            rows.append({"chart_name": chart_name, "path": str(path), "success / fail": "fail", "error_message": str(exc)})

    if "Dollar liquidity proxy / Fed Net Liquidity proxy" in panel.columns:
        normalized: dict[str, pd.Series] = {"Fed Net Liquidity": panel["Dollar liquidity proxy / Fed Net Liquidity proxy"]}
        for benchmark_name, series in benchmarks.items():
            label = "SPX" if benchmark_name.startswith("SPX") else "Nasdaq"
            normalized[label] = series
        add_chart("Fed Net Liquidity vs SPX Nasdaq", normalized)

    chart_map = {
        "ON RRP": "ON RRP",
        "TGA": "TGA",
        "SOFR": "SOFR",
        "3M Treasury": "3M Treasury Yield",
        "DXY": "DXY",
        "HY Spread": "HY OAS / High Yield Spread",
        "MOVE": "MOVE Index",
    }
    for title, column in chart_map.items():
        if column in panel.columns:
            add_chart(title, {column: panel[column]})
        else:
            rows.append(
                {
                    "chart_name": title,
                    "path": "",
                    "success / fail": "fail",
                    "error_message": f"Column not available: {column}",
                }
            )

    manifest = pd.DataFrame(rows)
    manifest.to_csv(chart_dir / "chart_manifest.csv", index=False, encoding="utf-8-sig")
    return manifest


def render_svg_chart(title: str, series_map: dict[str, pd.Series]) -> str:
    cleaned: dict[str, pd.Series] = {}
    for name, series in series_map.items():
        values = clean_series(series)
        if values.empty:
            continue
        cleaned[name] = values
    if not cleaned:
        raise ValueError("No non-empty series to plot.")

    if len(cleaned) > 1:
        common_start = max(series.index.min() for series in cleaned.values())
        common_end = min(series.index.max() for series in cleaned.values())
        normalized: dict[str, pd.Series] = {}
        for name, series in cleaned.items():
            subset = series[(series.index >= common_start) & (series.index <= common_end)].dropna()
            if subset.empty:
                continue
            first = subset.iloc[0]
            if first == 0 or pd.isna(first):
                continue
            normalized[name] = subset / first * 100.0
        cleaned = normalized
        if not cleaned:
            raise ValueError("No overlapping non-zero data to normalize.")

    width = 980
    height = 440
    margin_left = 68
    margin_right = 26
    margin_top = 54
    margin_bottom = 52
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    all_dates = pd.concat(cleaned.values()).index
    min_date = pd.Timestamp(all_dates.min())
    max_date = pd.Timestamp(all_dates.max())
    all_values = pd.concat(cleaned.values()).astype(float)
    min_value = float(all_values.min())
    max_value = float(all_values.max())
    if math.isclose(min_value, max_value):
        min_value -= 1.0
        max_value += 1.0
    pad = (max_value - min_value) * 0.08
    min_value -= pad
    max_value += pad

    def x_pos(ts: pd.Timestamp) -> float:
        if min_date == max_date:
            return margin_left + plot_width / 2
        return margin_left + ((pd.Timestamp(ts) - min_date).days / max(1, (max_date - min_date).days)) * plot_width

    def y_pos(value: float) -> float:
        return margin_top + (1 - ((value - min_value) / (max_value - min_value))) * plot_height

    palette = ["#2563eb", "#dc2626", "#059669", "#9333ea", "#f97316"]
    lines = []
    legend = []
    for idx, (name, series) in enumerate(cleaned.items()):
        color = palette[idx % len(palette)]
        sampled = downsample_series(series, max_points=700)
        points = " ".join(f"{x_pos(ts):.1f},{y_pos(float(value)):.1f}" for ts, value in sampled.items())
        if points:
            lines.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.2" points="{points}" />')
            legend_y = 22 + idx * 20
            legend.append(
                f'<line x1="{margin_left + 530}" y1="{legend_y}" x2="{margin_left + 552}" y2="{legend_y}" stroke="{color}" stroke-width="3" />'
                f'<text x="{margin_left + 560}" y="{legend_y + 4}" font-size="13" fill="#111827">{html.escape(name)}</text>'
            )

    y_ticks = []
    for value in linspace(min_value, max_value, 5):
        y = y_pos(value)
        y_ticks.append(
            f'<line x1="{margin_left}" y1="{y:.1f}" x2="{width - margin_right}" y2="{y:.1f}" stroke="#e5e7eb" />'
            f'<text x="{margin_left - 10}" y="{y + 4:.1f}" text-anchor="end" font-size="12" fill="#6b7280">{value:.2f}</text>'
        )
    x_labels = [
        (min_date, date_text(min_date)),
        (min_date + (max_date - min_date) / 2, date_text(min_date + (max_date - min_date) / 2)),
        (max_date, date_text(max_date)),
    ]
    x_ticks = [
        f'<text x="{x_pos(ts):.1f}" y="{height - 18}" text-anchor="middle" font-size="12" fill="#6b7280">{label}</text>'
        for ts, label in x_labels
    ]
    note = "Indexed to 100 over common window" if len(series_map) > 1 else "Raw value"
    return "\n".join(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" width="980" height="440" viewBox="0 0 980 440">',
            '<rect width="100%" height="100%" fill="white" />',
            f'<text x="{margin_left}" y="30" font-size="20" font-weight="700" fill="#111827">{html.escape(title)}</text>',
            f'<text x="{margin_left}" y="50" font-size="12" fill="#6b7280">{html.escape(note)}</text>',
            *legend,
            *y_ticks,
            f'<line x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}" stroke="#9ca3af" />',
            f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}" stroke="#9ca3af" />',
            *lines,
            *x_ticks,
            "</svg>",
        ]
    )


def print_summary(
    availability: pd.DataFrame,
    raw_panel: pd.DataFrame,
    availability_path: Path,
    raw_panel_path: Path,
    chart_manifest: pd.DataFrame,
) -> None:
    print(f"availability_csv={availability_path}")
    print(f"raw_panel_csv={raw_panel_path}")
    if not chart_manifest.empty:
        successes = int((chart_manifest["success / fail"] == "success").sum())
        print(f"charts={successes}/{len(chart_manifest)} saved under {availability_path.parent / 'liquidity_charts'}")
    successes = availability[availability["success / fail"] == "success"]
    print(f"indicator_success={len(successes)}/{len(availability)}")
    if not successes.empty:
        print("sources_found=" + json.dumps(successes["actual_source_found"].value_counts().to_dict(), ensure_ascii=False))
    ifind_count = int((successes["actual_source_found"] == "iFinD").sum()) if not successes.empty else 0
    wind_count = int((successes["actual_source_found"] == "Wind").sum()) if not successes.empty else 0
    if ifind_count or wind_count:
        answer = f"iFinD/Wind partial support: iFinD={ifind_count}, Wind={wind_count} successful indicators."
    else:
        answer = "iFinD/Wind support not confirmed in this run; dashboard would need FRED/Yahoo/public fallbacks unless local terminals are fixed."
    print("liquidity_dashboard_answer=" + answer)
    print(f"raw_panel_shape={raw_panel.shape}")


def normalize_series(series: pd.Series, name: str) -> pd.Series:
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]
    series = pd.Series(series.to_numpy(), index=pd.to_datetime(series.index, errors="coerce"), name=name)
    return clean_series(series)


def clean_series(series: pd.Series) -> pd.Series:
    if series is None or len(series) == 0:
        return pd.Series(dtype=float)
    output = pd.Series(series).copy()
    output.index = pd.to_datetime(output.index, errors="coerce")
    output = output[~pd.isna(output.index)]
    output = pd.to_numeric(output, errors="coerce").dropna()
    output.index = pd.DatetimeIndex(output.index).normalize()
    output = output[~output.index.duplicated(keep="last")]
    output = output.sort_index()
    output.name = getattr(series, "name", None)
    return output


def infer_frequency(series: pd.Series, hint: str = "") -> str:
    if series.empty:
        return hint
    if len(series) < 3:
        return hint or "unknown"
    diffs = pd.Series(series.index).diff().dropna().dt.days
    median_days = float(diffs.median())
    if median_days <= 2:
        return "daily"
    if 5 <= median_days <= 9:
        return "weekly"
    if 25 <= median_days <= 35:
        return "monthly"
    return f"irregular median {median_days:.1f} days"


def downsample_series(series: pd.Series, max_points: int) -> pd.Series:
    if len(series) <= max_points:
        return series
    step = math.ceil(len(series) / max_points)
    return series.iloc[::step]


def linspace(start: float, end: float, count: int) -> list[float]:
    if count <= 1:
        return [start]
    step = (end - start) / (count - 1)
    return [start + step * index for index in range(count)]


def pick_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    lowered = {str(column).lower(): column for column in frame.columns}
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def wind_error(result: Any) -> str:
    code = getattr(result, "ErrorCode", "")
    data = getattr(result, "Data", "")
    return f"ErrorCode={code}; Data={data}"


def date_text(value: Any) -> str:
    return str(pd.Timestamp(value).date())


def slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


if __name__ == "__main__":
    started = time.time()
    try:
        main()
    finally:
        elapsed = time.time() - started
        print(f"completed_at={datetime.now().isoformat(timespec='seconds')} elapsed_seconds={elapsed:.2f}")
