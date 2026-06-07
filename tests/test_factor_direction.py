import pandas as pd
import pytest

from daily_bias_engine.features.base import directional_score
from daily_bias_engine.features.logic import factor_logic_rows


def test_directional_score_positive_polarity_supports_risk_on() -> None:
    score = directional_score(pd.Series([2.0]), polarity=1.0).iloc[0]

    assert score == pytest.approx(1.0)


def test_directional_score_negative_polarity_maps_pressure_to_risk_off() -> None:
    score = directional_score(pd.Series([2.0]), polarity=-1.0).iloc[0]

    assert score == pytest.approx(-1.0)


def test_factor_logic_rows_are_reader_facing() -> None:
    rows = factor_logic_rows()

    assert len(rows) == 10
    required = {"factor_name", "group", "raw_formula", "normalization", "direction", "caveat"}
    assert all(required.issubset(row) for row in rows)
