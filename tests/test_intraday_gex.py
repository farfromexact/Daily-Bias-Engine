from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from daily_bias_engine.data.client import MarketDataError
from daily_bias_engine.options.analytics.greeks import calculate_greeks
from daily_bias_engine.options.analytics.intraday_gex import (
    BAR, FLOW_COLUMNS, TICK_FIELDS, classify_ticks, completed_bar, estimate_intraday_gex, price_response,
    select_contracts, window_bars,
)
from daily_bias_engine.options.data.intraday_wind import IntradayCache, _frame
from daily_bias_engine.options.data.market_data_store import OptionMarketDataStore
from daily_bias_engine.options.reports.intraday_gex import build_snapshot, publish_snapshot


DAY = pd.Timestamp("2026-11-23")
END = DAY + pd.Timedelta(hours=10, minutes=45)
DAYS = pd.bdate_range(end=DAY, periods=12)


def contract(option_type="call"):
    return {"trade_date": DAYS[-2], "product_group": "CSI300", "option_code": "sample",
            "underlying_code": "000300.SH", "option_type": option_type, "expiry_date": DAY + pd.Timedelta(days=25),
            "underlying_price": 100.0, "strike": 100.0, "year_fraction": 28 / 365, "risk_free_rate": 0.02,
            "dividend_yield": 0.0, "implied_vol": 0.20, "open_interest": 200, "multiplier_or_contract_unit": 100}


def index_prices(momentum):
    rng = np.random.default_rng(12)
    days = []
    for day in DAYS:
        grid = pd.date_range(END - pd.Timedelta(hours=1), END, freq="min") - (DAY - day)
        increments = rng.normal(0, 0.001, len(grid) - 1)
        if day == DAY:
            increments = (np.sin(np.arange(60) / 7) if momentum else (-1.0) ** np.arange(60)) / 1000
        days.append(pd.Series(100 * np.exp(np.r_[0.0, increments.cumsum()]), index=grid))
    return pd.concat(days)


def tick_frame(start, offsets, rows):
    return pd.DataFrame(rows, columns=TICK_FIELDS, index=start + pd.to_timedelta(offsets, unit="s"))


def test_tick_classifier_uses_previous_second_and_increment_vwap():
    end = END
    ticks = tick_frame(end - BAR, [0, 1, 1.2, 2, 3, 10, 299], [
        [2, 1, 3, 100, 20000], [3, 4, 6, 102, 20600], [4, 4, 6, 103, 21000],
        [4, 4, 6, 104, 21400], [6, 4, 6, 106, 22400], [6, 4, 6, 107, 23000],
        [6, 4, 6, 107, 23000],
    ])
    row = classify_ticks(ticks, pd.DatetimeIndex([end]), 100).iloc[0]
    assert row.complete
    assert (row.buy_lots, row.sell_lots, row.unknown_lots, row.signed_updates, row.updates) == (2, 1, 4, 2, 5)


def test_auction_locked_quotes_missing_edges_and_counter_resets():
    start = DAY + pd.Timedelta(hours=14, minutes=55)
    end = pd.DatetimeIndex([start + BAR])
    rows = [[2, 2, 2, 100, 10000], [2, 1, 3, 101, 10200],
            [3, 1, 3, 101, 10200], [3, 1, 3, 102, 10500], [3, 1, 3, 102, 10500]]
    ticks = tick_frame(start, [0, 1, 119, 120, 300], rows)
    bar = classify_ticks(ticks, end, 100).iloc[0]
    assert bar.complete and bar.unknown_lots == 2 and bar.signed_updates == 0
    for truncated in (ticks.iloc[1:], ticks.iloc[:-1], ticks.assign(volume=[100, 101, 0, 1, 2])):
        assert not classify_ticks(truncated, end, 100).iloc[0].complete


@pytest.mark.parametrize(("cutoff", "expected"), [
    ("2026-11-23 09:34", "2026-11-20 15:00"), ("2026-11-23 11:44", "2026-11-23 11:30"),
    ("2026-11-23 13:04", "2026-11-23 11:30"), ("2026-11-23 05:08+00:00", "2026-11-23 13:05"),
    ("2026-11-21 12:00", "2026-11-20 15:00"),
])
def test_completed_cutoffs_use_exchange_sessions(cutoff, expected):
    assert completed_bar(pd.Timestamp(cutoff), DAYS) == pd.Timestamp(expected)
    assert window_bars(pd.Timestamp("2026-11-23 13:05")).tolist() == [pd.Timestamp("2026-11-23 13:05")]


