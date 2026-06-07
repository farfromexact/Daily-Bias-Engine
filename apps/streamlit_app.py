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
from daily_bias_engine.data import MockWindDataClient, RawDataCache, WindDataError, WindPyDataClient
from daily_bias_engine.engine import DailyBiasEngine
from daily_bias_engine.features import calculate_all_features
from daily_bias_engine.labeling import label_market_results
from daily_bias_engine.report import build_daily_report

CONFIG_DIR = PROJECT_ROOT / "configs"


def run_demo_pipeline(
    start_date: str = "2024-01-01",
    end_date: str = "2024-04-30",
    data_mode: str = "mock",
) -> dict[str, Any]:
    """Run the full pipeline used by Streamlit and smoke tests."""

    client = _make_client(data_mode)
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
        "data_mode": data_mode,
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

    st.set_page_config(page_title="市场风向机", layout="wide")
    st.title("市场风向机 / Daily Bias Engine")

    with st.sidebar:
        st.header("运行参数")
        data_mode_label = st.radio("数据源", ["Wind 实盘", "Mock 演示"], horizontal=False)
        data_mode = "wind" if data_mode_label == "Wind 实盘" else "mock"
        start_date = st.date_input("开始日期", value=pd.Timestamp("2024-01-01"))
        end_date = st.date_input("结束日期", value=pd.Timestamp("2024-04-30"))
        run_button = st.button("运行", type="primary")

    if run_button or "demo_result" not in st.session_state:
        try:
            st.session_state["demo_result"] = run_demo_pipeline(str(start_date), str(end_date), data_mode=data_mode)
            st.session_state["data_warning"] = ""
        except WindDataError as exc:
            st.session_state["demo_result"] = run_demo_pipeline(str(start_date), str(end_date), data_mode="mock")
            st.session_state["data_warning"] = f"Wind 数据连接失败，已回退到 Mock 演示：{exc}"

    result = st.session_state["demo_result"]
    latest = result["report"]["latest"]
    metrics = result["metrics"]
    if st.session_state.get("data_warning"):
        st.warning(st.session_state["data_warning"])
    st.caption(f"当前数据源：{_data_mode_label(result.get('data_mode', 'mock'))}")

    overview, factors_tab, engine_tab, labels_tab, backtest_tab = st.tabs(
        ["总览", "因子", "引擎", "标签", "回测"]
    )

    with overview:
        columns = st.columns(6)
        columns[0].metric("信号日期", latest.get("date", "N/A"))
        columns[1].metric("市场风向", _bias_label(latest.get("bias_label")))
        columns[2].metric("总分", _format_float(latest.get("total_score")))
        columns[3].metric("趋势日概率", f"{_format_float(latest.get('trend_day_probability'))}%")
        columns[4].metric("趋势方向", _trend_label(latest.get("trend_direction_bias")))
        columns[5].metric("置信度", f"{_format_float(latest.get('confidence'))}%")

        explanation = latest.get("explanation", {})
        st.subheader("每日环境卡片")
        st.write(_trading_posture(latest))

        driver_columns = st.columns(2)
        with driver_columns[0]:
            st.subheader("正向驱动")
            st.dataframe(pd.DataFrame(explanation.get("positive_drivers", [])), use_container_width=True)
        with driver_columns[1]:
            st.subheader("负向驱动")
            st.dataframe(pd.DataFrame(explanation.get("negative_drivers", [])), use_container_width=True)

        st.subheader("风险硬标记")
        risk_flags = latest.get("risk_flags_json", [])
        if risk_flags:
            st.dataframe(pd.DataFrame(risk_flags), use_container_width=True)
        else:
            st.write("无")

    with factors_tab:
        st.dataframe(result["factors"], use_container_width=True)

    with engine_tab:
        st.dataframe(result["scores"], use_container_width=True)
        st.subheader("最新分项分")
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


def _make_client(data_mode: str) -> MockWindDataClient | WindPyDataClient:
    if data_mode == "wind":
        return WindPyDataClient(cache=RawDataCache(PROJECT_ROOT / "data" / "raw" / "wind"))
    return MockWindDataClient()


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
        return "防守优先。避免过早做多抄底，优先控制回撤和仓位。"
    if label == "Risk-On" and trend_probability >= 60 and direction == "up":
        return "顺势优先。若开盘后放量确认，上行趋势策略可以提高优先级。"
    if label == "Risk-On":
        return "环境偏建设性。优先观察多头机会，但提高频率前仍需要开盘确认。"
    if trend_probability >= 60:
        return "方向不清晰，但趋势日概率较高。降低均值回归假设，等待方向确认。"
    return "中性环境。降低交易频率，等待更强确认。"


def _bias_label(value: Any) -> str:
    labels = {
        "Risk-On": "Risk-On / 进攻",
        "Neutral": "Neutral / 等待",
        "Risk-Off": "Risk-Off / 防守",
    }
    return labels.get(str(value), "N/A")


def _trend_label(value: Any) -> str:
    labels = {
        "up": "上行",
        "down": "下行",
        "unclear": "不明确",
    }
    return labels.get(str(value), "N/A")


def _data_mode_label(value: str) -> str:
    return "Wind 实盘" if value == "wind" else "Mock 演示"


if __name__ == "__main__":
    main()
