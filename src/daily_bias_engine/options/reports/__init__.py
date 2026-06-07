"""Daily option state reporting."""

from __future__ import annotations

from typing import Any

__all__ = ["generate_daily_option_state"]


def __getattr__(name: str) -> Any:
    if name == "generate_daily_option_state":
        from daily_bias_engine.options.reports.daily_option_state import generate_daily_option_state

        return generate_daily_option_state
    raise AttributeError(name)