def test_sampling_ranks_only_prior_live_priceable_contracts():
    prior = contract()
    contracts = [dict(prior, option_code=f"C{i:02d}") for i in range(50)]
    contracts += [dict(prior, expiry_date=DAY - pd.Timedelta(days=1), option_code="expired"),
                  dict(prior, open_interest=0, option_code="empty"), dict(prior, implied_vol=np.nan, option_code="no_iv")]
    chain = pd.DataFrame(contracts)
    selected, coverage = select_contracts(chain, DAY, 20)
    assert selected.option_code.tolist() == [f"C{i:02d}" for i in range(20)]
    assert coverage["eligible_contracts"] == 51 and coverage["priceable_contracts"] == 50
    assert coverage["selected_prior_gex_share"] == pytest.approx(0.4)
    with pytest.raises(ValueError, match="strictly prior"):
        select_contracts(chain.assign(trade_date=DAY), DAY, 20)


def estimate(*, buy=1, sell=8, unknown=1, momentum=False, option_type="call", last_complete=True):
    selected, universe = select_contracts(pd.DataFrame([contract(option_type)]), DAY, 20)
    ends = window_bars(END)
    flows = pd.DataFrame([[buy, sell, unknown, 4, 5, True]] * len(ends), index=ends, columns=FLOW_COLUMNS)
    flows.loc[ends[-1], "complete"] = last_complete
    return estimate_intraday_gex(selected, universe, {"sample": flows}, {"000300.SH": pd.Series(100.0, index=ends)},
                                 index_prices(momentum), END)


@pytest.mark.parametrize("option_type", ["call", "put"])
def test_passive_buy_grows_gamma_for_calls_and_puts_with_reversal_confirmation(option_type):
    report = estimate(option_type=option_type)
    assert report["sign"] == "positive" and report["reasons"] == []
    assert report["dealer_net_gex_observed"] is False
    days = (contract()["expiry_date"] + pd.Timedelta(hours=15) - END).total_seconds() / 86400
    unit = calculate_greeks(100, 100, days / 365, 0.02, 0.20, option_type).gamma * 100**2 * 0.01 * 100
    assert report["bars"][-1]["passive_change_rmb_per_1pct"] == pytest.approx(7 * unit)
    flow = report["flow"]
    assert flow["classified_share"] == pytest.approx(0.9)
    assert flow["sample_change_low"] == pytest.approx(flow["passive_change_rmb_per_1pct"] - flow["unclassified_rmb_per_1pct"])
    assert flow["sample_change_high"] > flow["passive_change_rmb_per_1pct"]


def test_negative_requires_concordance_and_weak_observations_abstain():
    assert estimate(buy=8, sell=1, momentum=True)["sign"] == "negative"
    for report, reason in [(estimate(momentum=True), "conflicting_evidence"), (estimate(buy=8), "balanced_flow"),
                           (estimate(unknown=100), "insufficient_signed_flow"), (estimate(last_complete=False), "low_chain_coverage")]:
        assert report["sign"] == "indeterminate" and reason in report["reasons"]


def test_price_response_does_not_read_future_or_bridge_missing_minutes():
    series = index_prices(True)
    start = END - pd.Timedelta(hours=1)
    expected = price_response(series, start, END)
    assert expected["sign"] == "negative"
    with_future = pd.concat([series, pd.Series([9999], index=[END + pd.Timedelta(minutes=1)])])
    assert price_response(with_future, start, END) == expected
    response = price_response(series.drop(pd.date_range(start, END, freq="2min")), start, END)
    assert response["sign"] == "unclear" and response["return_pairs"] == 0
    assert price_response(series[series.index.normalize() == DAY], start, END)["sign"] == "unclear"


def test_wind_validates_identity_and_dates_and_normalizes_amount():
    payload = SimpleNamespace(ErrorCode=0, Codes=["W"], Fields=["LAST", "BID1", "ASK1", "VOLUME", "AMOUNT"],
                              Times=[END, END + BAR], Data=[[2, 2], [1, 1], [3, 3], [20, 21], [40, 42]])
    frame = _frame(payload, "W", TICK_FIELDS, END - BAR, END)
    assert list(frame) == TICK_FIELDS and frame.index.tolist() == [END]
    with pytest.raises(MarketDataError, match="Unexpected"):
        _frame(payload, "X", TICK_FIELDS, END - BAR, END)


