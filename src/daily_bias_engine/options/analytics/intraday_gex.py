"""Intraday evidence of dealer gamma sign from option executions and index returns."""

from __future__ import annotations

from datetime import time
from typing import Any

import numpy as np
import pandas as pd

from daily_bias_engine.options.analytics.exposure import compute_contract_exposures
from daily_bias_engine.options.analytics.greeks import calculate_greeks

SHANGHAI = "Asia/Shanghai"
PRODUCT_ROOTS = {"IH": "SSE50", "IF": "CSI300", "IM": "CSI1000"}
WINDOW_MINUTES = 60
BAR = pd.Timedelta(minutes=5)
TICK_FIELDS = ["last", "bid1", "ask1", "volume", "amt"]
FLOW_COLUMNS = ["buy_lots", "sell_lots", "unknown_lots", "signed_updates", "updates", "complete"]


def local_time(value: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    return stamp if stamp.tzinfo is None else stamp.tz_convert(SHANGHAI).tz_localize(None)


def iso_time(value: Any) -> str:
    return local_time(value).tz_localize(SHANGHAI).isoformat()


def freshness(data_time: pd.Timestamp, cutoff: pd.Timestamp) -> str:
    if data_time.date() != cutoff.date():
        return "prior_session"
    if cutoff.hour >= 15:
        return "session_close" if data_time.time() == time(15) else "delayed"
    if time(11, 30) <= cutoff.time() < time(13, 5):
        return "midday_close" if data_time.time() == time(11, 30) else "delayed"
    return "recent" if cutoff - data_time <= pd.Timedelta(minutes=10) else "delayed"


def completed_bar(as_of: pd.Timestamp, sessions: pd.DatetimeIndex) -> pd.Timestamp:
    """Select a completed continuous-session bucket, including through lunch."""
    stamp = local_time(as_of).floor("5min")
    eligible = sessions[sessions <= stamp.normalize()].sort_values()
    for day in reversed(eligible):
        for start_hour, start_minute, end_hour, end_minute in ((13, 0, 15, 0), (9, 30, 11, 30)):
            start = day + pd.Timedelta(hours=start_hour, minutes=start_minute)
            end = day + pd.Timedelta(hours=end_hour, minutes=end_minute)
            if stamp >= start + BAR:
                return min(stamp, end)
    raise ValueError("No completed SSE session in the calendar range.")


def window_bars(end: pd.Timestamp) -> pd.DatetimeIndex:
    start = end.normalize() + (pd.Timedelta(hours=13) if end.hour >= 13 else pd.Timedelta(hours=9, minutes=30))
    start = max(start, end - pd.Timedelta(minutes=WINDOW_MINUTES))
    return pd.date_range(start + BAR, end, freq=BAR)


def select_contracts(chain: pd.DataFrame, day: pd.Timestamp, limit: int) -> tuple[pd.DataFrame, dict]:
    """Rank surviving, priceable contracts by unsigned previous-close GEX."""
    if limit < 1 or chain.empty or not pd.to_datetime(chain.trade_date).dt.normalize().lt(day).all():
        raise ValueError("A positive contract limit and a strictly prior option chain are required.")
    live = chain[pd.to_datetime(chain.expiry_date).dt.normalize().ge(day)
                 & np.isfinite(chain.open_interest) & chain.open_interest.gt(0)].copy()
    inputs = ["underlying_price", "strike", "year_fraction", "implied_vol", "multiplier_or_contract_unit"]
    valid = np.isfinite(live[inputs + ["risk_free_rate", "dividend_yield"]]).all(axis=1) & live[inputs].gt(0).all(axis=1)
    if not valid.any():
        raise ValueError("No priceable prior-session option inventory.")
    ranked = compute_contract_exposures(live[valid], mode="unsigned")
    ranked = ranked.loc[ranked.gamma_exposure_1pct.gt(0)].sort_values(
        ["gamma_exposure_1pct", "option_code"], ascending=[False, True]
    )
    if ranked.empty:
        raise ValueError("Zero unsigned GEX in the prior-session universe.")
    ranked["prior_share"] = ranked.gamma_exposure_1pct / ranked.gamma_exposure_1pct.sum()
    count = min(limit, int(ranked.prior_share.cumsum().searchsorted(0.50)) + 1)
    selected = ranked.head(count).copy()
    return selected, {"eligible_contracts": len(live), "priceable_contracts": int(valid.sum()),
                      "sample_contracts": len(selected), "selected_prior_gex_share": float(selected.prior_share.sum())}


def classify_ticks(ticks: pd.DataFrame, ends: pd.DatetimeIndex, multiplier: float) -> pd.DataFrame:
    """Classify cumulative-volume increments at a strictly earlier, fresh touch."""
    if not np.isfinite(multiplier) or multiplier <= 0:
        raise ValueError("A positive, finite contract multiplier is required.")
    bars = pd.DataFrame(0.0, index=ends, columns=FLOW_COLUMNS)
    bars["complete"] = False
    if ticks.empty or ends.empty:
        return bars
    start = ends[0] - BAR
    ticks = ticks.loc[ticks.index.to_series().between(start - pd.Timedelta(seconds=5), ends[-1])].sort_index(kind="stable")
    if ticks.empty:
        return bars
    clock = ticks.index
    # At Wind's second resolution several updates can share a timestamp. A
    # quote from that second could already reflect the trade being classified.
    book = ticks.loc[~clock.duplicated(keep="last"), ["bid1", "ask1"]]
    prior = book.index.searchsorted(clock.floor("s"), side="left") - 1
    previous = book.iloc[np.maximum(prior, 0)]
    bid, ask = previous.bid1.to_numpy(), previous.ask1.to_numpy()
    quote_age = (clock - previous.index).total_seconds().to_numpy()
    last = ticks["last"].to_numpy()
    dv = ticks.volume.diff().to_numpy()
    da = ticks.amt.diff().to_numpy()
    traded = np.isfinite(dv) & (dv > 0)
    vwap = np.divide(da, dv * multiplier, out=np.full(len(ticks), np.nan), where=traded)
    # Both the last price and the increment VWAP must match the same touch.
    # Mixed-price batches and the last three minutes stay unsigned.
    fresh = (prior >= 0) & (quote_age > 0) & (quote_age <= 3) & np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
    continuous = (clock.time < time(14, 57)) & (clock > start)
    usable = traded & fresh & continuous & (da > 0)
    buy = usable & np.isclose(vwap, ask, rtol=1e-7, atol=1e-8) & np.isclose(last, ask, rtol=1e-7, atol=1e-8)
    sell = usable & np.isclose(vwap, bid, rtol=1e-7, atol=1e-8) & np.isclose(last, bid, rtol=1e-7, atol=1e-8)
    volume = np.where(traded, dv, 0.0)
    values = pd.DataFrame({"buy_lots": np.where(buy, volume, 0), "sell_lots": np.where(sell, volume, 0),
                           "unknown_lots": np.where(buy | sell, 0, volume), "signed_updates": (buy | sell).astype(int),
                           "updates": traded.astype(int)}, index=clock)
    totals = values.groupby(clock.ceil("5min")).sum()
    bars[totals.columns] = totals.reindex(ends).fillna(0)
    for end in ends:
        left = end - BAR
        near_left = clock.searchsorted(left - pd.Timedelta(seconds=5))
        right = clock.searchsorted(end, side="right")
        chunk = ticks.iloc[near_left:right]
        if chunk.empty:
            continue
        # Without a starting counter, the first volume increment is unknown.
        # If the boundary is unobserved or counters reset, omit the bucket
        # from priced evidence instead of treating the missing flow as zero.
        counters = chunk[["volume", "amt"]]
        bars.at[end, "complete"] = bool(chunk.index[0] <= left and chunk.index[-1] >= end - pd.Timedelta(seconds=30)
                                        and counters.notna().all().all() and not counters.diff().lt(0).any().any())
    return bars


def _lag_response(prices: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> tuple[float | None, int]:
    grid = pd.date_range(start, end, freq="min")
    values = prices.reindex(grid)
    returns = np.log(values.where(values.gt(0))).diff()
    pairs = pd.concat([returns.shift(1), returns], axis=1).dropna()
    if len(pairs) < max(30, (len(grid) - 2) * 0.8) or pairs.nunique().min() < 2:
        return None, len(pairs)
    rho = float(pairs.iloc[:, 0].corr(pairs.iloc[:, 1]))
    return (rho if np.isfinite(rho) else None), len(pairs)


def price_response(prices: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """Compare one-minute return autocorrelation to earlier same-clock windows."""
    rho, pairs = _lag_response(prices, start, end)
    days = prices.index.normalize().unique().sort_values()
    previous = []
    for day in days[days < end.normalize()][-20:]:
        shift = end.normalize() - day
        value, _ = _lag_response(prices, start - shift, end - shift)
        if value is not None:
            previous.append(value)
    low = high = None
    sign = "unclear"
    if len(previous) >= 8:
        low, high = map(float, np.quantile(previous, [0.25, 0.75]))
        if rho is not None and rho < min(-0.10, low):
            sign = "positive"
        elif rho is not None and rho > max(0.10, high):
            sign = "negative"
    return {"sign": sign, "lag1_return_corr": rho, "return_pairs": pairs,
            "baseline_days": len(previous), "baseline_q25": low, "baseline_q75": high}


def _unit_gex(contract: Any, spot: float, end: pd.Timestamp) -> float:
    expiry = pd.Timestamp(contract.expiry_date).normalize() + pd.Timedelta(hours=15)
    t = max(0.0, (expiry - end).total_seconds() / (365 * 86400))
    greeks = calculate_greeks(spot, contract.strike, t, contract.risk_free_rate, contract.implied_vol,
                              contract.option_type, contract.dividend_yield)
    return greeks.gamma * spot**2 * 0.01 * contract.multiplier_or_contract_unit


def estimate_intraday_gex(selected: pd.DataFrame, universe: dict, flows: dict[str, pd.DataFrame],
                          spots: dict[str, pd.Series], index_prices: pd.Series, end: pd.Timestamp) -> dict:
    ends = window_bars(end)
    start = ends[0] - BAR
    buckets = pd.DataFrame(0.0, index=ends, columns=["buy", "sell", "unsigned", "coverage", "signed_updates"])
    for contract in selected.itertuples():
        for stamp, row in flows[contract.option_code].reindex(ends).iterrows():
            spot = spots[contract.underlying_code].get(stamp, np.nan)
            if pd.isna(row.complete) or not row.complete or not np.isfinite(spot) or spot <= 0:
                continue
            unit = _unit_gex(contract, float(spot), stamp)
            buckets.loc[stamp] += [unit * row.buy_lots, unit * row.sell_lots, unit * row.unknown_lots,
                                   contract.prior_share, row.signed_updates]
    buy, sell, unknown = (float(buckets[c].sum()) for c in ["buy", "sell", "unsigned"])
    classified = buy + sell
    turnover = classified + unknown
    net = sell - buy
    coverage = float(buckets.coverage.mean())
    classified_share = classified / turnover if turnover else None
    imbalance = net / classified if classified else None
    updates = int(buckets.signed_updates.sum())
    response = price_response(index_prices, start, end)
    reasons = []
    if coverage < 0.40 or float(buckets.coverage.iloc[-1]) < 0.40:
        reasons.append("low_chain_coverage")
    if classified_share is None or classified_share < 0.50 or updates < 20:
        reasons.append("insufficient_signed_flow")
    flow_sign = "unclear"
    if imbalance is not None and abs(imbalance) >= 0.15:
        flow_sign = "positive" if imbalance > 0 else "negative"
    else:
        reasons.append("balanced_flow")
    if response["sign"] == "unclear":
        reasons.append("unclear_price_response")
    elif flow_sign != "unclear" and flow_sign != response["sign"]:
        reasons.append("conflicting_evidence")
    verdict = "indeterminate" if reasons else flow_sign
    return {
        "schema_version": 1, "product": str(selected.product_group.iloc[0]),
        "trade_date": str(end.date()), "window_start": iso_time(start), "as_of": iso_time(end),
        "prior_chain_date": str(pd.Timestamp(selected.trade_date.iloc[0]).date()), "sign": verdict,
        "method": "passive_flow_and_index_response_v1", "reasons": reasons, "dealer_net_gex_observed": False,
        "coverage": {**universe, "mean_observed_prior_gex_share": coverage,
                     "last_observed_prior_gex_share": float(buckets.coverage.iloc[-1]),
                     "contracts": selected.option_code.astype(str).tolist()},
        "flow": {"sign": flow_sign, "passive_change_rmb_per_1pct": net if classified else None,
                 "classified_share": classified_share, "imbalance": imbalance, "signed_updates": updates,
                 "unclassified_rmb_per_1pct": unknown, "classified_rmb_per_1pct": classified,
                 "sample_change_low": net - unknown if turnover else None,
                 "sample_change_high": net + unknown if turnover else None},
        "price_response": response,
        "bars": [{"as_of": iso_time(ts), "passive_change_rmb_per_1pct": float(r.sell - r.buy) if r.sell + r.buy > 0 else None,
                  "classified_rmb_per_1pct": float(r.sell + r.buy), "unclassified_rmb_per_1pct": float(r.unsigned),
                  "observed_prior_gex_share": float(r.coverage)} for ts, r in buckets.iterrows()],
    }
