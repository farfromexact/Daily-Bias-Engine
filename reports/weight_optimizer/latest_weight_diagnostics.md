# Weight Diagnostics

## Executive Summary

- Adoption status: `not adopted until manually approved`.
- OOS direction hit rate: 0.5100.
- OOS big loss capture rate: 0.1034.
- Strong signal count: `91`.

## What changed from current weights

| factor | current | return optimized | risk optimized | constrained blended |
| --- | ---: | ---: | ---: | ---: |
| `ashare_breadth_proxy` | 0.0900 | 0.0000 | 0.1070 | 0.0305 |
| `ashare_turnover_momentum` | 0.0600 | 0.1432 | 0.1377 | 0.0893 |
| `equity_index_futures_basis` | 0.1500 | 0.0623 | 0.0925 | 0.1245 |
| `etf_flow_proxy` | 0.1000 | 0.0794 | 0.0842 | 0.0796 |
| `futures_open_interest_momentum` | 0.1000 | 0.2500 | 0.0585 | 0.2069 |
| `margin_balance_momentum` | 0.1000 | 0.0706 | 0.0658 | 0.0694 |
| `overseas_market_momentum` | 0.1200 | 0.2500 | 0.2098 | 0.2500 |
| `overseas_volatility_pressure` | 0.0800 | 0.1000 | 0.1402 | 0.0630 |
| `rates_change_5d` | 0.1000 | 0.0360 | 0.0371 | 0.0486 |
| `yield_curve_slope` | 0.1000 | 0.0085 | 0.0671 | 0.0383 |

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
- Direction hit rate CI: `{'successes': 305, 'total': 598, 'rate': 0.5100334448160535, 'lower': 0.47003031900012543, 'upper': 0.5499084821728077}`.
- Long-side average return: 0.0025.
- Short/risk-off average return: -0.0023.

## Risk score diagnostics

- TP/FP/TN/FN: `3/32/537/26`.
- Precision: 0.0857.
- False positive rate: 0.0562.

## Walk-forward fold summary

| fold | train_start | train_end | test_start | test_end | sample_count | direction_hit_rate | big_loss_capture_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2023-06-13 | 2023-12-15 | 2023-12-18 | 2024-01-17 | 21 | 0.5238 | 0.0000 |
| 1 | 2023-06-13 | 2024-01-17 | 2024-01-18 | 2024-02-23 | 21 | 0.4762 | 0.0000 |
| 2 | 2023-06-13 | 2024-02-23 | 2024-02-26 | 2024-03-25 | 21 | 0.2857 | N/A |
| 3 | 2023-06-13 | 2024-03-25 | 2024-03-26 | 2024-04-25 | 21 | 0.6190 | N/A |
| 4 | 2023-06-13 | 2024-04-25 | 2024-04-26 | 2024-05-29 | 21 | 0.4762 | N/A |
| 5 | 2023-06-13 | 2024-05-29 | 2024-05-30 | 2024-06-28 | 21 | 0.4286 | N/A |
| 6 | 2023-06-13 | 2024-06-28 | 2024-07-01 | 2024-07-29 | 21 | 0.3333 | 0.0000 |
| 7 | 2023-07-14 | 2024-07-29 | 2024-07-30 | 2024-08-27 | 21 | 0.5714 | N/A |
| 8 | 2023-08-14 | 2024-08-27 | 2024-08-28 | 2024-09-27 | 21 | 0.7143 | 0.0000 |
| 9 | 2023-09-12 | 2024-09-27 | 2024-09-30 | 2024-11-04 | 21 | 0.5238 | 0.0000 |
| 10 | 2023-10-19 | 2024-11-04 | 2024-11-05 | 2024-12-03 | 21 | 0.5714 | 0.3333 |
| 11 | 2023-11-17 | 2024-12-03 | 2024-12-04 | 2025-01-03 | 21 | 0.4286 | 0.0000 |

## Factor stability ranking

