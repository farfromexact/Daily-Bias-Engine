import pandas as pd
import pytest

from daily_bias_engine.engine import DailyBiasEngine
from daily_bias_engine.features import validate_premarket_asof


def test_premarket_asof_rejects_same_day_source_data() -> None:
    factors = pd.DataFrame(
        [
            {
                "date": "2024-01-02",
                "data_date": "2024-01-02",
                "factor_name": "bad_factor",
                "raw_value": 1.0,
                "zscore_value": 1.0,
                "directional_score": 1.0,
                "asof_time": "16:30:00",
            }
        ]
    )

    with pytest.raises(ValueError, match="Lookahead detected"):
        validate_premarket_asof(factors)

    with pytest.raises(ValueError, match="Lookahead detected"):
        DailyBiasEngine(weights={"bad_factor": 1.0}, groups={"bad_factor": "bad"}).score(factors)
