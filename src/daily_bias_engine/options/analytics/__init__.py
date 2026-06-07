"""Option analytics primitives."""

from daily_bias_engine.options.analytics.exposure import ExposureMode, aggregate_exposures, compute_contract_exposures, normalize_exposure_mode
from daily_bias_engine.options.analytics.factors import build_option_factors
from daily_bias_engine.options.analytics.greeks import OptionGreeks, calculate_greeks, calculate_greeks_frame
from daily_bias_engine.options.analytics.levels import calculate_key_levels, simulate_spot_grid_gamma
from daily_bias_engine.options.analytics.pricing import black_scholes_price, implied_volatility
from daily_bias_engine.options.analytics.regime_classifier import OptionRegimeResult, classify_option_regime

__all__ = [
    "ExposureMode",
    "OptionGreeks",
    "OptionRegimeResult",
    "aggregate_exposures",
    "black_scholes_price",
    "build_option_factors",
    "calculate_greeks",
    "calculate_greeks_frame",
    "calculate_key_levels",
    "classify_option_regime",
    "compute_contract_exposures",
    "implied_volatility",
    "normalize_exposure_mode",
    "simulate_spot_grid_gamma",
]
