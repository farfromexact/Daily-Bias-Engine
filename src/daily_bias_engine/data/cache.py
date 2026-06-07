"""Immutable raw data snapshot cache."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


def _stable_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, default=str, ensure_ascii=True, sort_keys=True)


def _safe_part(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.=-]+", "_", value.strip())
    return value.strip("_") or "snapshot"


@dataclass(frozen=True)
class RawDataCache:
    """Append-only Parquet cache for raw source snapshots."""

    root: Path | str = Path("data/raw/wind")

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))

    def request_hash(self, request: Mapping[str, Any]) -> str:
        payload = _stable_json(request)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def write_snapshot(
        self,
        dataset: str,
        request: Mapping[str, Any],
        frame: pd.DataFrame,
        asof_time: str | pd.Timestamp | None = None,
    ) -> Path:
        """Write a new snapshot and fail rather than overwrite an existing file."""

        if frame.empty:
            raise ValueError("Cannot cache an empty raw snapshot.")

        timestamp = pd.Timestamp(asof_time or pd.Timestamp.now(tz="UTC"))
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("UTC").tz_localize(None)

        dataset_dir = self.root / _safe_part(dataset)
        dataset_dir.mkdir(parents=True, exist_ok=True)

        stamp = timestamp.strftime("%Y%m%dT%H%M%S%fZ")
        request_hash = self.request_hash(request)
        path = dataset_dir / f"{stamp}_{request_hash}_{uuid.uuid4().hex[:8]}.parquet"
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite raw snapshot: {path}")

        frame.to_parquet(path, index=False)
        return path

    def list_snapshots(
        self,
        dataset: str,
        request: Mapping[str, Any] | None = None,
    ) -> list[Path]:
        dataset_dir = self.root / _safe_part(dataset)
        if not dataset_dir.exists():
            return []

        pattern = "*.parquet"
        if request is not None:
            pattern = f"*_{self.request_hash(request)}_*.parquet"
        return sorted(dataset_dir.glob(pattern))

    def read_snapshot(self, path: Path | str) -> pd.DataFrame:
        return pd.read_parquet(path)
