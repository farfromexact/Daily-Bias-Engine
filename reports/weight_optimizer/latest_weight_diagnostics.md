# Weight Diagnostics

## Executive Summary

- Adoption status: `not adopted until manually approved`.
- OOS direction hit rate: 0.5147.
- OOS big loss capture rate: 0.0811.
- Strong signal count: `102`.

## What changed from current weights

| factor | current | return optimized | risk optimized | constrained blended |
| --- | ---: | ---: | ---: | ---: |
| `ashare_breadth_proxy` | 0.0900 | 0.0000 | 0.2103 | 0.0316 |
| `ashare_turnover_momentum` | 0.0600 | 0.1381 | 0.1397 | 0.0742 |
| `equity_index_futures_basis` | 0.1500 | 0.2419 | 0.1013 | 0.2500 |
| `etf_flow_proxy` | 0.1000 | 0.0884 | 0.1363 | 0.0862 |
| `futures_open_interest_momentum` | 0.1000 | 0.1081 | 0.0622 | 0.1000 |
| `margin_balance_momentum` | 0.1000 | 0.0616 | 0.0137 | 0.0623 |
| `overseas_market_momentum` | 0.1200 | 0.2156 | 0.1675 | 0.2117 |
| `overseas_volatility_pressure` | 0.0800 | 0.1344 | 0.0751 | 0.1031 |
| `rates_change_5d` | 0.1000 | 0.0119 | 0.0491 | 0.0434 |
| `yield_curve_slope` | 0.1000 | 0.0000 | 0.0449 | 0.0375 |

## Constraint checks

| weight set | pass | violations |
| --- | --- | --- |
| `current_weights` | `False` | rates_change_5d exceeds cap 5.00%; ETF flow + margin proxy exceeds cap 15.00% |
| `optimized_return_weights` | `True` | none |
| `optimized_risk_weights` | `True` | none |
| `raw_blended_weights` | `False` | rates_change_5d exceeds cap 5.00%; ETF flow + margin proxy exceeds cap 15.00% |
| `constrained_blended_weights` | `True` | none |

## Return score diagnostics

- Test IC: 0.0694.
- Direction hit rate CI: `{'successes': 298, 'total': 579, 'rate': 0.5146804835924007, 'lower': 0.47400813969474176, 'upper': 0.5551593047704441}`.
- Long-side average return: 0.0028.
- Short/risk-off average return: -0.0024.

## Risk score diagnostics

- TP/FP/TN/FN: `3/24/518/34`.
- Precision: 0.1111.
- False positive rate: 0.0443.

## Walk-forward fold summary

| fold | train_start | train_end | test_start | test_end | sample_count | direction_hit_rate | big_loss_capture_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2023-11-24 | 2024-06-12 | 2024-06-13 | 2024-07-11 | 21 | 0.5238 | N/A |
| 1 | 2023-11-24 | 2024-07-11 | 2024-07-12 | 2024-08-09 | 21 | 0.4762 | 0.0000 |
| 2 | 2023-11-24 | 2024-08-09 | 2024-08-12 | 2024-09-09 | 21 | 0.4286 | 0.0000 |
| 3 | 2023-11-24 | 2024-09-09 | 2024-09-10 | 2024-10-21 | 21 | 0.6667 | 0.0000 |
| 4 | 2023-11-24 | 2024-10-21 | 2024-10-22 | 2024-11-19 | 21 | 0.4762 | 0.5000 |
| 5 | 2023-11-24 | 2024-11-19 | 2024-11-20 | 2024-12-18 | 21 | 0.4286 | 0.0000 |
| 6 | 2023-11-24 | 2024-12-18 | 2024-12-19 | 2025-01-20 | 21 | 0.6190 | 0.0000 |
| 7 | 2023-12-25 | 2025-01-20 | 2025-01-21 | 2025-02-27 | 21 | 0.5238 | N/A |
| 8 | 2024-01-25 | 2025-02-27 | 2025-02-28 | 2025-03-28 | 21 | 0.5238 | 0.0000 |
| 9 | 2024-03-05 | 2025-03-28 | 2025-03-31 | 2025-04-30 | 21 | 0.3333 | N/A |
| 10 | 2024-04-03 | 2025-04-30 | 2025-05-07 | 2025-06-06 | 21 | 0.5238 | N/A |
| 11 | 2024-05-13 | 2025-06-06 | 2025-06-09 | 2025-07-07 | 21 | 0.4286 | N/A |

## Factor stability ranking

| factor_name | return_ic_mean | return_predictive_score | risk_predictive_score | weight_volatility | final_stability_rank |
| --- | --- | --- | --- | --- | --- |
| overseas_market_momentum | 0.0690 | 0.4490 | 0.3679 | 0.1077 | 1 |
| overseas_volatility_pressure | 0.0379 | 0.3266 | 0.4904 | 0.0714 | 2 |
| equity_index_futures_basis | 0.0492 | 0.3109 | 0.3797 | 0.0769 | 3 |
| futures_open_interest_momentum | 0.0487 | 0.4434 | 0.1157 | 0.0804 | 4 |
| ashare_turnover_momentum | 0.0392 | 0.3215 | 0.3260 | 0.0855 | 5 |
| etf_flow_proxy | 0.0394 | 0.3620 | 0.1679 | 0.0530 | 6 |
| margin_balance_momentum | 0.0393 | 0.3614 | 0.1664 | 0.0408 | 7 |
| rates_change_5d | 0.0160 | 0.0871 | 0.0000 | 0.0237 | 8 |
| ashare_breadth_proxy | -0.0307 | 0.0000 | 0.1122 | 0.0653 | 9 |
| yield_curve_slope | -0.0780 | 0.0000 | 0.0000 | 0.0838 | 10 |

