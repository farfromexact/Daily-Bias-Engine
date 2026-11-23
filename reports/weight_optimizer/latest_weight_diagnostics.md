# Weight Diagnostics

## Executive Summary

- Adoption status: `not adopted until manually approved`.
- OOS direction hit rate: 0.5075.
- OOS big loss capture rate: 0.0750.
- Strong signal count: `111`.

## What changed from current weights

| factor | current | return optimized | risk optimized | constrained blended |
| --- | ---: | ---: | ---: | ---: |
| `ashare_breadth_proxy` | 0.0900 | 0.0000 | 0.2280 | 0.0324 |
| `ashare_turnover_momentum` | 0.0600 | 0.1468 | 0.1220 | 0.0761 |
| `equity_index_futures_basis` | 0.1500 | 0.2500 | 0.1046 | 0.2500 |
| `etf_flow_proxy` | 0.1000 | 0.1500 | 0.1022 | 0.1186 |
| `futures_open_interest_momentum` | 0.1000 | 0.1000 | 0.0513 | 0.0900 |
| `margin_balance_momentum` | 0.1000 | 0.0000 | 0.0478 | 0.0314 |
| `overseas_market_momentum` | 0.1200 | 0.2005 | 0.1829 | 0.2072 |
| `overseas_volatility_pressure` | 0.0800 | 0.1495 | 0.0743 | 0.1097 |
| `rates_change_5d` | 0.1000 | 0.0032 | 0.0396 | 0.0442 |
| `yield_curve_slope` | 0.1000 | 0.0000 | 0.0473 | 0.0405 |

## Constraint checks

| weight set | pass | violations |
| --- | --- | --- |
| `current_weights` | `False` | rates_change_5d exceeds cap 5.00%; ETF flow + margin proxy exceeds cap 15.00% |
| `optimized_return_weights` | `True` | none |
| `optimized_risk_weights` | `True` | none |
| `raw_blended_weights` | `False` | rates_change_5d exceeds cap 5.00%; ETF flow + margin proxy exceeds cap 15.00% |
| `constrained_blended_weights` | `True` | none |

## Return score diagnostics

- Test IC: 0.0676.
- Direction hit rate CI: `{'successes': 304, 'total': 599, 'rate': 0.5075125208681135, 'lower': 0.4675551963657827, 'upper': 0.5473740984937624}`.
- Long-side average return: 0.0025.
- Short/risk-off average return: -0.0013.

## Risk score diagnostics

- TP/FP/TN/FN: `3/21/538/37`.
- Precision: 0.1250.
- False positive rate: 0.0376.

## Walk-forward fold summary

| fold | train_start | train_end | test_start | test_end | sample_count | direction_hit_rate | big_loss_capture_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2023-11-24 | 2024-06-04 | 2024-06-05 | 2024-07-04 | 21 | 0.3810 | N/A |
| 1 | 2023-11-24 | 2024-07-04 | 2024-07-05 | 2024-08-02 | 21 | 0.3810 | 0.0000 |
| 2 | 2023-11-24 | 2024-08-02 | 2024-08-05 | 2024-09-02 | 21 | 0.4762 | 0.0000 |
| 3 | 2023-11-24 | 2024-09-02 | 2024-09-03 | 2024-10-10 | 21 | 0.7143 | 0.0000 |
| 4 | 2023-11-24 | 2024-10-10 | 2024-10-11 | 2024-11-08 | 21 | 0.5238 | 0.0000 |
| 5 | 2023-11-24 | 2024-11-08 | 2024-11-11 | 2024-12-09 | 21 | 0.4762 | 0.3333 |
| 6 | 2023-11-24 | 2024-12-09 | 2024-12-10 | 2025-01-08 | 21 | 0.4762 | 0.0000 |
| 7 | 2023-12-25 | 2025-01-08 | 2025-01-09 | 2025-02-14 | 21 | 0.6667 | N/A |
| 8 | 2024-01-24 | 2025-02-14 | 2025-02-17 | 2025-03-17 | 21 | 0.4286 | 0.0000 |
| 9 | 2024-03-01 | 2025-03-17 | 2025-03-18 | 2025-04-16 | 21 | 0.3333 | 0.0000 |
| 10 | 2024-04-01 | 2025-04-16 | 2025-04-17 | 2025-05-20 | 21 | 0.4762 | N/A |
| 11 | 2024-05-07 | 2025-05-20 | 2025-05-21 | 2025-06-19 | 21 | 0.4762 | N/A |

## Factor stability ranking

| factor_name | return_ic_mean | return_predictive_score | risk_predictive_score | weight_volatility | final_stability_rank |
| --- | --- | --- | --- | --- | --- |
| overseas_volatility_pressure | 0.0605 | 0.6288 | 0.5520 | 0.0652 | 1 |
| overseas_market_momentum | 0.0880 | 0.5441 | 0.4945 | 0.1102 | 2 |
| equity_index_futures_basis | 0.0708 | 0.4664 | 0.4573 | 0.0709 | 3 |
| ashare_turnover_momentum | 0.0384 | 0.3249 | 0.2507 | 0.0886 | 4 |
| futures_open_interest_momentum | 0.0441 | 0.3620 | 0.0198 | 0.0870 | 5 |
| etf_flow_proxy | 0.0306 | 0.2234 | 0.0341 | 0.0607 | 6 |
| margin_balance_momentum | 0.0223 | 0.1698 | 0.0000 | 0.0497 | 7 |
| ashare_breadth_proxy | -0.0315 | 0.0000 | 0.1319 | 0.0652 | 8 |
| rates_change_5d | -0.0326 | 0.0000 | 0.0000 | 0.0244 | 9 |
| yield_curve_slope | -0.0516 | 0.0000 | 0.0000 | 0.1042 | 9 |

