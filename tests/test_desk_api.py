import json
from types import SimpleNamespace

import pandas as pd
import pytest

from daily_bias_engine.desk_api import DeskHandler, archive_market_bias, desk_context
from daily_bias_engine.options.analytics.intraday_gex import freshness, iso_time, local_time
from daily_bias_engine.options.reports.intraday_gex import publish_snapshot
from daily_bias_engine.pipeline import list_snapshots


def timestamp(clock):
    return pd.Timestamp(f"2026-11-23 {clock}")


def write_market(root, published, signal_date, end, bias, source="wind"):
    stamp = published.tz_localize("Asia/Shanghai").strftime("%Y%m%dT%H%M%S%z")
    base = root / f"{stamp}_{source}_2024-01-01_{end}"
    outputs = base / "outputs"
    outputs.mkdir(parents=True)
    latest = {"date": signal_date, "bias_label": bias, "raw_score_bias": "Neutral", "total_score": -9.0,
              "risk_override": False}
    (outputs / "report.json").write_text(json.dumps({"latest": latest}))
    (base / "manifest.json").write_text(json.dumps({"source": source, "created_at": stamp, "end_date": end,
                                                     "start_date": "2024-01-01", "latest": latest}))
    return base


def gex_report(clock, published, sign, product="CSI300"):
    return {"product": product, "as_of": iso_time(timestamp(clock)), "computed_at": iso_time(timestamp(published)),
            "sign": sign, "trade_date": "2026-11-23", "bars": [], "reasons": []}


def test_market_and_option_clocks_are_independent_and_keep_actual_publication(tmp_path):
    market, options = tmp_path / "market", tmp_path / "options"
    write_market(market, timestamp("09:21"), "2026-11-23", "2026-11-20", "Neutral")
    write_market(market, timestamp("19:00"), "2026-11-24", "2026-11-23", "Risk-Off")
    write_market(market, timestamp("19:30"), "2026-11-24", "2026-11-23", "IFIND", source="ifind")
    publish_snapshot(gex_report("15:00", "20:01", "negative"), options)

    def read(clock, root="IF"):
        return desk_context(root, timestamp(clock), snapshot_root=market, options_root=options)

    assert read("09:20")["market_bias"] == {"status": "unavailable"}
    assert read("15:00")["market_bias"]["status"] == "same_day_snapshot"
    evening = read("19:31")
    assert evening["market_bias"]["status"] == "next_session_preview"
    assert evening["market_bias"]["bias"] == "Risk-Off" and evening["market_bias"]["scope"] == "A_share_market"
    assert evening["intraday_gex"] == {"status": "unavailable", "sign": "indeterminate"}
    current = read("20:02")
    assert current["intraday_gex"]["status"] == "session_close" and current["intraday_gex"]["sign"] == "negative"
    for root, product in [("IH", "SSE50"), ("IM", "CSI1000")]:
        other = read("20:02", root)
        assert other["product"] == product and other["market_bias"] == current["market_bias"]
        assert other["intraday_gex"]["status"] == "unavailable" and other["dashboard_url"].endswith("root=" + root)

    old = list_snapshots(market, source="wind")[-1]
    archive_market_bias(market, old)
    old.path.rename(tmp_path / "retired-full-snapshot")
    restored = read("15:00")["market_bias"]
    assert restored["bias"] == "Neutral" and restored["snapshot_id"] == old.path.name
    assert restored["published_at"] == iso_time(timestamp("09:21"))


def test_as_published_revisions_and_idempotent_writes(tmp_path):
    first = gex_report("10:00", "10:01", "positive")
    path = publish_snapshot(first, tmp_path)
    assert publish_snapshot(dict(first, computed_at=iso_time(timestamp("10:03"))), tmp_path) == path
    revision = publish_snapshot(gex_report("10:00", "10:15", "negative"), tmp_path)
    assert revision != path
    with pytest.raises(ValueError, match="Conflicting"):
        publish_snapshot(gex_report("10:00", "10:15", "positive"), tmp_path)
    publish_snapshot(gex_report("10:10", "19:00", "indeterminate"), tmp_path)

    def read(clock):
        return desk_context("IF", timestamp(clock), snapshot_root=tmp_path / "market", options_root=tmp_path)["intraday_gex"]

    assert read("09:59")["status"] == "unavailable"
    assert read("10:02")["sign"] == "positive"
    assert read("10:14")["sign"] == "positive" and read("10:14")["status"] == "delayed"
    assert read("10:16")["sign"] == "negative"
    assert read("19:01")["as_of"] == iso_time(timestamp("10:10"))
    assert "bars" not in read("19:01")


