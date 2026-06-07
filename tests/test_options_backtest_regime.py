import pandas as pd
import pytest

from daily_bias_engine.options.analytics.regime_classifier import classify_option_regime
from daily_bias_engine.options.backtest.factor_backtest import FactorBacktester
from daily_bias_engine.options.data.market_data_store import OptionMarketDataStore
from daily_bias_engine.options.reports.daily_option_state import generate_daily_option_state
from tests.fixtures import option_chain_fixture


def test_factor_backtester_shifts_factor_to_next_trading_day() -> None:
    factors = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01"]),
            "data_date": pd.to_datetime(["2024-01-01"]),
            "gex_z": [1.0],
        }
    )
    returns = pd.DataFrame({"date": pd.to_datetime(["2024-01-02"]), "forward_return": [0.01]})

    result = FactorBacktester("gex_z").run(factors, returns)

    assert result["observations"] == 1
    aligned = result["aligned"].iloc[0]
    assert aligned["factor_data_date"] == pd.Timestamp("2024-01-01")
    assert aligned["join_date"] == pd.Timestamp("2024-01-02")


def test_factor_backtester_rejects_same_day_signal_date() -> None:
    factors = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2024-01-01"]),
            "data_date": pd.to_datetime(["2024-01-01"]),
            "gex_z": [1.0],
        }
    )
    returns = pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "forward_return": [0.01]})

    with pytest.raises(ValueError, match="Lookahead detected"):
        FactorBacktester("gex_z").run(factors, returns)


def test_regime_classifier_positive_and_negative_gamma_cases() -> None:
    positive = classify_option_regime(
        {
            "gex_z": 1.4,
            "iv_30d_change": -0.001,
            "spot_to_max_gamma_pct": 0.005,
            "put_skew_25d_change": 0.0,
        }
    )
    negative = classify_option_regime(
        {
            "gex_z": -1.3,
            "iv_30d_change": 0.01,
            "spot_to_zero_gamma_pct": 0.005,
            "put_skew_25d_change": 0.002,
        }
    )

    assert positive.regime == "PIN_GRIND"
    assert negative.regime == "NEGATIVE_GAMMA_FRAGILE"
    assert negative.allow_short_vol is False


def test_daily_option_state_report_reads_local_option_store(tmp_path) -> None:
    store = OptionMarketDataStore(tmp_path)
    store.write_normalized_chain(option_chain_fixture())

    factors, payload, markdown, plots = generate_daily_option_state("2026-06-07", "CSI300", store=store, include_plots=True)

    assert not factors.empty
    assert payload["product_group"] == "CSI300"
    assert payload["date"] == "2026-06-07"
    assert "option_direction_score" in payload
    assert markdown is not None
    assert plots is not None
    assert "gex_by_strike" in plots