def test_cache_retries_partial_buckets_and_never_counts_a_retry_twice(tmp_path):
    class Client:
        calls = 0

        def ticks(self, code, start, end):
            self.calls += 1
            ticks = tick_frame(end - BAR, [0, 1, 299], [[2, 1, 3, 100, 10000], [3, 1, 3, 102, 10600], [3, 1, 3, 102, 10600]])
            return ticks.iloc[:-1] if self.calls == 1 else ticks

    client = Client()
    cache = IntradayCache(tmp_path)
    ends = pd.DatetimeIndex([END])
    assert not cache.flow_buckets(client, "W", 100, ends).iloc[0].complete
    second = cache.flow_buckets(client, "W", 100, ends)
    pd.testing.assert_frame_equal(second, cache.flow_buckets(client, "W", 100, ends))
    assert client.calls == 2 and second.iloc[0].buy_lots == 2


def test_snapshot_reads_exactly_the_previous_session_chain(tmp_path):
    store = OptionMarketDataStore(tmp_path)
    store.write_normalized_chain(pd.DataFrame([dict(contract(), trade_date=DAY, option_code="future")]))
    with pytest.raises(FileNotFoundError, match="2026-11-20"):
        build_snapshot("CSI300", END, DAYS, tmp_path, None, None)
    store.write_normalized_chain(pd.DataFrame([contract()]))
    prices = index_prices(False)

    class Offline:
        def previous_prices(self, client, code, days):
            assert days[-1] == DAYS[-2]
            return prices[prices.index.normalize() < DAY]

        def prices(self, code, start, end):
            assert end == END
            return prices.loc[start:end]

        def flow_buckets(self, client, code, multiplier, ends):
            assert code == "sample" and multiplier == 100 and ends[-1] == END
            return pd.DataFrame([[1, 8, 1, 4, 5, True]] * len(ends), columns=FLOW_COLUMNS, index=ends)

    report = build_snapshot("CSI300", END, DAYS, tmp_path, Offline(), Offline())
    assert report["prior_chain_date"] == "2026-11-20" and report["sign"] == "positive"


def test_dashboard_deep_link_works_without_a_daily_snapshot(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from apps import streamlit_app as dashboard

    monkeypatch.setattr(dashboard, "OPTION_DATA_ROOT", tmp_path)
    monkeypatch.setattr(dashboard, "list_snapshots", lambda *a, **kw: pytest.fail("GEX should load independently"))
    report = dict(estimate(), computed_at="2026-11-23T10:46:00+08:00")
    publish_snapshot(report, tmp_path)
    app = AppTest.from_string("from apps.streamlit_app import main\nmain()")
    app.query_params.update({"view": "intraday-gex", "root": "IF"})
    app.run()
    assert not app.exception and app.radio[0].value == "日内 GEX"
    assert app.metric[0].value == "偏正 GEX" and len(app.get("vega_lite_chart")) == 1
    app.selectbox[0].select("IM").run()
    assert not app.exception and "尚无日内快照" in app.info[0].value


def test_watch_retries_only_failed_products_in_same_cutoff(tmp_path, monkeypatch):
    from scripts import update_intraday_gex as cli

    monkeypatch.setattr(cli.sys, "argv", ["update_intraday_gex", "--watch", "--cache-root", str(tmp_path)])
    monkeypatch.setattr(cli, "WindPyDataClient", lambda: SimpleNamespace(get_trading_calendar=lambda *args: DAYS))
    monkeypatch.setattr(cli, "completed_bar", lambda *args: END)
    calls = []

    def snapshot(product, *args):
        calls.append(product)
        if product == "SSE50" and len(calls) == 1:
            raise MarketDataError("temporary disconnect")
        return {"as_of": str(END), "sign": "indeterminate"}

    def sleep(seconds):
        if len(calls) == 4:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "build_snapshot", snapshot)
    monkeypatch.setattr(cli, "publish_snapshot", lambda *args: tmp_path)
    monkeypatch.setattr(cli.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        cli.main()
    assert calls == ["SSE50", "CSI300", "CSI1000", "SSE50"]
