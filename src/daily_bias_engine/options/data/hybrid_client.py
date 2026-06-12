"""Hybrid option clients that combine Wind contract discovery with iFinD quotes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import pandas as pd

from daily_bias_engine.options.data.ifind_client import IFindOptionClient
from daily_bias_engine.options.data.wind_client import OptionDataError, WindPyOptionClient


@dataclass
class WindPyIFindFallbackOptionClient(WindPyOptionClient):
    """Wind-backed contract client with iFinD fallback for quota-limited quotes."""

    fallback_client: IFindOptionClient | None = field(default=None, repr=False)

    def get_option_eod(self, codes: Sequence[str], trade_date: str | pd.Timestamp) -> pd.DataFrame:
        try:
            return super().get_option_eod(codes, trade_date)
        except OptionDataError as exc:
            if not _should_fallback(exc):
                raise
            return self._ifind().get_option_eod(codes, trade_date)

    def get_underlying_eod(self, codes: Sequence[str], trade_date: str | pd.Timestamp) -> pd.DataFrame:
        try:
            return super().get_underlying_eod(codes, trade_date)
        except OptionDataError as exc:
            if not _should_fallback(exc):
                raise
            return self._ifind().get_underlying_eod(codes, trade_date)

    def get_index_eod(self, codes: Sequence[str], trade_date: str | pd.Timestamp) -> pd.DataFrame:
        try:
            return super().get_index_eod(codes, trade_date)
        except OptionDataError as exc:
            if not _should_fallback(exc):
                raise
            return self._ifind().get_index_eod(codes, trade_date)

    def get_futures_eod(self, prefix: str, trade_date: str | pd.Timestamp) -> pd.DataFrame:
        try:
            return super().get_futures_eod(prefix, trade_date)
        except OptionDataError as exc:
            if not _should_fallback(exc):
                raise
            return self._ifind().get_futures_eod(prefix, trade_date)

    def get_rates(self, trade_date: str | pd.Timestamp) -> pd.DataFrame:
        try:
            return super().get_rates(trade_date)
        except OptionDataError as exc:
            if not _should_fallback(exc):
                raise
            return self._ifind().get_rates(trade_date)

    def _reference_close(self, code: str, trade_date: pd.Timestamp) -> float:
        try:
            return super()._reference_close(code, trade_date)
        except OptionDataError as exc:
            if not _should_fallback(exc):
                raise
            return self._ifind()._reference_close(code, trade_date)

    def close(self) -> None:
        if self.fallback_client is not None:
            self.fallback_client.close()

    def _ifind(self) -> IFindOptionClient:
        if self.fallback_client is None:
            self.fallback_client = IFindOptionClient(asof_time=self.asof_time)
        return self.fallback_client


def _should_fallback(exc: Exception) -> bool:
    text = str(exc).lower()
    return "quota exceeded" in text or "close missing" in text
