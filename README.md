# daily-bias-engine

`daily-bias-engine` is a Python research package for producing a daily
Risk-On / Neutral / Risk-Off market bias signal from localized real-market
iFinD data snapshots.

The runtime design is snapshot-first. Vendor API fetching happens as an
offline/localization step, then the model pipeline and Streamlit dashboard read
local Parquet snapshots. The current supported data path is iFinD.

For a complete Chinese user guide, see [USER_MANUAL.md](USER_MANUAL.md).

The current milestone hardens the project as a pre-open market environment
filter:

- Scores use a `-100` to `+100` scale.
- Bias thresholds are `+30` and `-30`.
- Daily close-based factors carry both `data_date` and signal `date`.
- A signal for date `T` cannot use `T` close data.
- Explanations include top positive and negative drivers plus hard risk flags.

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

The dashboard automatically loads the latest local market snapshot under
`data/snapshots/`. If no snapshot exists, fetch an iFinD snapshot first.

## Fetch iFinD Snapshot

Set `IFIND_USERNAME` and `IFIND_PASSWORD` in your local shell, then run:

```bash
python scripts/fetch_ifind_snapshot.py
```

By default this is incremental. If a local iFinD snapshot already exists, the
script fetches only dates after the latest raw market date, merges them with
the existing three-year history, and writes a new full snapshot under
`data/snapshots/`. If no local iFinD snapshot exists, it initializes the
trailing three calendar years.

Force a full rebuild when needed:

```bash
python scripts/fetch_ifind_snapshot.py --full-refresh --years 3
```

The current main-market universe is:

- Domestic index/futures: `000300.SH`, `IF.CFE`.
- Rates: `DR007.IB`, `CGB10Y`, `CGB30Y`.
- Yield curve slope: iFinD EDB `L001618299` 30Y minus `L001619604` 10Y.
- ETF flow proxy: `510300.SH`, `510500.SH`.
- Overseas: `SPX.GI` 80%, `N225.GI` 10%, `KS11.GI` 10%.
- A-share breadth/turnover sample: `000016.SH`, `000300.SH`, `000688.SH`, `399006.SZ`.

## Fetch iFinD Option Snapshot

```bash
python scripts/fetch_ifind_options_snapshot.py --date 2026-06-12
python -m daily_bias_engine.options.reports.daily_option_state --date 2026-06-12 --product CSI300 --data-root data/options_ifind
```

The current Streamlit options tab reads local iFinD option chains under
`data/options_ifind/`.

## Automated Daily Updates

The repository includes `.github/workflows/ifind_daily_update.yml`. It runs on
GitHub Actions at 20:30 China time on weekdays and can also be triggered
manually. Configure repository secrets named `IFIND_USERNAME` and
`IFIND_PASSWORD`.

The workflow runs:

```bash
python scripts/update_ifind_data.py
```

It updates the main market snapshot incrementally, updates option chains by
product/date, keeps the latest two iFinD market snapshots, and commits changed
data files back to the repository. Streamlit Cloud then reads the latest
committed parquet snapshot.

## Project Layout

```text
src/daily_bias_engine/
  data/       market-data client interfaces, iFinD client, raw cache
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

- Implemented: iFinD data fetching, Parquet cache, representative v1 factors,
  scoring, labels, metrics, docs, tests, Streamlit dashboard, and option state
  layer.
- Not implemented yet: production factor formulas, scheduler, database storage,
  or execution integration.
