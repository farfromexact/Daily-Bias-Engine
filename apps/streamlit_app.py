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
from daily_bias_engine.features import factor_logic_rows
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

    overview, factors_tab, engine_tab, labels_tab, backtest_tab, logic_tab = st.tabs(
        ["总览", "因子", "引擎", "标签", "回测", "逻辑说明"]
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
        scores = result["scores"].copy()
        st.subheader("每日信号总览")
        st.dataframe(_engine_summary_table(scores), use_container_width=True, hide_index=True)

        selected_date = st.selectbox("查看某一天的引擎解释", _date_options(scores), index=max(len(scores) - 1, 0))
        selected_row = _selected_engine_row(scores, selected_date)
        selected_explanation = selected_row.get("explanation", {}) if selected_row else {}

        detail_columns = st.columns(5)
        detail_columns[0].metric("市场风向", _bias_label(selected_row.get("bias_label") if selected_row else None))
        detail_columns[1].metric("总分", _format_float(selected_row.get("total_score") if selected_row else None))
        detail_columns[2].metric("趋势日概率", f"{_format_float(selected_row.get('trend_day_probability') if selected_row else None)}%")
        detail_columns[3].metric("趋势方向", _trend_label(selected_row.get("trend_direction_bias") if selected_row else None))
        detail_columns[4].metric("置信度", f"{_format_float(selected_row.get('confidence') if selected_row else None)}%")

        st.subheader("分项分")
        st.dataframe(_sub_scores_table(selected_row.get("sub_scores", {}) if selected_row else {}), use_container_width=True, hide_index=True)

        st.subheader("风险硬标记")
        risk_flags = selected_row.get("risk_flags_json", []) if selected_row else []
        if risk_flags:
            st.dataframe(_risk_flags_table(risk_flags), use_container_width=True, hide_index=True)
        else:
            st.write("无风险硬标记。")

        driver_columns = st.columns(2)
        with driver_columns[0]:
            st.subheader("正向驱动")
            st.dataframe(_drivers_table(selected_explanation.get("positive_drivers", [])), use_container_width=True, hide_index=True)
        with driver_columns[1]:
            st.subheader("负向驱动")
            st.dataframe(_drivers_table(selected_explanation.get("negative_drivers", [])), use_container_width=True, hide_index=True)

        st.subheader("全部因子贡献")
        st.dataframe(_factor_contribution_table(selected_explanation.get("factors", [])), use_container_width=True, hide_index=True)

    with labels_tab:
        st.markdown(
            """
            `标签` 是收盘后的市场结果，用来评价开盘前信号有没有提前识别环境。
            它不是预测信号。比如某天被标为 `down_trend_day_flag` 和 `big_loss_day_flag`，
            说明当天实际走势符合“下跌趋势日/大亏日”的定义。
            """
        )
        st.dataframe(result["labels"], use_container_width=True)

    with backtest_tab:
        st.subheader("回测摘要")
        st.markdown(_backtest_plain_language(metrics))
        metric_columns = st.columns(6)
        metric_columns[0].metric("样本天数", str(metrics.get("observations", 0)))
        metric_columns[1].metric("方向命中率", _format_percent(metrics.get("bias_accuracy")))
        metric_columns[2].metric("趋势日 precision", _format_percent(metrics.get("trend_day_precision")))
        metric_columns[3].metric("趋势日 recall", _format_percent(metrics.get("trend_day_recall")))
        metric_columns[4].metric("大亏日过滤率", _format_percent(metrics.get("big_loss_day_filter_rate")))
        metric_columns[5].metric("Risk-Off 误伤率", _format_percent(metrics.get("false_risk_off_rate")))

        st.subheader("指标解释")
        st.dataframe(_metrics_explanation_table(metrics), use_container_width=True, hide_index=True)

        st.subheader("逐日复盘")
        st.dataframe(_backtest_review_table(result["scores"], result["labels"]), use_container_width=True, hide_index=True)

    with logic_tab:
        st.subheader("系统如何使用这些因子")
        st.markdown(
            """
            当前版本是规则引擎，不是机器学习模型。每个因子先计算原始值，再做 20 日滚动 z-score，
            然后按风险方向映射成 `directional_score`。最终因子得分为 `directional_score * 100`，
            引擎按配置权重加权得到 `-100` 到 `+100` 的总分。

            日收盘数据只生成下一交易日的开盘前信号，因此表里的 `data_date` 必须早于 `date`。

            **注意：当前快照可以是真实 Wind 数据。这里的 proxy 通常指“因子口径是替代变量”，
            不是说底层行情是假数据。** 例如 ETF 成交额是真实 Wind 数据，但它只是 ETF 净申购的
            proxy；指数样本上涨比例是真实 Wind 价格派生结果，但它只是全市场上涨家数的 proxy。
            """
        )
        st.dataframe(pd.DataFrame(factor_logic_rows()), use_container_width=True)


def _engine_summary_table(scores: pd.DataFrame) -> pd.DataFrame:
    table = scores[
        [
            "date",
            "bias_label",
            "total_score",
            "confidence",
            "trend_day_probability",
            "trend_direction_bias",
        ]
    ].copy()
    table["date"] = pd.to_datetime(table["date"]).dt.strftime("%Y-%m-%d")
    table["bias_label"] = table["bias_label"].map(_bias_label)
    table["trend_direction_bias"] = table["trend_direction_bias"].map(_trend_label)
    table = table.rename(
        columns={
            "date": "信号日期",
            "bias_label": "市场风向",
            "total_score": "总分",
            "confidence": "置信度",
            "trend_day_probability": "趋势日概率",
            "trend_direction_bias": "趋势方向",
        }
    )
    return _round_numeric(table)


def _date_options(scores: pd.DataFrame) -> list[str]:
    return pd.to_datetime(scores["date"]).dt.strftime("%Y-%m-%d").tolist()


def _selected_engine_row(scores: pd.DataFrame, selected_date: str) -> dict[str, Any]:
    prepared = scores.copy()
    prepared["date_label"] = pd.to_datetime(prepared["date"]).dt.strftime("%Y-%m-%d")
    matched = prepared[prepared["date_label"] == selected_date]
    if matched.empty:
        return {}
    return matched.iloc[0].to_dict()


def _sub_scores_table(sub_scores: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for group, score in sub_scores.items():
        score_value = float(score)
        rows.append(
            {
                "模块": _group_label(group),
                "分项分": score_value,
                "解释": _score_interpretation(score_value),
            }
        )
    return _round_numeric(pd.DataFrame(rows).sort_values("分项分", ascending=False))


def _risk_flags_table(risk_flags: list[dict[str, Any]]) -> pd.DataFrame:
    if not risk_flags:
        return pd.DataFrame(columns=["风险类型", "因子", "模块", "因子分", "触发阈值", "含义"])
    rows = []
    for flag in risk_flags:
        rows.append(
            {
                "风险类型": "硬 Risk-Off",
                "因子": flag.get("factor_name"),
                "模块": _group_label(flag.get("group")),
                "因子分": flag.get("factor_score"),
                "触发阈值": flag.get("threshold"),
                "含义": "该因子跌破硬风险阈值，即使总分不够低，也会把环境降级为 Risk-Off。",
            }
        )
    return _round_numeric(pd.DataFrame(rows))


def _drivers_table(drivers: list[dict[str, Any]]) -> pd.DataFrame:
    if not drivers:
        return pd.DataFrame(columns=["因子", "模块", "因子分", "贡献", "原始值", "z-score"])
    table = pd.DataFrame(drivers).rename(
        columns={
            "factor_name": "因子",
            "group": "模块",
            "factor_score": "因子分",
            "contribution": "贡献",
            "raw_value": "原始值",
            "zscore_value": "z-score",
        }
    )
    table["模块"] = table["模块"].map(_group_label)
    return _round_numeric(table[["因子", "模块", "因子分", "贡献", "原始值", "z-score"]])


def _factor_contribution_table(factors: list[dict[str, Any]]) -> pd.DataFrame:
    if not factors:
        return pd.DataFrame(columns=["数据日期", "因子", "模块", "方向分", "因子分", "权重", "贡献", "原始值", "z-score"])
    table = pd.DataFrame(factors).rename(
        columns={
            "data_date": "数据日期",
            "factor_name": "因子",
            "group": "模块",
            "directional_score": "方向分",
            "factor_score": "因子分",
            "weight": "权重",
            "contribution": "贡献",
            "raw_value": "原始值",
            "zscore_value": "z-score",
        }
    )
    table["模块"] = table["模块"].map(_group_label)
    columns = ["数据日期", "因子", "模块", "方向分", "因子分", "权重", "贡献", "原始值", "z-score"]
    return _round_numeric(table[columns].sort_values("贡献", ascending=False))


def _metrics_explanation_table(metrics: dict[str, Any]) -> pd.DataFrame:
    rows = [
        {
            "指标": "方向命中率",
            "当前值": _format_percent(metrics.get("bias_accuracy")),
            "普通解释": "Risk-On 后市场上涨、Risk-Off 后市场下跌、Neutral 后市场小波动的比例。",
            "怎么解读": _quality_label(metrics.get("bias_accuracy"), high=0.55, low=0.45),
        },
        {
            "指标": "趋势日 precision",
            "当前值": _format_percent(metrics.get("trend_day_precision")),
            "普通解释": "系统说趋势日概率高的时候，实际有多少天真成了趋势日。",
            "怎么解读": _quality_label(metrics.get("trend_day_precision"), high=0.45, low=0.25),
        },
        {
            "指标": "趋势日 recall",
            "当前值": _format_percent(metrics.get("trend_day_recall")),
            "普通解释": "所有真实趋势日中，系统提前抓到了多少。",
            "怎么解读": _quality_label(metrics.get("trend_day_recall"), high=0.45, low=0.25),
        },
        {
            "指标": "大亏日过滤率",
            "当前值": _format_percent(metrics.get("big_loss_day_filter_rate")),
            "普通解释": "真实大亏日里，有多少天系统没有给 Risk-On。",
            "怎么解读": _quality_label(metrics.get("big_loss_day_filter_rate"), high=0.70, low=0.50),
        },
        {
            "指标": "Risk-Off 误伤率",
            "当前值": _format_percent(metrics.get("false_risk_off_rate")),
            "普通解释": "非大亏日里，被系统标成 Risk-Off 的比例。越低越好。",
            "怎么解读": _inverse_quality_label(metrics.get("false_risk_off_rate"), high=0.20, low=0.35),
        },
    ]
    return pd.DataFrame(rows)


def _backtest_review_table(scores: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    scored = scores[["date", "bias_label", "total_score", "trend_day_probability", "trend_direction_bias"]].copy()
    realized = labels[["date", "market_return", "trend_day_flag", "big_loss_day_flag"]].copy()
    scored["date"] = pd.to_datetime(scored["date"]).dt.normalize()
    realized["date"] = pd.to_datetime(realized["date"]).dt.normalize()
    joined = scored.merge(realized, on="date", how="inner").sort_values("date", ascending=False)
    joined["复盘结论"] = joined.apply(_daily_review_label, axis=1)
    joined["date"] = joined["date"].dt.strftime("%Y-%m-%d")
    joined["bias_label"] = joined["bias_label"].map(_bias_label)
    joined["trend_direction_bias"] = joined["trend_direction_bias"].map(_trend_label)
    joined["market_return"] = joined["market_return"].map(lambda value: _format_percent(value))
    joined = joined.rename(
        columns={
            "date": "日期",
            "bias_label": "开盘前风向",
            "total_score": "总分",
            "trend_day_probability": "趋势日概率",
            "trend_direction_bias": "趋势方向",
            "market_return": "实际市场收益",
            "trend_day_flag": "实际趋势日",
            "big_loss_day_flag": "实际大亏日",
        }
    )
    columns = ["日期", "开盘前风向", "总分", "趋势日概率", "趋势方向", "实际市场收益", "实际趋势日", "实际大亏日", "复盘结论"]
    return _round_numeric(joined[columns].head(80))


def _backtest_plain_language(metrics: dict[str, Any]) -> str:
    observations = metrics.get("observations", 0)
    return (
        f"本次回测共有 **{observations}** 个可比较交易日。"
        f"方向命中率为 **{_format_percent(metrics.get('bias_accuracy'))}**；"
        f"大亏日过滤率为 **{_format_percent(metrics.get('big_loss_day_filter_rate'))}**；"
        f"Risk-Off 误伤率为 **{_format_percent(metrics.get('false_risk_off_rate'))}**。"
        "这些指标用于复盘环境过滤器是否有用，不是收益率回测。"
    )


def _daily_review_label(row: pd.Series) -> str:
    bias = row["bias_label"]
    market_return = float(row["market_return"])
    trend_day = bool(row["trend_day_flag"])
    big_loss = bool(row["big_loss_day_flag"])
    if big_loss and bias != "Risk-On":
        return "大亏日未给进攻，风险过滤有效"
    if big_loss and bias == "Risk-On":
        return "严重漏判：大亏日仍给进攻"
    if bias == "Risk-On" and market_return > 0.003:
        return "进攻信号命中"
    if bias == "Risk-Off" and market_return < -0.003:
        return "防守信号命中"
    if bias == "Neutral" and abs(market_return) <= 0.003:
        return "中性判断匹配"
    if bias == "Risk-Off" and market_return > 0.003:
        return "可能误伤机会"
    if trend_day:
        return "趋势日未充分识别"
    return "普通偏差"


def _group_label(value: Any) -> str:
    labels = {
        "equity_index_futures": "股指期货结构",
        "rates_and_bond_futures": "利率与债券",
        "etf_and_margin_flow": "ETF 与资金流",
        "overseas_market": "海外隔夜",
        "ashare_market_structure": "A股市场结构",
        "ungrouped": "未分组",
    }
    return labels.get(str(value), str(value))


def _score_interpretation(score: float) -> str:
    if score >= 30:
        return "明显偏 Risk-On"
    if score <= -30:
        return "明显偏 Risk-Off"
    if score > 5:
        return "轻微偏多"
    if score < -5:
        return "轻微偏空"
    return "接近中性"


def _quality_label(value: Any, high: float, low: float) -> str:
    number = float(value or 0.0)
    if number >= high:
        return "较好"
    if number < low:
        return "偏弱，需要改进"
    return "一般"


def _inverse_quality_label(value: Any, high: float, low: float) -> str:
    number = float(value or 0.0)
    if number <= high:
        return "较好"
    if number > low:
        return "偏高，需要降低"
    return "一般"


def _round_numeric(table: pd.DataFrame) -> pd.DataFrame:
    output = table.copy()
    numeric_columns = output.select_dtypes(include="number").columns
    output[numeric_columns] = output[numeric_columns].round(3)
    return output


def _format_percent(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value) * 100:.1f}%"


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