| factor_name | return_ic_mean | return_predictive_score | risk_predictive_score | weight_volatility | final_stability_rank |
| --- | --- | --- | --- | --- | --- |
| overseas_market_momentum | 0.1189 | 0.7327 | 0.5358 | 0.1038 | 1 |
| overseas_volatility_pressure | 0.0530 | 0.4723 | 0.7188 | 0.0866 | 2 |
| futures_open_interest_momentum | 0.0793 | 0.5775 | 0.0120 | 0.0769 | 3 |
| etf_flow_proxy | 0.0245 | 0.2486 | 0.1919 | 0.0526 | 4 |
| margin_balance_momentum | 0.0245 | 0.2478 | 0.1903 | 0.0574 | 5 |
| rates_change_5d | 0.0359 | 0.2440 | 0.0991 | 0.0224 | 6 |
| ashare_turnover_momentum | 0.0259 | 0.2389 | 0.0667 | 0.0747 | 7 |
| equity_index_futures_basis | 0.0027 | 0.0191 | 0.3589 | 0.0636 | 8 |
| ashare_breadth_proxy | -0.0224 | 0.0000 | 0.0000 | 0.0532 | 9 |
| yield_curve_slope | -0.0766 | 0.0000 | 0.0000 | 0.0932 | 9 |

## Regime diagnostics

### trend_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| downtrend | 263 | equity_index_futures_basis, rates_change_5d, yield_curve_slope, overseas_volatility_pressure, ashare_breadth_proxy | futures_open_interest_momentum, etf_flow_proxy, margin_balance_momentum, overseas_market_momentum, ashare_turnover_momentum |
| sideways | 101 | futures_open_interest_momentum, rates_change_5d, yield_curve_slope, etf_flow_proxy, margin_balance_momentum, overseas_volatility_pressure, ashare_breadth_proxy, ashare_turnover_momentum | overseas_market_momentum |
| uptrend | 360 | futures_open_interest_momentum, rates_change_5d, yield_curve_slope, etf_flow_proxy, margin_balance_momentum, overseas_volatility_pressure, ashare_breadth_proxy, ashare_turnover_momentum | overseas_market_momentum |

### volatility_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| high realized volatility | 259 | yield_curve_slope, ashare_breadth_proxy | futures_open_interest_momentum, overseas_market_momentum, ashare_turnover_momentum |
| low realized volatility | 264 | rates_change_5d, etf_flow_proxy, margin_balance_momentum, overseas_market_momentum, ashare_breadth_proxy | yield_curve_slope, ashare_turnover_momentum |
| normal realized volatility | 201 | rates_change_5d, yield_curve_slope, ashare_breadth_proxy, ashare_turnover_momentum | futures_open_interest_momentum, overseas_market_momentum, overseas_volatility_pressure |

### stress_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| drawdown > threshold | 294 | equity_index_futures_basis, rates_change_5d, yield_curve_slope | futures_open_interest_momentum, etf_flow_proxy, margin_balance_momentum, overseas_market_momentum, overseas_volatility_pressure, ashare_turnover_momentum |
| no stress | 430 | rates_change_5d, yield_curve_slope, etf_flow_proxy, margin_balance_momentum, ashare_breadth_proxy, ashare_turnover_momentum | futures_open_interest_momentum, overseas_market_momentum |

### overseas_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| neutral | 354 | rates_change_5d, yield_curve_slope, etf_flow_proxy, margin_balance_momentum, ashare_breadth_proxy, ashare_turnover_momentum | futures_open_interest_momentum, overseas_market_momentum, overseas_volatility_pressure |
| overseas risk-off | 206 | equity_index_futures_basis, rates_change_5d, yield_curve_slope, ashare_breadth_proxy | futures_open_interest_momentum, overseas_market_momentum, overseas_volatility_pressure, ashare_turnover_momentum |
| overseas risk-on | 164 | yield_curve_slope, overseas_market_momentum, overseas_volatility_pressure, ashare_breadth_proxy | futures_open_interest_momentum, etf_flow_proxy, margin_balance_momentum |


## Bucket analysis

### Return buckets

| bucket | sample_count | next_day_avg_return | direction_hit_rate | big_loss_rate |
| --- | --- | --- | --- | --- |
| score <= -0.70 | 0 | N/A | N/A | N/A |
| -0.70 < score <= -0.35 | 40 | -0.0023 | 0.6000 | 0.1000 |
| -0.35 < score < 0.35 | 507 | 0.0008 | 0.5069 | 0.0434 |
| 0.35 <= score < 0.70 | 50 | 0.0022 | 0.4600 | 0.0600 |
| score >= 0.70 | 1 | 0.0148 | 1.0000 | 0.0000 |

### Risk buckets

| bucket | sample_count | big_loss_rate | avg_next_day_return | false_alarm_count | missed_big_loss_count |
| --- | --- | --- | --- | --- | --- |
| low risk | 293 | 0.0375 | 0.0008 | 0 | 11 |
| neutral risk | 270 | 0.0556 | 0.0009 | 0 | 15 |
| high risk | 35 | 0.0857 | -0.0009 | 32 | 0 |
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
