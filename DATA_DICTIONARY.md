# Data Dictionary

## `raw_market_data`

| Column | Type | Description |
| --- | --- | --- |
| `date` | date | Source observation date. |
| `asof_time` | string | Time the source data was known. |
| `source` | string | Data source, for example `mock` or `wind`. |
| `symbol` | string | Instrument code. |
| `open` | float | Daily open price. |
| `high` | float | Daily high price. |
| `low` | float | Daily low price. |
| `close` | float | Daily close price. |
| `volume` | integer | Daily traded volume. |
| `amount` | float | Daily traded amount. |
| `open_interest` | float | Futures open interest when available. |

## Daily OHLCV

| Column | Type | Description |
| --- | --- | --- |
| `date` | date | Trading date. |
| `symbol` | string | Wind-like security code. |
| `open` | float | Daily open price. |
| `high` | float | Daily high price. |
| `low` | float | Daily low price. |
| `close` | float | Daily close price. |
| `volume` | integer | Daily traded volume. |
| `amount` | float | Daily traded amount proxy. |
| `asof_time` | string | Data observation time. |

## Futures Open Interest

| Column | Type | Description |
| --- | --- | --- |
| `date` | date | Trading date. |
| `symbol` | string | Futures contract or continuous symbol. |
| `open_interest` | integer | Daily open interest. |
| `volume` | integer | Daily futures volume. |
| `asof_time` | string | Data observation time. |

## Interest Rates

| Column | Type | Description |
| --- | --- | --- |
| `date` | date | Observation date. |
| `series` | string | Rate series identifier. |
| `rate` | float | Interest rate value. |
| `asof_time` | string | Data observation time. |

## `factor_daily`

| Column | Type | Description |
| --- | --- | --- |
| `date` | date | Signal date. |
| `data_date` | date | Source data date used by the factor. |
| `factor_name` | string | Stable factor identifier. |
| `factor_group` | string | Factor group from config; added by engine/report layers. |
| `raw_value` | float | Unnormalized factor value. |
| `zscore_value` | float | Rolling z-score of raw value. |
| `directional_score` | float | Risk direction score clipped to `[-1, 1]`. |
| `asof_time` | string | Data observation time. |

## `bias_daily`

| Column | Type | Description |
| --- | --- | --- |
| `date` | date | Signal date. |
| `total_score` | float | Weighted aggregate score from `-100` to `+100`. |
| `bias_label` | string | `Risk-On`, `Neutral`, or `Risk-Off`. |
| `confidence` | float | Signal confidence proxy from `0` to `100`. |
| `trend_day_probability` | float | Rule-based trend-day probability from `0` to `100`. |
| `trend_direction_bias` | string | `up`, `down`, or `unclear`. |
| `sub_scores` | object | Group-level weighted scores. |
| `risk_flags_json` | object | Hard risk flags. |
| `explanation` | object | Driver and factor contribution details. |

## `market_result_daily`

| Column | Type | Description |
| --- | --- | --- |
| `date` | date | Market date. |
| `market_return` | float | Alias for composite market return. |
| `market_composite_return` | float | Average close-to-close return across available market symbols. |
| `IF_open_to_close_return` | float | IF open-to-close return when available. |
| `IH_open_to_close_return` | float | IH open-to-close return when available. |
| `IC_open_to_close_return` | float | IC open-to-close return when available. |
| `IM_open_to_close_return` | float | IM open-to-close return when available. |
| `CSI300_return` | float | CSI 300 close-to-close return when available. |
| `CSI500_return` | float | CSI 500 close-to-close return when available. |
| `CSI1000_return` | float | CSI 1000 close-to-close return when available. |
| `intraday_range` | float | Average `(high - low) / close`. |
| `open_close_direction` | string | Composite open-to-close direction. |
| `body_ratio` | float | Average absolute candle body divided by range. |
| `close_location` | float | Close location within daily range, from low `0` to high `1`. |
| `trend_day_flag` | bool | True when body, range, and close-location rules indicate trend. |
| `up_trend_day_flag` | bool | Trend day with positive open-to-close return. |
| `down_trend_day_flag` | bool | Trend day with negative open-to-close return. |
| `big_loss_day_flag` | bool | Composite or multi-index tail-loss day. |
| `choppy_day_flag` | bool | Small close return with wide intraday range and no trend. |

## `evaluation_summary`

| Column | Type | Description |
| --- | --- | --- |
| `period_start` | date | Evaluation start date. |
| `period_end` | date | Evaluation end date. |
| `bias_accuracy` | float | Directional environment hit rate. |
| `trend_day_precision` | float | Precision of high trend-probability days. |
| `trend_day_recall` | float | Recall of actual trend days. |
| `big_loss_filter_rate` | float | Big-loss days not labeled Risk-On. |
| `false_risk_off_rate` | float | Non-big-loss days labeled Risk-Off. |
| `notes` | string | Optional evaluation comments. |
