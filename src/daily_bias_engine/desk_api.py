"""Loopback, snapshot-only market context for the trading desk."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import parse_qs, urlencode, urlsplit

import pandas as pd

from daily_bias_engine.options.analytics.intraday_gex import PRODUCT_ROOTS, SHANGHAI, freshness, iso_time, local_time
from daily_bias_engine.options.reports.intraday_gex import latest_visible_report
from daily_bias_engine.pipeline import SnapshotInfo, list_snapshots

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _bias_vintage(snapshot: SnapshotInfo) -> dict:
    path = snapshot.path / "outputs/report.json"
    if not path.is_file():
        path = snapshot.path / "manifest.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    latest = report["latest"]
    published = pd.to_datetime(snapshot.created_at, format="%Y%m%dT%H%M%S%z")
    return {"scope": "A_share_market", "benchmark": "000300.SH", "signal_date": str(pd.Timestamp(latest["date"]).date()),
            "data_through": snapshot.end_date, "published_at": iso_time(published), "snapshot_id": snapshot.path.name,
            "bias": latest["bias_label"], "raw_bias": latest.get("raw_score_bias"), "score": latest["total_score"],
            "risk_override": latest.get("risk_override"), "overseas_components": report.get("latest_overseas_components")}


def archive_market_bias(snapshot_root: Path, snapshot: SnapshotInfo) -> None:
    """Keep the small as-published record when a full Wind snapshot rotates out."""
    directory = snapshot_root / "market_bias_history"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{snapshot.end_date}_{snapshot.created_at}.json"
    body = json.dumps(_bias_vintage(snapshot), ensure_ascii=False, allow_nan=False)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as f:
        stage = Path(f.name)
        f.write(body)
    try:
        stage.replace(path)
    finally:
        stage.unlink(missing_ok=True)


def _market_bias(snapshot_root: Path, cutoff: pd.Timestamp) -> dict:
    active = {(s.end_date, s.created_at): s for s in list_snapshots(snapshot_root, source="wind")}
    directory = snapshot_root / "market_bias_history"
    archived = {tuple(p.stem.split("_", 1)): p for p in directory.glob("????-??-??_*.json")}
    for key in sorted(active.keys() | archived.keys(), reverse=True):
        published = local_time(pd.to_datetime(key[1], format="%Y%m%dT%H%M%S%z"))
        if published > cutoff or key[0] > str(cutoff.date()):
            continue
        if key in archived:
            vintage = json.loads(archived[key].read_text(encoding="utf-8"))
        else:
            try:
                vintage = _bias_vintage(active[key])
            except FileNotFoundError:
                # A collector may rotate a full snapshot between listing and reading it.
                vintage = json.loads((directory / f"{key[0]}_{key[1]}.json").read_text(encoding="utf-8"))
        signal_day = pd.Timestamp(vintage["signal_date"]).date()
        if signal_day > cutoff.date():
            status = "next_session_preview"
        elif signal_day < cutoff.date():
            status = "prior_session"
        else:
            status = "same_day_snapshot"
        return {"status": status, **vintage}
    return {"status": "unavailable"}


def desk_context(root: str, cutoff: pd.Timestamp, *, snapshot_root: Path, options_root: Path,
                 dashboard_url: str = "http://127.0.0.1:8506/") -> dict:
    """Return only estimates published by cutoff, even for retrospective requests."""
    product = PRODUCT_ROOTS[root]
    cutoff = local_time(cutoff)
    gex = {"status": "unavailable", "sign": "indeterminate"}
    report = latest_visible_report(options_root, product, cutoff)
    if report is not None:
        gex = {key: value for key, value in report.items() if key != "bars"}
        gex["status"] = freshness(local_time(report["as_of"]), cutoff)
    return {"schema_version": 1, "root": root, "product": product, "as_of": iso_time(cutoff),
            "market_bias": _market_bias(snapshot_root, cutoff), "intraday_gex": gex,
            "dashboard_url": dashboard_url.rstrip("/") + "/?" + urlencode({"view": "intraday-gex", "root": root})}


class DeskHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, snapshot_root: Path, options_root: Path, dashboard_url: str, **kwargs):
        self.snapshot_root = snapshot_root
        self.options_root = options_root
        self.dashboard_url = dashboard_url
        super().__init__(*args, **kwargs)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/healthz":
            self._send(200, {"status": "ok", "schema_version": 1})
            return
        prefix = "/v1/desk/context/"
        root = url.path.removeprefix(prefix)
        if not url.path.startswith(prefix) or root not in PRODUCT_ROOTS:
            self._send(404, {"error": "unknown route or index future root"})
            return
        params = parse_qs(url.query, keep_blank_values=True)
        if set(params) - {"as_of"} or len(params.get("as_of", [])) > 1:
            self._send(400, {"error": "expected at most one as_of parameter"})
            return
        now = local_time(pd.Timestamp.now(tz=SHANGHAI))
        try:
            cutoff = local_time(params["as_of"][0]) if "as_of" in params else now
            if pd.isna(cutoff) or cutoff > now:
                raise ValueError("invalid cutoff")
        except (ValueError, OverflowError):
            self._send(400, {"error": "as_of must be a valid past or current timestamp"})
            return
        try:
            payload = desk_context(root, cutoff, snapshot_root=self.snapshot_root, options_root=self.options_root,
                                   dashboard_url=self.dashboard_url)
            self._send(200, payload)
        except (OSError, KeyError, ValueError):
            self._send(503, {"error": "local snapshot unreadable"})

    def _send(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8507)
    parser.add_argument("--snapshot-root", type=Path, default=PROJECT_ROOT / "data/snapshots")
    parser.add_argument("--options-root", type=Path, default=PROJECT_ROOT / "data/options_wind")
    parser.add_argument("--dashboard-url", default="http://127.0.0.1:8506/")
    args = parser.parse_args()
    handler = partial(DeskHandler, snapshot_root=args.snapshot_root, options_root=args.options_root, dashboard_url=args.dashboard_url)
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Trading desk context at http://127.0.0.1:{args.port}/v1/desk/context/IF", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
