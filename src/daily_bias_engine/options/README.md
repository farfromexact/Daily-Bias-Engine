# Option State Layer

This package adds an A-share index option state layer for `SSE50`, `CSI300`,
and `CSI1000`. It is designed to run from localized Wind option snapshots.

## Data Requirements

The normalized chain expects one row per option contract and date:

- contract metadata: product group, venue, underlying, reference index, strike,
  expiry, multiplier or contract unit, settlement type, adjusted flag
- end-of-day option data: open, high, low, close, settle, volume, open interest,
  bid, ask, implied volatility if available
- underlying and reference index close
- risk-free rate and dividend or forward adjustment

Wind calls are isolated in `data/wind_client.py`. No Wind credentials are
hardcoded. Use `scripts/fetch_wind_options_snapshot.py` to fetch Wind data and
persist normalized parquet chains before running reports or model code.

## Dealer Sign Assumptions

Actual dealer positioning is not assumed to be observable. Exposure functions
support three modes:

- `unsigned`: absolute OI and exposure concentration without directional dealer
  sign.
- `dealer_short_options`: assumes end clients are net long options and dealers
  are short options.
- `calibrated`: uses a `calibrated_sign`, `dealer_sign`, or `position_sign`
  column if supplied; otherwise it falls back to the placeholder short-options
  assumption.

The calibrated mode is a placeholder for a future rolling model based on OI
changes, IV changes, and underlying response. It should not be presented as true
dealer positioning without participant-level data.

## Core Formulas

Contract exposures are RMB-equivalent:

```text
gamma_exposure_1pct = sign * OI * multiplier * gamma * S^2 * 0.01
vanna_exposure_1vol = sign * OI * multiplier * vanna * S * 0.01
charm_exposure_1day = sign * OI * multiplier * charm_delta_change_1day * S
vega_notional_1vol = sign * OI * multiplier * vega * 0.01
```

ETF options use ETF spot and contract unit. CFFEX index options use index level
and RMB-per-index-point multiplier.

## Factor Definitions

The factor layer extracts:

- ATM IV at 7, 14, 30, 60, and 90 calendar days
- 25-delta and 10-delta call/put IV, 25-delta risk reversal, put skew, call
  skew
- IV term structure and vol risk premium
- realized vol at 5, 10, 20, and 60 days when underlying history is supplied
- PCR by volume and OI, OI Herfindahl concentration, OI change buckets
- aggregate GEX, vanna, charm, vega, theta, OI notional
- put wall, call wall, max gamma strike, zero gamma, and spot distances

## Backtest Methodology

`FactorBacktester` shifts factor data to the next trading day before comparing
with target returns. A T-day close and T-day OI signal is only tradable from T+1.
`OverlayBacktester` combines an existing daily bias signal with option direction
and risk scores, then compares base, option-only, and combined variants.

## Daily Report

Example:

```bash
python scripts/fetch_wind_options_snapshot.py --date 2026-06-07 --product CSI300
python -m daily_bias_engine.options.reports.daily_option_state --date 2026-06-07 --product CSI300
```

The command emits a JSON payload with regime, scores, key levels, exposures, vol,
skew, and recommended overlay fields. It reads local parquet data under
`data/options/` and fails fast if the requested product/date has not been
localized yet.