## Regime diagnostics

### trend_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| downtrend | 266 | equity_index_futures_basis, rates_change_5d, yield_curve_slope, overseas_volatility_pressure, ashare_breadth_proxy | etf_flow_proxy, margin_balance_momentum, overseas_market_momentum, ashare_turnover_momentum |
| sideways | 103 | futures_open_interest_momentum, rates_change_5d, yield_curve_slope, etf_flow_proxy, margin_balance_momentum, ashare_breadth_proxy, ashare_turnover_momentum | equity_index_futures_basis |
| uptrend | 336 | futures_open_interest_momentum, yield_curve_slope, etf_flow_proxy, margin_balance_momentum, overseas_volatility_pressure, ashare_breadth_proxy, ashare_turnover_momentum | equity_index_futures_basis |

### volatility_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| high realized volatility | 271 | rates_change_5d, yield_curve_slope, ashare_breadth_proxy | overseas_market_momentum |
| low realized volatility | 181 | futures_open_interest_momentum, rates_change_5d, etf_flow_proxy, margin_balance_momentum, overseas_volatility_pressure, ashare_breadth_proxy, ashare_turnover_momentum | equity_index_futures_basis, yield_curve_slope |
| normal realized volatility | 253 | yield_curve_slope, ashare_breadth_proxy, ashare_turnover_momentum | equity_index_futures_basis, futures_open_interest_momentum, rates_change_5d, etf_flow_proxy, margin_balance_momentum, overseas_volatility_pressure |

### stress_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| drawdown > threshold | 256 | equity_index_futures_basis, rates_change_5d, yield_curve_slope, overseas_volatility_pressure, ashare_breadth_proxy | etf_flow_proxy, margin_balance_momentum, overseas_market_momentum, ashare_turnover_momentum |
| no stress | 449 | futures_open_interest_momentum, rates_change_5d, yield_curve_slope, etf_flow_proxy, margin_balance_momentum, ashare_breadth_proxy, ashare_turnover_momentum | equity_index_futures_basis, overseas_volatility_pressure |

### overseas_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| neutral | 353 | rates_change_5d, yield_curve_slope, etf_flow_proxy, margin_balance_momentum, ashare_breadth_proxy, ashare_turnover_momentum | equity_index_futures_basis, overseas_market_momentum |
| overseas risk-off | 194 | equity_index_futures_basis, futures_open_interest_momentum, rates_change_5d, yield_curve_slope, ashare_breadth_proxy, ashare_turnover_momentum | etf_flow_proxy, margin_balance_momentum |
| overseas risk-on | 158 | equity_index_futures_basis, yield_curve_slope, overseas_volatility_pressure, ashare_breadth_proxy | rates_change_5d, etf_flow_proxy, margin_balance_momentum |


## Bucket analysis

### Return buckets

| bucket | sample_count | next_day_avg_return | direction_hit_rate | big_loss_rate |
| --- | --- | --- | --- | --- |
| score <= -0.70 | 2 | -0.0041 | 1.0000 | 0.0000 |
| -0.70 < score <= -0.35 | 39 | -0.0023 | 0.5897 | 0.1282 |
| -0.35 < score < 0.35 | 477 | 0.0001 | 0.5073 | 0.0587 |
| 0.35 <= score < 0.70 | 58 | 0.0025 | 0.5000 | 0.0690 |
| score >= 0.70 | 3 | 0.0085 | 0.6667 | 0.0000 |

### Risk buckets

| bucket | sample_count | big_loss_rate | avg_next_day_return | false_alarm_count | missed_big_loss_count |
| --- | --- | --- | --- | --- | --- |
| low risk | 303 | 0.0528 | 0.0010 | 0 | 16 |
| neutral risk | 249 | 0.0723 | -0.0005 | 0 | 18 |
| high risk | 27 | 0.1111 | -0.0017 | 24 | 0 |
| extreme risk | 0 | N/A | N/A | 0 | 0 |

## Leakage checks

| check | pass | note |
| --- | --- | --- |
| factor_data_date_before_signal_date | `True` |  |
| next_day_return_shift_minus_one_contract | `True` | market_return is the realized return on signal date; because factors require data_date < signal date, this is equivalent to a next-day target from the factor data date. |
| rolling_zscore_no_full_sample_refit_in_optimizer | `True` | optimizer consumes as-of directional_score only |
| walk_forward_train_before_test | `True` |  |
| full_history_optimized_weights_warning | `True` | optimized weights are full-history diagnostic only, not out-of-sample verified |

Warnings:
- optimized weights fit on all visible history are full-history diagnostic only, not out-of-sample verified

## Recommendation

1. Can this optimizer improve return prediction? No. Out-of-sample direction hit rate is not above 52%.
2. Can this optimizer improve risk filtering? Yes, risk filtering is useful, but crash prediction is limited.
3. Should any weight be adopted into production now? No. Nothing should be adopted into production automatically.

## Do / Do Not

### Do

- Use constrained_blended_weights only as a shadow candidate.
- Review risk_score separately from return_score.
- Require manual approval before editing configs/factor_weights.yaml.

### Do Not

- Do not deploy optimized_return_weights directly.
- Do not interpret high abs IC with negative mean IC as return predictive power.
- Do not treat small-sample strong signal hit rates as stable.
