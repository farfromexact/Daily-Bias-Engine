import pandas as pd
import pytest

from daily_bias_engine.engine import DailyBiasEngine
from daily_bias_engine.features import validate_no_lookahead_contract, validate_premarket_asof


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


def test_no_lookahead_contract_rejects_domestic_same_day_data() -> None:
    factors = pd.DataFrame(
        [
            {
                "signal_date": "2024-01-03",
                "data_date": "2024-01-03",
                "available_time": "08:30:00",
                "factor_name": "ashare_breadth_proxy",
                "data_source": "Wind A-share market structure",
            }
        ]
    )

    with pytest.raises(ValueError, match="previous_trading_day"):
        validate_no_lookahead_contract(factors, decision_time="09:20:00")


def test_no_lookahead_contract_allows_overseas_preopen_same_day_data() -> None:
    factors = pd.DataFrame(
        [
            {
                "signal_date": "2024-01-03",
                "data_date": "2024-01-03",
                "available_time": "08:30:00",
                "factor_name": "overseas_market_momentum",
                "data_source": "Wind overseas market SPX.GI",
            }
        ]
    )

    validated = validate_no_lookahead_contract(factors, decision_time="09:20:00")

    assert len(validated) == 1


def test_no_lookahead_contract_rejects_late_available_time() -> None:
    factors = pd.DataFrame(
        [
            {
                "signal_date": "2024-01-03",
                "data_date": "2024-01-03",
                "available_time": "09:31:00",
                "factor_name": "overseas_market_momentum",
                "data_source": "Wind overseas market SPX.GI",
            }
        ]
    )

    with pytest.raises(ValueError, match="available_time"):
        validate_no_lookahead_contract(factors, decision_time="09:20:00")


def test_no_lookahead_contract_rejects_label_columns_in_factor_table() -> None:
    factors = pd.DataFrame(
        [
            {
                "signal_date": "2024-01-03",
                "data_date": "2024-01-02",
                "available_time": "16:30:00",
                "factor_name": "equity_index_futures_basis",
                "data_source": "Wind domestic futures",
                "market_return": 0.01,
            }
        ]
    )

    with pytest.raises(ValueError, match="realized label columns"):
        validate_no_lookahead_contract(factors, decision_time="09:20:00")


def test_no_lookahead_contract_rejects_market_result_before_signal_date() -> None:
    factors = pd.DataFrame(
        [
            {
                "signal_date": "2024-01-03",
                "data_date": "2024-01-02",
                "available_time": "16:30:00",
                "factor_name": "equity_index_futures_basis",
                "data_source": "Wind domestic futures",
            }
        ]
    )
    market_results = pd.DataFrame({"signal_date": ["2024-01-03"], "date": ["2024-01-02"]})

    with pytest.raises(ValueError, match="date >= signal_date"):
        validate_no_lookahead_contract(factors, market_results=market_results, decision_time="09:20:00")
