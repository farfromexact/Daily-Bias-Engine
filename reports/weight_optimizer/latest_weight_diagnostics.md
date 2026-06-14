# Weight Diagnostics

## Executive Summary

- Adoption status: `not adopted until manually approved`.
- OOS direction hit rate: 0.5215.
- OOS big loss capture rate: 0.1050.
- Strong signal count: `368`.

## What changed from current weights

| factor | current | return optimized | risk optimized | constrained blended |
| --- | ---: | ---: | ---: | ---: |
| `ashare_breadth_proxy` | 0.0900 | 0.1398 | 0.1284 | 0.1205 |
| `ashare_turnover_momentum` | 0.0600 | 0.0945 | 0.0773 | 0.0541 |
| `equity_index_futures_basis` | 0.1500 | 0.2500 | 0.1558 | 0.2500 |
| `etf_flow_proxy` | 0.1000 | 0.1075 | 0.0646 | 0.0936 |
| `futures_open_interest_momentum` | 0.1000 | 0.0157 | 0.0288 | 0.0447 |
| `margin_balance_momentum` | 0.1000 | 0.0425 | 0.0588 | 0.0564 |
| `overseas_market_momentum` | 0.1200 | 0.2500 | 0.1494 | 0.2311 |
| `overseas_volatility_pressure` | 0.0800 | 0.1000 | 0.2006 | 0.0767 |
| `rates_change_5d` | 0.1000 | 0.0000 | 0.0374 | 0.0377 |
| `yield_curve_slope` | 0.1000 | 0.0000 | 0.0990 | 0.0353 |

## Constraint checks

| weight set | pass | violations |
| --- | --- | --- |
| `current_weights` | `False` | rates_change_5d exceeds cap 5.00%; ETF flow + margin proxy exceeds cap 15.00% |
| `optimized_return_weights` | `True` | none |
| `optimized_risk_weights` | `True` | none |
| `raw_blended_weights` | `False` | rates_change_5d exceeds cap 5.00%; ETF flow + margin proxy exceeds cap 15.00% |
| `constrained_blended_weights` | `True` | none |

## Return score diagnostics

- Test IC: 0.0876.
- Direction hit rate CI: `{'successes': 1380, 'total': 2646, 'rate': 0.5215419501133787, 'lower': 0.5024905995838059, 'upper': 0.5405308398863873}`.
- Long-side average return: 0.0023.
- Short/risk-off average return: -0.0037.

## Risk score diagnostics

- TP/FP/TN/FN: `21/139/2307/179`.
- Precision: 0.1313.
- False positive rate: 0.0568.

## Walk-forward fold summary

| fold | train_start | train_end | test_start | test_end | sample_count | direction_hit_rate | big_loss_capture_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2015-01-05 | 2015-07-09 | 2015-07-10 | 2015-08-07 | 21 | 0.5714 | 0.1667 |
| 1 | 2015-01-05 | 2015-08-07 | 2015-08-10 | 2015-09-09 | 21 | 0.6667 | 0.1667 |
| 2 | 2015-01-05 | 2015-09-09 | 2015-09-10 | 2015-10-15 | 21 | 0.3810 | 0.0000 |
| 3 | 2015-01-05 | 2015-10-15 | 2015-10-16 | 2015-11-13 | 21 | 0.6190 | 0.0000 |
| 4 | 2015-01-05 | 2015-11-13 | 2015-11-16 | 2015-12-14 | 21 | 0.4286 | 0.0000 |
| 5 | 2015-01-05 | 2015-12-14 | 2015-12-15 | 2016-01-14 | 21 | 0.4762 | 0.0000 |
| 6 | 2015-01-05 | 2016-01-14 | 2016-01-15 | 2016-02-19 | 21 | 0.4286 | 0.1667 |
| 7 | 2015-02-03 | 2016-02-19 | 2016-02-22 | 2016-03-21 | 21 | 0.5714 | 0.0000 |
| 8 | 2015-03-11 | 2016-03-21 | 2016-03-22 | 2016-04-20 | 21 | 0.4286 | 0.0000 |
| 9 | 2015-04-10 | 2016-04-20 | 2016-04-21 | 2016-05-20 | 21 | 0.4286 | 0.0000 |
| 10 | 2015-05-12 | 2016-05-20 | 2016-05-23 | 2016-06-22 | 21 | 0.5238 | 0.0000 |
| 11 | 2015-06-10 | 2016-06-22 | 2016-06-23 | 2016-07-21 | 21 | 0.5714 | N/A |

## Factor stability ranking