## Regime diagnostics

### trend_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| downtrend | 270 | equity_index_futures_basis, rates_change_5d, yield_curve_slope, margin_balance_momentum, overseas_volatility_pressure, ashare_breadth_proxy | etf_flow_proxy, ashare_turnover_momentum |
| sideways | 107 | futures_open_interest_momentum, rates_change_5d, etf_flow_proxy, ashare_breadth_proxy, ashare_turnover_momentum | none |
| uptrend | 348 | futures_open_interest_momentum, rates_change_5d, yield_curve_slope, etf_flow_proxy, margin_balance_momentum, overseas_volatility_pressure, ashare_breadth_proxy, ashare_turnover_momentum | equity_index_futures_basis |

### volatility_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| high realized volatility | 272 | rates_change_5d, yield_curve_slope, etf_flow_proxy, margin_balance_momentum, overseas_volatility_pressure, ashare_breadth_proxy, ashare_turnover_momentum | overseas_market_momentum |
| low realized volatility | 190 | futures_open_interest_momentum, rates_change_5d, etf_flow_proxy, ashare_breadth_proxy | equity_index_futures_basis, yield_curve_slope, overseas_volatility_pressure |
| normal realized volatility | 263 | yield_curve_slope, margin_balance_momentum, ashare_breadth_proxy, ashare_turnover_momentum | rates_change_5d, etf_flow_proxy, overseas_volatility_pressure |

### stress_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| drawdown > threshold | 306 | equity_index_futures_basis, rates_change_5d, yield_curve_slope, margin_balance_momentum, overseas_volatility_pressure, ashare_breadth_proxy | etf_flow_proxy |
| no stress | 419 | futures_open_interest_momentum, rates_change_5d, yield_curve_slope, etf_flow_proxy, margin_balance_momentum, ashare_breadth_proxy, ashare_turnover_momentum | equity_index_futures_basis |

### overseas_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| neutral | 358 | rates_change_5d, yield_curve_slope, etf_flow_proxy, margin_balance_momentum, ashare_breadth_proxy, ashare_turnover_momentum | equity_index_futures_basis, overseas_market_momentum |
| overseas risk-off | 202 | equity_index_futures_basis, futures_open_interest_momentum, rates_change_5d, yield_curve_slope, margin_balance_momentum, ashare_breadth_proxy, ashare_turnover_momentum | etf_flow_proxy, overseas_volatility_pressure |
| overseas risk-on | 165 | equity_index_futures_basis, overseas_market_momentum, overseas_volatility_pressure, ashare_breadth_proxy | futures_open_interest_momentum, etf_flow_proxy, margin_balance_momentum |


## Bucket analysis

### Return buckets

| bucket | sample_count | next_day_avg_return | direction_hit_rate | big_loss_rate |
| --- | --- | --- | --- | --- |
| score <= -0.70 | 0 | N/A | N/A | N/A |
| -0.70 < score <= -0.35 | 38 | -0.0013 | 0.6053 | 0.1316 |
| -0.35 < score < 0.35 | 488 | -0.0000 | 0.5000 | 0.0656 |
| 0.35 <= score < 0.70 | 72 | 0.0026 | 0.5139 | 0.0417 |
| score >= 0.70 | 1 | -0.0035 | 0.0000 | 0.0000 |

### Risk buckets

| bucket | sample_count | big_loss_rate | avg_next_day_return | false_alarm_count | missed_big_loss_count |
| --- | --- | --- | --- | --- | --- |
| low risk | 344 | 0.0581 | 0.0006 | 0 | 20 |
| neutral risk | 231 | 0.0736 | -0.0001 | 0 | 17 |
| high risk | 24 | 0.1250 | -0.0025 | 21 | 0 |
| extreme risk | 0 | N/A | N/A | 0 | 0 |

## Leakage checks

| check | pass | note |
| --- | --- | --- |
| factor_data_date_before_signal_date | `True` |  |
| next_day_return_shift_minus_one_contract | `True` | market_return is the realized close-to-close return on the domestic signal date. Financing and holiday observations can come from earlier sessions. |
| rolling_zscore_no_full_sample_refit_in_optimizer | `True` | optimizer consumes as-of directional_score only |
| walk_forward_train_before_test | `True` |  |
| full_history_optimized_weights_warning | `True` | optimized weights are full-history diagnostic only, not out-of-sample verified |

Warnings:
- optimized weights fit on all visible history are full-history diagnostic only, not out-of-sample verified

## Recommendation

1. Can this optimizer improve return prediction? No. Out-of-sample direction hit rate is not above 52%.
2. Can this optimizer improve risk filtering? Alert precision was 12.5% against a 6.7% event base rate. Recall was 7.5%.
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
