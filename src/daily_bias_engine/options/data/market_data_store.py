"""Parquet store for normalized option market data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class OptionMarketDataStore:
    root: Path | str = Path("data/options")

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))

    def write_normalized_chain(self, chain: pd.DataFrame) -> Path:
        if chain.empty:
            raise ValueError("Cannot write an empty option chain.")
        product_group = str(chain["product_group"].iloc[0])
        trade_date = pd.Timestamp(chain["trade_date"].iloc[0]).strftime("%Y-%m-%d")
        path = self.root / "normalized_chain" / f"product_group={product_group}" / f"trade_date={trade_date}" / "data.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        chain.to_parquet(path, index=False)
        return path

    def read_normalized_chain(self, product_group: str, trade_date: str | pd.Timestamp) -> pd.DataFrame:
        date_part = pd.Timestamp(trade_date).strftime("%Y-%m-%d")
        path = self.root / "normalized_chain" / f"product_group={product_group.upper()}" / f"trade_date={date_part}" / "data.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Normalized option chain not found: {path}")
        return pd.read_parquet(path)