def test_legacy_market_snapshot_does_not_invent_missing_fields(tmp_path):
    root = tmp_path / "market"
    day = pd.Timestamp("2026-06-07 19:45")
    path = write_market(root, day, "2026-06-08", "2026-06-05", "Risk-Off")
    manifest = json.loads((path / "manifest.json").read_text())
    manifest["latest"].pop("raw_score_bias")
    manifest["latest"].pop("risk_override")
    (path / "manifest.json").write_text(json.dumps(manifest))
    # Old snapshots could lack precomputed output or an independently recorded raw bias.
    (path / "outputs/report.json").unlink()
    context = desk_context("IF", timestamp("15:00"), snapshot_root=root, options_root=tmp_path)
    market = context["market_bias"]
    assert market["status"] == "prior_session" and market["bias"] == "Risk-Off"
    assert market["raw_bias"] is None and market["risk_override"] is None
    assert context["intraday_gex"]["status"] == "unavailable"


@pytest.mark.parametrize(("data", "asof", "status"), [
    ("2026-11-23 10:00", "2026-11-23 10:10", "recent"),
    ("2026-11-23 10:00", "2026-11-23 10:11", "delayed"),
    ("2026-11-23 11:30", "2026-11-23 13:04", "midday_close"),
    ("2026-11-23 11:25", "2026-11-23 11:31", "delayed"),
    ("2026-11-23 11:30", "2026-11-23 13:05", "delayed"),
    ("2026-11-23 15:00", "2026-11-23 20:00", "session_close"),
    ("2026-11-23 14:55", "2026-11-23 15:01", "delayed"),
    ("2026-11-23 15:00", "2026-11-24 09:15", "prior_session"),
])
def test_freshness_distinguishes_lunch_close_and_old_records(data, asof, status):
    assert freshness(local_time(data), local_time(asof)) == status


@pytest.mark.parametrize(("path", "expected"), [
    ("/healthz", 200), ("/v1/desk/context/IF", 200), ("/v1/desk/context/IF?as_of=2024-01-03T02%3A00%3A00Z", 200),
    ("/v1/desk/context/IM?as_of=", 400), ("/v1/desk/context/IF?as_of=broken", 400),
    ("/v1/desk/context/IF?as_of=2100-11-13", 400), ("/v1/desk/context/IF?as_of=2024&as_of=2025", 400),
    ("/v1/desk/context/IF?code=IH", 400), ("/v1/desk/context/IC", 404),
])
def test_http_read_contract(tmp_path, path, expected):
    result = []
    handler = SimpleNamespace(path=path, snapshot_root=tmp_path, options_root=tmp_path, dashboard_url="http://localhost/",
                              _send=lambda status, payload: result.append((status, payload)))
    DeskHandler.do_GET(handler)
    status, payload = result[0]
    assert status == expected and (status == 200 or "error" in payload)


def test_unreadable_local_report_returns_503(tmp_path):
    sample = dict(gex_report("10:00", "10:01", "positive"), as_of=iso_time("2024-10-09 10:00"),
                  computed_at=iso_time("2024-10-09 10:01"), trade_date="2024-10-09")
    path = publish_snapshot(sample, tmp_path)
    path.write_text("{")
    result = []
    handler = SimpleNamespace(path="/v1/desk/context/IF?as_of=2024-10-09T11%3A00",
                              snapshot_root=tmp_path, options_root=tmp_path, dashboard_url="http://localhost/",
                              _send=lambda status, payload: result.append(status))
    DeskHandler.do_GET(handler)
    assert result == [503]
