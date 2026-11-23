"""Build and atomically publish time-stamped Intraday GEX research snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

from daily_bias_engine.options.analytics.intraday_gex import (
    BAR, PRODUCT_ROOTS, SHANGHAI, completed_bar, estimate_intraday_gex, iso_time, local_time, select_contracts, window_bars,
)
from daily_bias_engine.options.data.contract_master import get_product_metadata
from daily_bias_engine.options.data.intraday_wind import IntradayCache, WindIntradayClient
from daily_bias_engine.options.data.market_data_store import OptionMarketDataStore


def report_dates(data_root: Path, product: str) -> list[str]:
    directory = data_root / "intraday_gex" / f"product_group={product}"
    return sorted(p.name.removeprefix("trade_date=") for p in directory.glob("trade_date=????-??-??") if p.is_dir())


def report_paths(data_root: Path, product: str, day: str) -> list[Path]:
    directory = data_root / "intraday_gex" / f"product_group={product}" / f"trade_date={day}"
    return sorted(directory.glob("[0-2][0-9][0-5][0-9]_*.json"))


def latest_visible_report(data_root: Path, product: str, cutoff: pd.Timestamp) -> dict | None:
    day_limit = str(cutoff.date())
    published_limit = cutoff.strftime("%Y%m%dT%H%M%S%f")
    for day in reversed(report_dates(data_root, product)):
        if day > day_limit:
            continue
        for path in reversed(report_paths(data_root, product, day)):
            clock, published = path.stem.split("_", 1)
            if (day == day_limit and clock > cutoff.strftime("%H%M")) or published > published_limit:
                continue
            report = json.loads(path.read_text(encoding="utf-8"))
            if local_time(report["as_of"]) <= cutoff and local_time(report["computed_at"]) <= cutoff:
                return report
    return None


def build_snapshot(product: str, as_of: pd.Timestamp, sessions: pd.DatetimeIndex, data_root: Path,
                   cache: IntradayCache, client: WindIntradayClient) -> dict:
    if product not in PRODUCT_ROOTS.values():
        raise ValueError(f"Unsupported option product {product}.")
    end = completed_bar(as_of, sessions)
    days = sessions[sessions < end.normalize()].unique().sort_values()[-20:]
    if days.empty:
        raise ValueError("No preceding exchange session for the option-chain baseline.")
    previous = days[-1]
    store = OptionMarketDataStore(data_root)
    chain = store.read_normalized_chain(product, previous)
    if not pd.to_datetime(chain.trade_date).dt.normalize().eq(previous).all() or not chain.product_group.eq(product).all():
        raise ValueError(f"{product} prior chain does not match {previous.date()}.")
    selected, coverage = select_contracts(chain, end.normalize(), limit=20)
    index_code = get_product_metadata(product).instruments[0].reference_index_code
    ends = window_bars(end)
    start = ends[0] - BAR
    previous_prices = cache.previous_prices(client, index_code, days)
    spots = {code: client.prices(code, start, end) for code in sorted(set(selected.underlying_code) | {index_code})}
    index_prices = pd.concat([previous_prices, spots[index_code]]).sort_index()
    flows = {row.option_code: cache.flow_buckets(client, row.option_code, float(row.multiplier_or_contract_unit), ends)
             for row in selected.itertuples()}
    report = estimate_intraday_gex(selected, coverage, flows, spots, index_prices, end)
    report["computed_at"] = iso_time(pd.Timestamp.now(tz=SHANGHAI))
    report["source"] = "WindPy WST / WSI"
    report["index_code"] = index_code
    return report


def publish_snapshot(report: dict, data_root: Path) -> Path:
    end = local_time(report["as_of"])
    directory = data_root / "intraday_gex" / f"product_group={report['product']}" / f"trade_date={end.date()}"
    directory.mkdir(parents=True, exist_ok=True)
    published = local_time(report["computed_at"])
    path = directory / f"{end:%H%M}_{published:%Y%m%dT%H%M%S%f}.json"
    existing = sorted(directory.glob(f"{end:%H%M}_*.json"))
    if existing:
        latest = json.loads(existing[-1].read_text(encoding="utf-8"))
        if {**latest, "computed_at": report["computed_at"]} == report:
            return existing[-1]
    body = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as f:
        stage = Path(f.name)
        f.write(body)
    try:
        try:
            path.hardlink_to(stage)
        except FileExistsError:
            if json.loads(path.read_text(encoding="utf-8")) != report:
                raise ValueError(f"Conflicting GEX revision at {path.name}")
    finally:
        stage.unlink(missing_ok=True)
    return path
