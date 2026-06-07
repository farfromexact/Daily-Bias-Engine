# Scoring Rules

Daily Bias Engine is a pre-open market environment filter, not a next-bar
predictor. Every signal must be explainable, auditable, and free of lookahead.

## Score Scale

The engine score is scaled from `-100` to `+100`.

- `score >= +30`: `Risk-On`
- `-30 < score < +30`: `Neutral`
- `score <= -30`: `Risk-Off`

Directional score convention:

- Positive factor contribution supports Risk-On.
- Negative factor contribution supports Risk-Off.
- Neutral or conflicting evidence should stay near zero.

## Group Weights

Initial group weights:

| Group | Weight |
| --- | ---: |
| Equity index futures structure | 25% |
| Rates and bond futures | 20% |
| ETF and margin flow | 20% |
| Overseas market | 20% |
| A-share market structure | 15% |

## As-Of Rule

For a pre-open signal on date `T`, daily close-based factors may only use data
with `data_date < T`. The default signal date is the next business day after the
source data date.

Market result labels are generated after the trading session and must never be
used to create the same date's pre-open signal.

## Hard Risk-Off Downgrade

The engine supports hard Risk-Off flags for extreme conditions. If configured
factor scores breach hard Risk-Off thresholds, the label is downgraded to
`Risk-Off` even when the weighted total score is not below `-30`.

Initial hard-risk candidates:

- Overseas market selloff or volatility shock.
- Equity index futures discount stress.
- A-share breadth collapse.

## Trend Day Probability

Trend day probability is not the same as Risk-On or Risk-Off. It estimates
market shape, not direction.

Initial rule:

```text
 base probability
+ absolute bias score
+ risk flags / signal alignment
- signal conflict
```

The engine also emits `trend_direction_bias`:

- `up` when score is strongly positive.
- `down` when score is strongly negative.
- `unclear` when the signal is neutral.
