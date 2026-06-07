# Daily Bias Engine Specification

## Objective

Daily Bias Engine is a daily, pre-open, explainable market environment filter
for A-share index trading and risk control.

It is not a next-bar predictor. It answers:

- Should today's posture be offensive, defensive, or patient?
- Is today's market more likely to trend, chop, or release risk?
- Which signals explain the current environment?

## Core Principles

- Daily frequency only.
- Signals are generated before the market opens.
- Every signal is explainable and auditable.
- No lookahead: a pre-open signal for date `T` cannot use data from the `T`
  close or any later timestamp.
- `Neutral` is a valid and important output.
- v1 is rule-based; no machine learning, minute timing, or auto execution.

## Inputs

- `factor_daily`: normalized factor table with one row per signal date and
  factor.
- `configs/factor_weights.yaml`: factor weights and score groups.
- `configs/thresholds.yaml`: bias thresholds, trend probability parameters,
  hard-risk flags, labeling thresholds, and backtest thresholds.
- `configs/instruments.yaml`: instrument universe.
- `configs/calendar.yaml`: trading calendar and as-of policy.

## Factor Contract

Each factor row must include:

- `date`: signal date.
- `data_date`: actual source data date used by the factor.
- `factor_name`
- `raw_value`
- `zscore_value`
- `directional_score`: clipped to `[-1, 1]`.
- `asof_time`

For daily close-based data, the default signal date is the next business day
after `data_date`.

## Engine Output

The rule engine emits one row per signal date:

- `date`
- `total_score`: `-100` to `+100`
- `bias_label`: `Risk-On`, `Neutral`, or `Risk-Off`
- `confidence`: `0` to `100`
- `sub_scores`: grouped scores on the same `-100` to `+100` scale
- `trend_day_probability`: `0` to `100`
- `trend_direction_bias`: `up`, `down`, or `unclear`
- `risk_flags_json`
- `explanation`

Explanation includes:

- Top positive drivers.
- Top negative drivers.
- Risk flags.
- Factor contribution details.

## Data Interface

`WindDataClient` defines:

- `get_daily_ohlcv(symbols, start_date, end_date)`
- `get_futures_open_interest(symbols, start_date, end_date)`
- `get_interest_rates(series, start_date, end_date)`

`MockWindDataClient` implements the interface with deterministic synthetic data.
`WindPyDataClient` implements the same interface through WindPy. The Wind
terminal must be installed, running, and logged in before live data calls can
succeed.

## Raw Snapshot Cache

`RawDataCache` stores raw source data as append-only Parquet files under
`data/raw/wind`.

The cache:

- Uses dataset name and request hash in snapshot filenames.
- Adds an as-of timestamp and unique suffix.
- Refuses to overwrite any existing snapshot.
- Keeps historical raw data immutable.

## Factor Groups

Representative v1 calculators cover:

- Equity index futures structure.
- Rates and bond futures.
- ETF and margin flow.
- Overseas market.
- A-share market structure.

Group weights follow `SCORING_RULES.md`.

## Market Result Labels

`market_result_daily` is generated after market close and is used only for
evaluation.

Labels include:

- Composite market return.
- Index/futures open-to-close returns where available.
- Intraday range.
- Open-close direction.
- Trend day flags.
- Big-loss day flag.
- Choppy day flag.

Trend day classification uses body ratio, range percentile, and close location.
Big-loss classification uses composite drawdown and multi-index tail losses.

## Backtest Metrics

Metrics include:

- Bias accuracy.
- Trend day precision.
- Trend day recall.
- Big loss day filter rate.
- False risk-off rate.
