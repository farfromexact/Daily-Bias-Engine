# daily-bias-engine

`daily-bias-engine` is a Python research package for producing a daily
Risk-On / Neutral / Risk-Off market bias signal from cross-asset factors.

The v1 implementation is intentionally snapshot-first at runtime. It defines
WindPy data fetchers, immutable raw snapshot caching, representative factor
calculators, a rule-based scoring engine, market result labels, backtest
metrics, and a Streamlit dashboard. WindPy fetching is an offline/localization
step; the dashboard and model pipeline read local Parquet snapshots.

The current milestone hardens the project as a pre-open market environment
filter:

- Scores use a `-100` to `+100` scale.
- Bias thresholds are `+30` and `-30`.
- Daily close-based factors carry both `data_date` and signal `date`.
- A signal for date `T` cannot use `T` close data.
- Explanations include top positive and negative drivers plus hard risk flags.

WindPy integration is available through `WindPyDataClient`. The Wind terminal
must be installed, running, and logged in. The recommended workflow is to fetch
Wind data into a local snapshot first and let Streamlit read the snapshot. This
keeps the long-running dashboard process away from Wind login/session issues.

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

## Fetch Wind Snapshot

Run this from a normal local PowerShell where the Wind terminal is logged in:

```bash
python scripts/fetch_wind_snapshot.py
```

By default this fetches the trailing three calendar years through the latest
weekday. You can still override the range:

```bash
python scripts/fetch_wind_snapshot.py --start 2024-01-01 --end 2024-04-30
```

The script writes Parquet snapshots under `data/snapshots/`. These local market
data files are ignored by Git.

The dashboard reads those local snapshots and does not need to call WindPy from
the long-running Streamlit process. This is more stable on Windows because Wind
login context and Streamlit server context can differ.

The dashboard automatically loads the latest local snapshot. If no snapshot is
available, it stops and asks you to run `python scripts/fetch_wind_snapshot.py`.
The main page uses a signal-date selector instead of sidebar run parameters.

For example, if the Wind snapshot ends on `2024-04-30`, the latest pre-open
signal is dated `2024-05-01` and uses `2024-04-30` as `data_date`.

## Fetch Wind Option Snapshot

Run this from a normal local PowerShell where the Wind terminal is logged in:

```bash
python scripts/fetch_wind_options_snapshot.py --date 2026-06-07 --product CSI300
```

The script writes normalized option chains under `data/options/`. Option reports
read those local Parquet chains:

```bash
python -m daily_bias_engine.options.reports.daily_option_state --date 2026-06-07 --product CSI300
```

## Project Layout

```text
src/daily_bias_engine/
  data/       WindDataClient interface, WindPy client, raw cache
  features/   representative factor calculators
  engine/     rule-based Daily Bias Engine
  labeling/   market result labels
  backtest/   evaluation metrics
  options/    localized A-share index option state layer
  report/     report helpers
apps/         Streamlit dashboard
configs/      YAML weights, thresholds, data config
tests/        pytest coverage
```

## Current Scope

- Implemented: WindPy interfaces, Parquet cache, representative v1 factors,
  scoring, labels, metrics, docs, tests, Streamlit dashboard, and option state
  layer.
- Not implemented yet: production factor formulas, scheduler, database storage,
  or execution integration.
