"""Streamlit dashboard for the Daily Bias Engine."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from daily_bias_engine.data import MockWindDataClient
from daily_bias_engine.pipeline import (
    list_snapshots,
    run_pipeline_from_client,
    run_pipeline_from_snapshot,
)

CONFIG_DIR = PROJECT_ROOT / "configs"
SNAPSHOT_ROOT = PROJECT_ROOT / "data" / "snapshots"


def run_demo_pipeline(
    start_date: str = "2024-01-01",
    end_date: str = "2024-04-30",
    data_mode: str = "mock",
    snapshot_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run the full pipeline used by Streamlit and smoke tests."""

    if data_mode == "snapshot":
        if snapshot_dir is None:
            snapshots = list_snapshots(SNAPSHOT_ROOT)
            if not snapshots:
                raise FileNotFoundError(f"没有找到本地快照：{SNAPSHOT_ROOT}")
            snapshot_dir = snapshots[0].path
        return run_pipeline_from_snapshot(snapshot_dir=snapshot_dir, config_dir=CONFIG_DIR)

    client = MockWindDataClient()
    return run_pipeline_from_client(
        client=client,
        start_date=start_date,
        end_date=end_date,
        config_dir=CONFIG_DIR,
        data_mode="mock",
    )


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="市场风向机", layout="wide")
    st.title("市场风向机 / Daily Bias Engine")

    snapshots = list_snapshots(SNAPSHOT_ROOT)
    default_mode = "本地快照" if snapshots else "Mock 演示"

    with st.sidebar:
        st.header("运行参数")
        data_mode_label = st.radio("数据源", ["本地快照", "Mock 演示"], index=0 if default_mode == "本地快照" else 1)
        selected_snapshot = None
        if data_mode_label == "本地快照":
            if snapshots:
                snapshot_labels = [item.label for item in snapshots]
                selected_label = st.selectbox("快照", snapshot_labels)
                selected_snapshot = snapshots[snapshot_labels.index(selected_label)].path
                st.caption("Wind 数据请先用脚本抓取到本地快照，页面只负责读取。")
            else:
                st.warning("还没有本地快照。请先运行 scripts/fetch_wind_snapshot.py。")

        start_date = st.date_input("开始日期", value=pd.Timestamp("2024-01-01"), disabled=data_mode_label == "本地快照")
        end_date = st.date_input("结束日期", value=pd.Timestamp("2024-04-30"), disabled=data_mode_label == "本地快照")
        run_button = st.button("运行", type="primary")

    if run_button or "demo_result" not in st.session_state:
        try:
            if data_mode_label == "本地快照":
                st.session_state["demo_result"] = run_demo_pipeline(data_mode="snapshot", snapshot_dir=selected_snapshot)
                st.session_state["data_warning"] = ""
            else:
                st.session_state["demo_result"] = run_demo_pipeline(str(start_date), str(end_date), data_mode="mock")
                st.session_state["data_warning"] = ""
        except Exception as exc:
            st.session_state["demo_result"] = run_demo_pipeline(str(start_date), str(end_date), data_mode="mock")
            st.session_state["data_warning"] = f"本地快照读取失败，已回退到 Mock 演示：{exc}"

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
    labels = {
        "snapshot": "本地快照",
        "mock": "Mock 演示",
        "wind": "Wind 实盘",
    }
    return labels.get(value, value)


if __name__ == "__main__":
    main()