| factor_name | return_ic_mean | return_predictive_score | risk_predictive_score | weight_volatility | final_stability_rank |
| --- | --- | --- | --- | --- | --- |
| overseas_market_momentum | 0.1534 | 1.0243 | 0.7014 | 0.0820 | 1 |
| overseas_volatility_pressure | 0.0824 | 0.6096 | 0.6922 | 0.0747 | 2 |
| equity_index_futures_basis | 0.0426 | 0.3287 | 0.4738 | 0.0925 | 3 |
| etf_flow_proxy | 0.0264 | 0.1978 | 0.0000 | 0.0448 | 4 |
| margin_balance_momentum | 0.0264 | 0.1977 | 0.0000 | 0.0451 | 5 |
| ashare_breadth_proxy | 0.0020 | 0.0178 | 0.0897 | 0.1051 | 6 |
| ashare_turnover_momentum | 0.0020 | 0.0172 | 0.0372 | 0.0917 | 7 |
| futures_open_interest_momentum | -0.0132 | 0.0000 | 0.0000 | 0.0897 | 8 |
| rates_change_5d | -0.0318 | 0.0000 | 0.0000 | 0.0232 | 8 |
| yield_curve_slope | -0.0327 | 0.0000 | 0.0000 | 0.0925 | 8 |

## Regime diagnostics

### trend_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| downtrend | 986 | equity_index_futures_basis, rates_change_5d, yield_curve_slope, ashare_breadth_proxy | overseas_market_momentum |
| sideways | 334 | futures_open_interest_momentum, rates_change_5d, yield_curve_slope, ashare_breadth_proxy, ashare_turnover_momentum | overseas_market_momentum, overseas_volatility_pressure |
| uptrend | 1452 | equity_index_futures_basis, futures_open_interest_momentum, rates_change_5d, yield_curve_slope, etf_flow_proxy, margin_balance_momentum, ashare_breadth_proxy, ashare_turnover_momentum | overseas_market_momentum |

### volatility_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| high realized volatility | 568 | equity_index_futures_basis, rates_change_5d, yield_curve_slope, ashare_turnover_momentum | overseas_market_momentum, overseas_volatility_pressure |
| low realized volatility | 1134 | equity_index_futures_basis, futures_open_interest_momentum, rates_change_5d, yield_curve_slope, overseas_volatility_pressure, ashare_breadth_proxy | etf_flow_proxy, margin_balance_momentum, overseas_market_momentum |
| normal realized volatility | 1070 | futures_open_interest_momentum, rates_change_5d, yield_curve_slope, etf_flow_proxy, margin_balance_momentum, ashare_breadth_proxy, ashare_turnover_momentum | equity_index_futures_basis, overseas_market_momentum, overseas_volatility_pressure |

### stress_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| drawdown > threshold | 1262 | equity_index_futures_basis, futures_open_interest_momentum, rates_change_5d, yield_curve_slope, ashare_breadth_proxy | overseas_market_momentum, overseas_volatility_pressure |
| no stress | 1510 | futures_open_interest_momentum, rates_change_5d, yield_curve_slope, ashare_breadth_proxy, ashare_turnover_momentum | overseas_market_momentum |

### overseas_regime

| regime | samples | failed factors | effective factors |
| --- | ---: | --- | --- |
| neutral | 1400 | futures_open_interest_momentum, rates_change_5d, yield_curve_slope, ashare_breadth_proxy, ashare_turnover_momentum | overseas_market_momentum, overseas_volatility_pressure |
| overseas risk-off | 789 | futures_open_interest_momentum, rates_change_5d, yield_curve_slope, ashare_breadth_proxy, ashare_turnover_momentum | overseas_market_momentum, overseas_volatility_pressure |
| overseas risk-on | 583 | equity_index_futures_basis, futures_open_interest_momentum, rates_change_5d, overseas_volatility_pressure, ashare_turnover_momentum | overseas_market_momentum |


## Bucket analysis

### Return buckets

| bucket | sample_count | next_day_avg_return | direction_hit_rate | big_loss_rate |
| --- | --- | --- | --- | --- |
| score <= -0.70 | 4 | 0.0072 | 0.5000 | 0.0000 |
| -0.70 < score <= -0.35 | 185 | -0.0039 | 0.5892 | 0.1459 |
| -0.35 < score < 0.35 | 2278 | 0.0004 | 0.5176 | 0.0724 |
| 0.35 <= score < 0.70 | 176 | 0.0022 | 0.5000 | 0.0455 |
| score >= 0.70 | 3 | 0.0054 | 0.6667 | 0.0000 |

### Risk buckets

| bucket | sample_count | big_loss_rate | avg_next_day_return | false_alarm_count | missed_big_loss_count |
| --- | --- | --- | --- | --- | --- |
| low risk | 1311 | 0.0656 | 0.0008 | 0 | 86 |
| neutral risk | 1175 | 0.0791 | 0.0000 | 0 | 93 |
| high risk | 159 | 0.1321 | -0.0036 | 138 | 0 |
| extreme risk | 1 | 0.0000 | -0.0049 | 1 | 0 |

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

1. Can this optimizer improve return prediction? Possibly, but only as shadow diagnostics until manually approved.
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
