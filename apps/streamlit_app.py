"""Streamlit dashboard for the Daily Bias Engine MVP."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from daily_bias_engine.backtest import evaluate_bias_predictions
from daily_bias_engine.data import MockWindDataClient
from daily_bias_engine.engine import DailyBiasEngine
from daily_bias_engine.features import calculate_all_features
from daily_bias_engine.labeling import label_market_results
from daily_bias_engine.report import build_daily_report

CONFIG_DIR = PROJECT_ROOT / "configs"


def run_demo_pipeline(
    start_date: str = "2024-01-01",
    end_date: str = "2024-04-30",
) -> dict[str, Any]:
    """Run the full mock-data pipeline used by Streamlit and smoke tests."""

    client = MockWindDataClient()
    index_ohlcv = client.get_daily_ohlcv(["000300.SH"], start_date, end_date)
    futures_ohlcv = client.get_daily_ohlcv(["IF.CFE"], start_date, end_date)
    open_interest = client.get_futures_open_interest(["IF.CFE"], start_date, end_date)
    rates = client.get_interest_rates(["DR007.IB", "CGB10Y.IB"], start_date, end_date)
    etf_flow = _with_margin_balance(
        client.get_daily_ohlcv(["510300.SH", "510500.SH"], start_date, end_date)
    )
    overseas_ohlcv = client.get_daily_ohlcv(["SPX.GI", "HSI.HI"], start_date, end_date)
    ashare_ohlcv = client.get_daily_ohlcv(["000300.SH", "000905.SH", "000852.SH"], start_date, end_date)

    factors = calculate_all_features(
        index_ohlcv=index_ohlcv,
        futures_ohlcv=futures_ohlcv,
        open_interest=open_interest,
        rates=rates,
        etf_flow=etf_flow,
        overseas_ohlcv=overseas_ohlcv,
        ashare_ohlcv=ashare_ohlcv,
    )
    engine = DailyBiasEngine.from_yaml(CONFIG_DIR / "factor_weights.yaml", CONFIG_DIR / "thresholds.yaml")
    scores = engine.score(factors)

    labeling_config = _load_yaml(CONFIG_DIR / "thresholds.yaml").get("labeling", {})
    labels = label_market_results(index_ohlcv, symbol="000300.SH", **labeling_config)

    backtest_config = _load_yaml(CONFIG_DIR / "thresholds.yaml").get("backtest", {})
    metrics = evaluate_bias_predictions(scores, labels, **backtest_config)
    report = build_daily_report(factors=factors, engine_output=scores, labels=labels, metrics=metrics)

    return {
        "factors": factors,
        "scores": scores,
        "labels": labels,
        "metrics": metrics,
        "report": report,
        "raw": {
            "index_ohlcv": index_ohlcv,
            "futures_ohlcv": futures_ohlcv,
            "open_interest": open_interest,
            "rates": rates,
            "etf_flow": etf_flow,
            "overseas_ohlcv": overseas_ohlcv,
            "ashare_ohlcv": ashare_ohlcv,
        },
    }


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Daily Bias Engine", layout="wide")
    st.title("Daily Bias Engine")

    with st.sidebar:
        st.header("Demo Range")
        start_date = st.date_input("Start date", value=pd.Timestamp("2024-01-01"))
        end_date = st.date_input("End date", value=pd.Timestamp("2024-04-30"))
        run_button = st.button("Run demo", type="primary")

    if run_button or "demo_result" not in st.session_state:
        st.session_state["demo_result"] = run_demo_pipeline(str(start_date), str(end_date))

    result = st.session_state["demo_result"]
    latest = result["report"]["latest"]
    metrics = result["metrics"]

    overview, factors_tab, engine_tab, labels_tab, backtest_tab = st.tabs(
        ["Overview", "Factors", "Engine", "Labels", "Backtest"]
    )

    with overview:
        columns = st.columns(6)
        columns[0].metric("Signal date", latest.get("date", "N/A"))
        columns[1].metric("Bias", latest.get("bias_label", "N/A"))
        columns[2].metric("Score", _format_float(latest.get("total_score")))
        columns[3].metric("Trend probability", f"{_format_float(latest.get('trend_day_probability'))}%")
        columns[4].metric("Trend direction", latest.get("trend_direction_bias", "N/A"))
        columns[5].metric("Confidence", f"{_format_float(latest.get('confidence'))}%")

        explanation = latest.get("explanation", {})
        st.subheader("Daily environment card")
        st.write(_trading_posture(latest))

        driver_columns = st.columns(2)
        with driver_columns[0]:
            st.subheader("Positive drivers")
            st.dataframe(pd.DataFrame(explanation.get("positive_drivers", [])), use_container_width=True)
        with driver_columns[1]:
            st.subheader("Negative drivers")
            st.dataframe(pd.DataFrame(explanation.get("negative_drivers", [])), use_container_width=True)

        st.subheader("Risk flags")
        risk_flags = latest.get("risk_flags_json", [])
        if risk_flags:
            st.dataframe(pd.DataFrame(risk_flags), use_container_width=True)
        else:
            st.write("None")

    with factors_tab:
        st.dataframe(result["factors"], use_container_width=True)

    with engine_tab:
        st.dataframe(result["scores"], use_container_width=True)
        st.subheader("Latest sub-scores")
        st.json(latest.get("sub_scores", {}))

    with labels_tab:
        st.dataframe(result["labels"], use_container_width=True)

    with backtest_tab:
        st.json(metrics)


def _with_margin_balance(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output["date"] = pd.to_datetime(output["date"]).dt.normalize()
    daily_amount = output.groupby("date")["amount"].transform("mean")
    rank = output.groupby("symbol").cumcount()
    output["margin_balance"] = daily_amount * (1.2 + rank * 0.002)
    return output


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _format_float(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.3f}"


def _trading_posture(latest: dict[str, Any]) -> str:
    label = latest.get("bias_label")
    trend_probability = float(latest.get("trend_day_probability") or 0.0)
    direction = latest.get("trend_direction_bias")
    if label == "Risk-Off":
        return "Defensive posture. Avoid early long-side bottom fishing; prioritize risk control."
    if label == "Risk-On" and trend_probability >= 60 and direction == "up":
        return "Trend-following posture. Upside trend strategies can receive higher priority after opening confirmation."
    if label == "Risk-On":
        return "Constructive posture. Prefer long setups, but require opening confirmation before increasing frequency."
    if trend_probability >= 60:
        return "Directional environment is unclear, but trend-day risk is elevated. Reduce mean-reversion assumptions."
    return "Neutral posture. Lower trade frequency and require stronger confirmation."


if __name__ == "__main__":
    main()
