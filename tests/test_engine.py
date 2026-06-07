import pandas as pd
import pytest

from daily_bias_engine.engine import DailyBiasEngine


def test_daily_bias_engine_scores_weighted_factors() -> None:
    factors = pd.DataFrame(
        [
                {
                    "date": "2024-01-02",
                    "data_date": "2024-01-01",
                    "factor_name": "risk_on_factor",
                    "raw_value": 1.0,
                    "zscore_value": 1.0,
                    "directional_score": 1.0,
                "asof_time": "16:30:00",
            },
                {
                    "date": "2024-01-02",
                    "data_date": "2024-01-01",
                    "factor_name": "risk_off_factor",
                    "raw_value": -1.0,
                    "zscore_value": -1.0,
                    "directional_score": -0.5,
                "asof_time": "16:30:00",
            },
        ]
    )
    engine = DailyBiasEngine(
        weights={"risk_on_factor": 0.8, "risk_off_factor": 0.2},
        groups={"risk_on_factor": "flow", "risk_off_factor": "rates"},
        risk_on_threshold=30,
        risk_off_threshold=-30,
    )

    output = engine.score(factors)
    row = output.iloc[0]

    assert row["bias_label"] == "Risk-On"
    assert row["raw_score_bias"] == "Risk-On"
    assert row["final_bias"] == "Risk-On"
    assert row["risk_override"] == ""
    assert row["total_score"] == pytest.approx(70.0)
    assert row["confidence"] == pytest.approx(70.0)
    assert row["trend_direction_bias"] == "up"
    assert "flow" in row["sub_scores"]
    assert row["explanation"]["bias_label"] == "Risk-On"
    assert len(row["explanation"]["factors"]) == 2
    assert len(row["explanation"]["positive_drivers"]) == 2
    assert len(row["explanation"]["negative_drivers"]) == 2


def test_daily_bias_engine_labels_neutral_inside_thresholds() -> None:
    factors = pd.DataFrame(
        [
                {
                    "date": "2024-01-02",
                    "data_date": "2024-01-01",
                    "factor_name": "flat_factor",
                    "raw_value": 0.0,
                    "zscore_value": 0.0,
                "directional_score": 0.1,
                "asof_time": "16:30:00",
            }
        ]
    )
    engine = DailyBiasEngine(weights={"flat_factor": 1.0}, groups={"flat_factor": "flat"})

    output = engine.score(factors)

    assert output.iloc[0]["bias_label"] == "Neutral"


def test_daily_bias_engine_hard_risk_off_downgrade() -> None:
    factors = pd.DataFrame(
        [
            {
                "date": "2024-01-02",
                "data_date": "2024-01-01",
                "factor_name": "overseas_market_momentum",
                "raw_value": -2.0,
                "zscore_value": -2.0,
                "directional_score": -0.8,
                "asof_time": "16:30:00",
            },
            {
                "date": "2024-01-02",
                "data_date": "2024-01-01",
                "factor_name": "offsetting_positive",
                "raw_value": 1.0,
                "zscore_value": 1.0,
                "directional_score": 0.4,
                "asof_time": "16:30:00",
            },
        ]
    )
    engine = DailyBiasEngine(
        weights={"overseas_market_momentum": 0.2, "offsetting_positive": 0.8},
        groups={"overseas_market_momentum": "overseas", "offsetting_positive": "flow"},
        hard_risk_off_factors={"overseas_market_momentum": -70},
    )

    row = engine.score(factors).iloc[0]

    assert row["total_score"] == pytest.approx(16.0)
    assert row["raw_score_bias"] == "Neutral"
    assert row["final_bias"] == "Risk-Off"
    assert row["bias_label"] == "Risk-Off"
    assert row["risk_override"] == "Hard Risk-Off"
    assert "overseas_market_momentum crossed hard Risk-Off threshold" in row["override_reason"]
    assert row["trend_direction_bias"] == "unclear"
    assert row["risk_flags_json"][0]["factor_name"] == "overseas_market_momentum"
