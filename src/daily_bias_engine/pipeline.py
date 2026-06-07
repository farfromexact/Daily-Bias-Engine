"""End-to-end pipeline and local snapshot utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from daily_bias_engine.backtest import evaluate_bias_predictions
from daily_bias_engine.data import WindDataClient
from daily_bias_engine.engine import DailyBiasEngine
from daily_bias_engine.features import calculate_all_features
from daily_bias_engine.labeling import label_market_results
from daily_bias_engine.report import build_daily_report

RAW_TABLES = [
    "index_ohlcv",
    "futures_ohlcv",
    "open_interest",
    "rates",
    "etf_flow",
    "overseas_ohlcv",
    "ashare_ohlcv",
]


def default_history_range(
    years: int = 3,
    end_date: str | pd.Timestamp | None = None,
) -> tuple[str, str]:
    """Return the default trailing history range for snapshot generation."""

    if years <= 0:
        raise ValueError("years must be positive.")
    end = _latest_business_day(end_date)
    start = end - pd.DateOffset(years=years)
    return str(start.date()), str(end.date())


@dataclass(frozen=True)
class SnapshotInfo:
    path: Path
    label: str
    source: str
    start_date: str
    end_date: str
    created_at: str


def fetch_raw_inputs(
    client: WindDataClient,
    start_date: str,
    end_date: str,
) -> dict[str, pd.DataFrame]:
    """Fetch raw inputs used by the current MVP factor set."""

    etf_flow = _with_margin_balance(client.get_daily_ohlcv(["510300.SH", "510500.SH"], start_date, end_date))
    return {
        "index_ohlcv": client.get_daily_ohlcv(["000300.SH"], start_date, end_date),
        "futures_ohlcv": client.get_daily_ohlcv(["IF.CFE"], start_date, end_date),
        "open_interest": client.get_futures_open_interest(["IF.CFE"], start_date, end_date),
        "rates": client.get_interest_rates(["DR007.IB", "CGB10Y.IB"], start_date, end_date),
        "etf_flow": etf_flow,
        "overseas_ohlcv": client.get_daily_ohlcv(["SPX.GI", "HSI.HI"], start_date, end_date),
        "ashare_ohlcv": client.get_daily_ohlcv(["000300.SH", "000905.SH", "000852.SH"], start_date, end_date),
    }


def _latest_business_day(date_value: str | pd.Timestamp | None = None) -> pd.Timestamp:
    if date_value is None:
        value = pd.Timestamp.now(tz="Asia/Shanghai")
    else:
        value = pd.Timestamp(date_value)
    if value.tzinfo is not None:
        value = value.tz_convert("Asia/Shanghai").tz_localize(None)
    value = value.normalize()
    while value.weekday() >= 5:
        value -= pd.Timedelta(days=1)
    return value


def run_pipeline_from_client(
    client: WindDataClient,
    start_date: str,
    end_date: str,
    config_dir: Path | str,
    data_mode: str,
) -> dict[str, Any]:
    raw = fetch_raw_inputs(client, start_date, end_date)
    return run_pipeline_from_raw(raw, config_dir=config_dir, data_mode=data_mode)


def run_pipeline_from_raw(
    raw: Mapping[str, pd.DataFrame],
    config_dir: Path | str,
    data_mode: str = "snapshot",
) -> dict[str, Any]:
    """Run factors, scoring, labeling, and metrics from raw DataFrames."""

    config_path = Path(config_dir)
    missing = [name for name in RAW_TABLES if name not in raw]
    if missing:
        raise ValueError(f"Snapshot raw data is missing tables: {missing}")

    factors = calculate_all_features(
        index_ohlcv=raw["index_ohlcv"],
        futures_ohlcv=raw["futures_ohlcv"],
        open_interest=raw["open_interest"],
        rates=raw["rates"],
        etf_flow=raw["etf_flow"],
        overseas_ohlcv=raw["overseas_ohlcv"],
        ashare_ohlcv=raw["ashare_ohlcv"],
    )
    engine = DailyBiasEngine.from_yaml(config_path / "factor_weights.yaml", config_path / "thresholds.yaml")
    scores = engine.score(factors)

    threshold_config = _load_yaml(config_path / "thresholds.yaml")
    labels = label_market_results(raw["index_ohlcv"], symbol="000300.SH", **threshold_config.get("labeling", {}))
    metrics = evaluate_bias_predictions(scores, labels, **threshold_config.get("backtest", {}))
    report = build_daily_report(factors=factors, engine_output=scores, labels=labels, metrics=metrics)

    return {
        "factors": factors,
        "scores": scores,
        "labels": labels,
        "metrics": metrics,
        "report": report,
        "data_mode": data_mode,
        "raw": dict(raw),
    }


def save_snapshot(
    result: Mapping[str, Any],
    output_root: Path | str,
    source: str,
    start_date: str,
    end_date: str,
) -> Path:
    """Persist raw inputs and computed outputs as a local Parquet snapshot."""

    root = Path(output_root)
    created_at = pd.Timestamp.now(tz="Asia/Shanghai").strftime("%Y%m%dT%H%M%S%z")
    snapshot_dir = root / f"{created_at}_{source}_{start_date}_{end_date}".replace(":", "").replace("/", "-")
    raw_dir = snapshot_dir / "raw"
    output_dir = snapshot_dir / "outputs"
    raw_dir.mkdir(parents=True, exist_ok=False)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw = result["raw"]
    for name in RAW_TABLES:
        raw[name].to_parquet(raw_dir / f"{name}.parquet", index=False)

    result["factors"].to_parquet(output_dir / "factor_daily.parquet", index=False)
    result["scores"].to_parquet(output_dir / "bias_daily.parquet", index=False)
    result["labels"].to_parquet(output_dir / "market_result_daily.parquet", index=False)
    (output_dir / "metrics.json").write_text(json.dumps(result["metrics"], ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "report.json").write_text(json.dumps(result["report"], ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    manifest = {
        "created_at": created_at,
        "source": source,
        "start_date": start_date,
        "end_date": end_date,
        "raw_tables": RAW_TABLES,
        "latest": result["report"].get("latest", {}),
    }
    (snapshot_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return snapshot_dir


def list_snapshots(snapshot_root: Path | str) -> list[SnapshotInfo]:
    root = Path(snapshot_root)
    if not root.exists():
        return []

    snapshots: list[SnapshotInfo] = []
    for manifest_path in root.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        latest = manifest.get("latest", {})
        label = (
            f"{manifest.get('created_at', manifest_path.parent.name)} | "
            f"{manifest.get('source', 'unknown')} | "
            f"{manifest.get('start_date', '?')} to {manifest.get('end_date', '?')} | "
            f"latest {latest.get('date', 'N/A')}"
        )
        snapshots.append(
            SnapshotInfo(
                path=manifest_path.parent,
                label=label,
                source=str(manifest.get("source", "unknown")),
                start_date=str(manifest.get("start_date", "")),
                end_date=str(manifest.get("end_date", "")),
                created_at=str(manifest.get("created_at", "")),
            )
        )
    return sorted(snapshots, key=lambda item: item.created_at, reverse=True)


def load_snapshot_raw(snapshot_dir: Path | str) -> dict[str, pd.DataFrame]:
    raw_dir = Path(snapshot_dir) / "raw"
    raw: dict[str, pd.DataFrame] = {}
    for name in RAW_TABLES:
        path = raw_dir / f"{name}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Snapshot is missing raw table {name}: {path}")
        raw[name] = pd.read_parquet(path)
    return raw


def run_pipeline_from_snapshot(
    snapshot_dir: Path | str,
    config_dir: Path | str,
) -> dict[str, Any]:
    raw = load_snapshot_raw(snapshot_dir)
    return run_pipeline_from_raw(raw, config_dir=config_dir, data_mode="snapshot")


def _with_margin_balance(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output["date"] = pd.to_datetime(output["date"]).dt.normalize()
    daily_amount = output.groupby("date")["amount"].transform("mean")
    rank = output.groupby("symbol").cumcount()
    output["margin_balance"] = daily_amount * (1.2 + rank * 0.002)
    return output


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}
