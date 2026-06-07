"""Product metadata and contract configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class OptionInstrument:
    product_group: str
    venue: str
    option_product_code: str
    underlying_code: str
    reference_index_code: str
    hedge_future_prefix: str
    underlying_type: str
    default_multiplier: float
    settlement_type: str
    option_style: str
    default_expiry_rule: str


@dataclass(frozen=True)
class ProductMetadata:
    product_group: str
    display_name: str
    chinese_name: str
    instruments: tuple[OptionInstrument, ...]


def default_products_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "products.yml"


def load_product_metadata(path: Path | str | None = None) -> dict[str, ProductMetadata]:
    """Load option product metadata from YAML."""

    config_path = Path(path) if path is not None else default_products_path()
    with config_path.open("r", encoding="utf-8") as handle:
        payload: dict[str, Any] = yaml.safe_load(handle) or {}

    products: dict[str, ProductMetadata] = {}
    for product_group, product_payload in (payload.get("products") or {}).items():
        instruments = tuple(
            OptionInstrument(
                product_group=str(product_group),
                venue=str(item["venue"]),
                option_product_code=str(item["option_product_code"]),
                underlying_code=str(item["underlying_code"]),
                reference_index_code=str(item["reference_index_code"]),
                hedge_future_prefix=str(item["hedge_future_prefix"]),
                underlying_type=str(item["underlying_type"]),
                default_multiplier=float(item["default_multiplier"]),
                settlement_type=str(item["settlement_type"]),
                option_style=str(item.get("option_style", "European")),
                default_expiry_rule=str(item.get("default_expiry_rule", "")),
            )
            for item in product_payload.get("instruments", [])
        )
        if not instruments:
            raise ValueError(f"Product {product_group} has no option instruments configured.")
        products[str(product_group)] = ProductMetadata(
            product_group=str(product_group),
            display_name=str(product_payload.get("display_name", product_group)),
            chinese_name=str(product_payload.get("chinese_name", "")),
            instruments=instruments,
        )
    if not products:
        raise ValueError(f"No option products found in {config_path}.")
    return products


def get_product_metadata(product_group: str, path: Path | str | None = None) -> ProductMetadata:
    products = load_product_metadata(path)
    key = product_group.upper()
    if key not in products:
        raise KeyError(f"Unsupported option product group: {product_group}. Available: {sorted(products)}")
    return products[key]


def instruments_frame(product_group: str | None = None, path: Path | str | None = None):
    """Return configured instruments as a DataFrame without making pandas a hard import at module load."""

    import pandas as pd

    products = load_product_metadata(path)
    rows: list[dict[str, object]] = []
    for group, metadata in products.items():
        if product_group is not None and group != product_group.upper():
            continue
        for instrument in metadata.instruments:
            rows.append(instrument.__dict__.copy())
    return pd.DataFrame(rows)
