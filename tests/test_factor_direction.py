import pandas as pd
import pytest

from daily_bias_engine.features.base import directional_score


def test_directional_score_positive_polarity_supports_risk_on() -> None:
    score = directional_score(pd.Series([2.0]), polarity=1.0).iloc[0]

    assert score == pytest.approx(1.0)


def test_directional_score_negative_polarity_maps_pressure_to_risk_off() -> None:
    score = directional_score(pd.Series([2.0]), polarity=-1.0).iloc[0]

    assert score == pytest.approx(-1.0)
