# daily-bias-engine

`daily-bias-engine` is a Python research package for producing a daily
Risk-On / Neutral / Risk-Off market bias signal from cross-asset factors.

The v1 implementation is intentionally self-contained. It does not call Wind
yet. Instead, it defines Wind-compatible interfaces, immutable raw snapshot
caching, deterministic mock data, representative factor calculators, a
rule-based scoring engine, market result labels, backtest metrics, and a
Streamlit dashboard.

The current milestone hardens the project as a pre-open market environment
filter:

- Scores use a `-100` to `+100` scale.
- Bias thresholds are `+30` and `-30`.
- Daily close-based factors carry both `data_date` and signal `date`.
- A signal for date `T` cannot use `T` close data.
- Explanations include top positive and negative drivers plus hard risk flags.

WindPy integration is available through `WindPyDataClient`. The Wind terminal
must be installed, running, and logged in. Streamlit supports both Wind live mode
and mock demo mode; when Wind login fails, the dashboard falls back to mock data
with a warning.

## Install

```bash
python -m pip install -e ".[test]"
```

## Run Tests

```bash
pytest
```

## Run Streamlit Dashboard

```bash
python -m streamlit run apps/streamlit_app.py
```

The dashboard can run the full pipeline with either `WindPyDataClient` or
`MockWindDataClient`:

1. Generate deterministic mock OHLCV, futures open interest, and rates data.
2. Calculate representative v1 factors.
3. Score daily market bias using YAML weights and thresholds.
4. Label realized market outcomes.
5. Report evaluation metrics.

For example, if the mock data ends on `2024-04-30`, the latest pre-open signal
is dated `2024-05-01` and uses `2024-04-30` as `data_date`.

## Project Layout

```text
src/daily_bias_engine/
  data/       WindDataClient interface, mock client, raw cache
  features/   representative factor calculators
  engine/     rule-based Daily Bias Engine
  labeling/   market result labels
  backtest/   evaluation metrics
  report/     report helpers
apps/         Streamlit dashboard
configs/      YAML weights, thresholds, data config
tests/        pytest coverage
```

## Current Scope

- Implemented: interfaces, mock data, Parquet cache, representative v1 factors,
  scoring, labels, metrics, docs, tests, and Streamlit demo.
- Not implemented yet: real Wind authentication, WindPy calls, production factor
  formulas, scheduler, database storage, or execution integration.
