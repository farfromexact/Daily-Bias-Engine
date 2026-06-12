"""Streamlit dashboard for the Daily Bias Engine."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from daily_bias_engine.backtest import (
    bias_return_diagnostics,
    factor_diagnostics,
    score_bucket_diagnostics,
    trend_probability_bucket_diagnostics,
)
from daily_bias_engine.features import factor_logic_rows
from daily_bias_engine.pipeline import (
    SnapshotInfo,
    list_snapshots,
    run_pipeline_from_snapshot,
)
from daily_bias_engine.options.reports.daily_option_state import generate_daily_option_state

CONFIG_DIR = PROJECT_ROOT / "configs"
SNAPSHOT_ROOT = PROJECT_ROOT / "data" / "snapshots"
OPTION_DATA_ROOT = PROJECT_ROOT / "data" / "options_ifind"


def run_dashboard_pipeline(snapshot_dir: str | Path | None = None) -> dict[str, Any]:
    """Run the dashboard pipeline from a local market-data snapshot."""

    if snapshot_dir is None:
        snapshots = list_snapshots(SNAPSHOT_ROOT)
        if not snapshots:
            raise FileNotFoundError(f"No local market snapshot found under {SNAPSHOT_ROOT}.")
        snapshot_dir = snapshots[0].path
    return run_pipeline_from_snapshot(snapshot_dir=snapshot_dir, config_dir=CONFIG_DIR)


@st.cache_data(show_spinner="Loading local market snapshot...")
def _cached_dashboard_result(snapshot_dir: str | None) -> dict[str, Any]:
    return run_dashboard_pipeline(snapshot_dir=snapshot_dir)


@st.cache_data(show_spinner="Loading local option state...")
def _cached_option_state(product_group: str, trade_date: str, data_root: str) -> tuple[pd.DataFrame, dict[str, Any], dict[str, pd.DataFrame]]:
    factors, payload, _, plots = generate_daily_option_state(
        trade_date,
        product_group,
        data_root=Path(data_root),
        include_markdown=False,
        include_plots=True,
    )
    return factors, payload, plots or {}



def main() -> None:
    st.set_page_config(page_title="市场风向机", layout="wide")
    st.title("市场风向机 / Daily Bias Engine")

    snapshots = list_snapshots(SNAPSHOT_ROOT)
    snapshot_info = snapshots[0] if snapshots else None
    result, data_warning = _load_dashboard_data(snapshot_info)
    if result is None:
        st.error(data_warning)
        st.stop()
    scores = result["scores"].copy()
    labels = result["labels"].copy()
    factors = result["factors"].copy()
    metrics = result["metrics"]
    if data_warning:
        st.warning(data_warning)

    signal_dates = _date_options(scores)
    if not signal_dates:
        st.error("当前数据没有可展示的信号日期。")
        return

    selected_date = st.selectbox("选择信号日期", signal_dates, index=len(signal_dates) - 1)
    selected_row = _selected_engine_row(scores, selected_date)
    selected_explanation = selected_row.get("explanation", {}) if selected_row else {}
    selected_label = _selected_label_row(labels, selected_date)
    selected_factors = _factor_rows_for_date(factors, selected_date)

    st.caption(_data_status_text(result, snapshot_info, scores))

    overview, factors_tab, engine_tab, labels_tab, backtest_tab, backtest_diagnostics_tab, factor_diagnostics_tab, options_tab, logic_tab = st.tabs(
        ["Overview", "Factors", "Engine", "Labels", "Backtest", "Backtest Diagnostics", "Factor Diagnostics", "Options", "Logic"]
    )

    with overview:
        columns = st.columns(6)
        columns[0].metric("信号日期", selected_date)
        columns[1].metric("市场风向", _bias_label(selected_row.get("bias_label") if selected_row else None))
        columns[2].metric("总分", _format_float(selected_row.get("total_score") if selected_row else None))
        columns[3].metric("趋势日概率", f"{_format_float(selected_row.get('trend_day_probability') if selected_row else None)}%")
        columns[4].metric("趋势方向", _trend_label(selected_row.get("trend_direction_bias") if selected_row else None))
        columns[5].metric("置信度", f"{_format_float(selected_row.get('confidence') if selected_row else None)}%")

        st.subheader("每日环境卡片")
        st.write(_trading_posture(selected_row))

        override = _override_summary_table(selected_row)
        if not override.empty:
            st.subheader("风险覆盖")
            st.dataframe(override, width="stretch", hide_index=True)

        label_text = _label_summary_text(selected_label)
        if label_text:
            st.caption(label_text)

        driver_columns = st.columns(2)
        with driver_columns[0]:
            st.subheader("正向驱动")
            st.dataframe(_drivers_table(selected_explanation.get("positive_drivers", [])), width="stretch", hide_index=True)
        with driver_columns[1]:
            st.subheader("负向驱动")
            st.dataframe(_drivers_table(selected_explanation.get("negative_drivers", [])), width="stretch", hide_index=True)

        st.subheader("风险硬标记")
        risk_flags = selected_row.get("risk_flags_json", []) if selected_row else []
        if risk_flags:
            st.dataframe(_risk_flags_table(risk_flags), width="stretch", hide_index=True)
        else:
            st.write("无")

    with factors_tab:
        st.subheader(f"{selected_date} 信号使用的因子")
        st.dataframe(_factor_display_table(selected_factors), width="stretch", hide_index=True)
        with st.expander("查看全部三年因子明细"):
            st.dataframe(_factor_display_table(factors), width="stretch", hide_index=True)

    with engine_tab:
        st.subheader("每日信号总览")
        st.dataframe(_engine_summary_table(scores), width="stretch", hide_index=True)

        st.subheader(f"{selected_date} 引擎解释")
        detail_columns = st.columns(5)
        detail_columns[0].metric("市场风向", _bias_label(selected_row.get("bias_label") if selected_row else None))
        detail_columns[1].metric("总分", _format_float(selected_row.get("total_score") if selected_row else None))
        detail_columns[2].metric("趋势日概率", f"{_format_float(selected_row.get('trend_day_probability') if selected_row else None)}%")
        detail_columns[3].metric("趋势方向", _trend_label(selected_row.get("trend_direction_bias") if selected_row else None))
        detail_columns[4].metric("置信度", f"{_format_float(selected_row.get('confidence') if selected_row else None)}%")

        st.subheader("分项分")
        st.dataframe(_sub_scores_table(selected_row.get("sub_scores", {}) if selected_row else {}), width="stretch", hide_index=True)

        st.subheader("风险硬标记")
        risk_flags = selected_row.get("risk_flags_json", []) if selected_row else []
        if risk_flags:
            st.dataframe(_risk_flags_table(risk_flags), width="stretch", hide_index=True)
        else:
            st.write("无风险硬标记。")

        driver_columns = st.columns(2)
        with driver_columns[0]:
            st.subheader("正向驱动")
            st.dataframe(_drivers_table(selected_explanation.get("positive_drivers", [])), width="stretch", hide_index=True)
        with driver_columns[1]:
            st.subheader("负向驱动")
            st.dataframe(_drivers_table(selected_explanation.get("negative_drivers", [])), width="stretch", hide_index=True)

        st.subheader("全部因子贡献")
        st.dataframe(_factor_contribution_table(selected_explanation.get("factors", [])), width="stretch", hide_index=True)

    with labels_tab:
        st.markdown(
            """
            `标签` 是收盘后的市场结果，用来评价开盘前信号有没有提前识别环境。
            它不是预测信号。比如某天被标为 `down_trend_day_flag` 和 `big_loss_day_flag`，
            说明当天实际走势符合“下跌趋势日/大亏日”的定义。
            """
        )
        if selected_label:
            st.subheader(f"{selected_date} 收盘后标签")
            st.dataframe(_label_display_table(pd.DataFrame([selected_label])), width="stretch", hide_index=True)
        else:
            st.info(f"{selected_date} 还没有对应的收盘后标签。最近一个信号日通常是下一交易日开盘前信号。")
        st.subheader("全部标签")
        st.dataframe(_label_display_table(labels), width="stretch", hide_index=True)

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
        st.dataframe(_metrics_explanation_table(metrics), width="stretch", hide_index=True)

        st.subheader("逐日复盘")
        st.dataframe(_backtest_review_table(scores, labels), width="stretch", hide_index=True)

    with backtest_diagnostics_tab:
        st.subheader("按最终风向分组")
        st.caption("这些统计只把开盘前信号与同一信号日收盘后的 realized label 对齐，不会回灌到因子生成。")
        st.dataframe(_bias_diagnostics_table(bias_return_diagnostics(scores, labels)), width="stretch", hide_index=True)

        st.subheader("总分分桶")
        st.dataframe(_score_bucket_table(score_bucket_diagnostics(scores, labels)), width="stretch", hide_index=True)

        st.subheader("趋势概率分桶")
        st.dataframe(
            _trend_probability_bucket_table(trend_probability_bucket_diagnostics(scores, labels)),
            width="stretch",
            hide_index=True,
        )

    with factor_diagnostics_tab:
        diagnostics = factor_diagnostics(factors, labels)
        factor_summary = diagnostics["summary"]
        quintiles = diagnostics["quintiles"]

        st.subheader("因子诊断")
        sort_mode = st.selectbox(
            "排序方式",
            ["大亏识别最强", "方向收益关系最强", "关系最弱或反向"],
        )
        st.dataframe(_factor_diagnostics_table(factor_summary, sort_mode), width="stretch", hide_index=True)

        factor_options = sorted(quintiles["factor_name"].dropna().unique().tolist()) if not quintiles.empty else []
        if factor_options:
            selected_factor = st.selectbox("查看五分位表现", factor_options)
            st.dataframe(_factor_quintile_table(quintiles, selected_factor), width="stretch", hide_index=True)
        else:
            st.info("当前没有足够数据生成因子五分位表现。")

    with options_tab:
        _render_options_tab(_available_option_snapshots())

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
        st.dataframe(pd.DataFrame(factor_logic_rows()), width="stretch")


def _available_option_snapshots(data_root: Path | str = OPTION_DATA_ROOT) -> dict[str, list[str]]:
    normalized_root = Path(data_root) / "normalized_chain"
    if not normalized_root.exists():
        return {}

    snapshots: dict[str, list[str]] = {}
    for product_dir in sorted(normalized_root.glob("product_group=*")):
        if not product_dir.is_dir():
            continue
        product_group = product_dir.name.split("=", 1)[-1].upper()
        dates = []
        for date_dir in sorted(product_dir.glob("trade_date=*")):
            if (date_dir / "data.parquet").exists():
                dates.append(date_dir.name.split("=", 1)[-1])
        if dates:
            snapshots[product_group] = sorted(dates)
    return snapshots


def _render_options_tab(option_snapshots: dict[str, list[str]]) -> None:
    st.subheader("Local Option State")
    st.caption(f"Source: iFinD local option chains at {OPTION_DATA_ROOT / 'normalized_chain'}")
    if not option_snapshots:
        st.info(
            "No local option snapshots found. Run "
            "`python scripts/fetch_ifind_options_snapshot.py --date YYYY-MM-DD --product CSI300 --data-root data/options_ifind` first."
        )
        return

    products = sorted(option_snapshots)
    default_product = products.index("CSI300") if "CSI300" in products else 0
    controls = st.columns([1, 1, 2])
    with controls[0]:
        product_group = st.selectbox("Option product", products, index=default_product)
    dates = option_snapshots.get(product_group, [])
    with controls[1]:
        trade_date = st.selectbox("Trade date", dates, index=len(dates) - 1)

    try:
        factors, payload, plots = _cached_option_state(product_group, trade_date, str(OPTION_DATA_ROOT))
    except Exception as exc:
        st.error(f"Local option state failed: {exc}")
        return

    overlay = payload.get("recommended_overlay", {})
    metric_columns = st.columns(6)
    metric_columns[0].metric("Regime", str(payload.get("regime", "N/A")))
    metric_columns[1].metric("Direction", _format_float(payload.get("option_direction_score")))
    metric_columns[2].metric("Risk", _format_float(payload.get("option_risk_score")))
    metric_columns[3].metric("Vol carry", _format_float(payload.get("vol_carry_score")))
    metric_columns[4].metric("Tail risk", _format_float(payload.get("tail_risk_score")))
    metric_columns[5].metric("Beta x", _format_float(overlay.get("beta_multiplier")))

    st.caption(str(payload.get("explanation", "")))

    summary_columns = st.columns(3)
    with summary_columns[0]:
        st.subheader("Key Levels")
        st.dataframe(_option_payload_table(payload.get("key_levels", {})), width="stretch", hide_index=True)
    with summary_columns[1]:
        st.subheader("Exposures")
        st.dataframe(_option_payload_table(payload.get("exposures", {})), width="stretch", hide_index=True)
    with summary_columns[2]:
        st.subheader("Vol / Skew")
        vol_skew = {**payload.get("vol", {}), **payload.get("skew", {})}
        st.dataframe(_option_payload_table(vol_skew), width="stretch", hide_index=True)

    overlay_table = _option_payload_table(
        {
            "allow_short_vol": overlay.get("allow_short_vol"),
            "prefer_option_structure": overlay.get("prefer_option_structure"),
        }
    )
    st.subheader("Recommended Overlay")
    st.dataframe(overlay_table, width="stretch", hide_index=True)

    st.subheader("Option Factor Row")
    st.dataframe(_option_factor_table(factors), width="stretch", hide_index=True)

    chart_columns = st.columns(2)
    with chart_columns[0]:
        _render_option_chart("GEX By Strike", plots.get("gex_by_strike"), x_column="strike", y_column="gamma_exposure_1pct", chart="bar")
    with chart_columns[1]:
        _render_option_chart("Spot Grid GEX", plots.get("spot_grid_gex"), x_column="spot", y_column="gamma_exposure_1pct", chart="line")

    chart_columns = st.columns(2)
    with chart_columns[0]:
        _render_option_chart("IV Term Structure", plots.get("iv_term_structure"), x_column="tenor_days", y_column="atm_iv", chart="line")
    with chart_columns[1]:
        _render_option_chart("Skew Curve", plots.get("skew_curve"), x_column="point", y_column="iv", chart="line")


def _option_payload_table(values: dict[str, Any]) -> pd.DataFrame:
    rows = [{"Metric": key, "Value": _option_display_value(value)} for key, value in values.items()]
    return pd.DataFrame(rows)


def _option_display_value(value: Any) -> str:
    if value is None or (not isinstance(value, bool) and pd.isna(value)):
        return "N/A"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{float(value):,.3f}"
    return str(value)


def _option_factor_table(factors: pd.DataFrame) -> pd.DataFrame:
    if factors.empty:
        return pd.DataFrame()
    columns = [
        "date",
        "product_group",
        "spot",
        "gex_z",
        "vanna_z",
        "charm_z",
        "iv_30d",
        "iv_30d_change",
        "put_skew_25d",
        "risk_reversal_25d",
        "regime",
        "option_direction_score",
        "option_risk_score",
        "recommended_beta_multiplier",
        "allow_short_vol",
        "prefer_option_structure",
    ]
    existing = [column for column in columns if column in factors.columns]
    table = factors[existing].copy()
    for column in ("date", "data_date"):
        if column in table.columns:
            table[column] = pd.to_datetime(table[column]).dt.strftime("%Y-%m-%d")
    return _round_numeric(table)


def _render_option_chart(
    title: str,
    frame: pd.DataFrame | None,
    *,
    x_column: str,
    y_column: str,
    chart: str,
) -> None:
    st.subheader(title)
    if frame is None or frame.empty or x_column not in frame.columns or y_column not in frame.columns:
        st.info("No local plot data available.")
        return

    chart_data = frame[[x_column, y_column]].dropna().copy()
    if chart_data.empty:
        st.info("No local plot data available.")
        return
    chart_data = chart_data.set_index(x_column)
    if chart == "bar":
        st.bar_chart(chart_data)
    else:
        st.line_chart(chart_data)
    with st.expander(f"{title} data"):
        st.dataframe(_round_numeric(frame), width="stretch", hide_index=True)


def _load_dashboard_data(snapshot_info: SnapshotInfo | None) -> tuple[dict[str, Any] | None, str]:
    if snapshot_info is None:
        return None, f"No local market snapshot found under {SNAPSHOT_ROOT}. Run `python scripts/fetch_ifind_snapshot.py` first."
    try:
        result = _cached_dashboard_result(str(snapshot_info.path))
        return result, ""
    except Exception as exc:
        return None, f"Local market snapshot read failed: {exc}"



def _data_status_text(result: dict[str, Any], snapshot_info: SnapshotInfo | None, scores: pd.DataFrame) -> str:
    dates = pd.to_datetime(scores["date"]).dt.strftime("%Y-%m-%d")
    signal_range = f"{dates.min()} 至 {dates.max()}" if not dates.empty else "N/A"
    base = (
        f"当前数据源：{_data_mode_label(result.get('data_mode', 'snapshot'))} | "
        f"信号日期范围：{signal_range} | "
        f"信号日数量：{len(scores)}"
    )
    if snapshot_info is None:
        return f"{base} | 页面自动使用三年默认区间"
    return (
        f"{base} | 自动读取最新快照：{snapshot_info.source} "
        f"{snapshot_info.start_date} 至 {snapshot_info.end_date} | "
        f"生成时间：{snapshot_info.created_at}"
    )


def _selected_label_row(labels: pd.DataFrame, selected_date: str) -> dict[str, Any]:
    if labels.empty:
        return {}
    prepared = labels.copy()
    prepared["date_label"] = pd.to_datetime(prepared["date"]).dt.strftime("%Y-%m-%d")
    matched = prepared[prepared["date_label"] == selected_date]
    if matched.empty:
        return {}
    return matched.iloc[0].drop(labels=["date_label"]).to_dict()


def _factor_rows_for_date(factors: pd.DataFrame, selected_date: str) -> pd.DataFrame:
    if factors.empty:
        return factors.copy()
    prepared = factors.copy()
    prepared["date_label"] = pd.to_datetime(prepared["date"]).dt.strftime("%Y-%m-%d")
    return prepared[prepared["date_label"] == selected_date].drop(columns=["date_label"])


def _factor_display_table(factors: pd.DataFrame) -> pd.DataFrame:
    columns = ["信号日期", "数据日期", "因子", "模块", "数据源", "原始值", "z-score", "方向分", "可用时间"]
    if factors.empty:
        return pd.DataFrame(columns=columns)
    logic_groups = {row["factor_name"]: row["group"] for row in factor_logic_rows()}
    table = factors.copy()
    table["group"] = table["factor_name"].map(logic_groups).fillna("未分组")
    if "data_source" not in table.columns:
        table["data_source"] = ""
    table["date"] = pd.to_datetime(table["date"]).dt.strftime("%Y-%m-%d")
    table["data_date"] = pd.to_datetime(table["data_date"]).dt.strftime("%Y-%m-%d")
    table = table.rename(
        columns={
            "date": "信号日期",
            "data_date": "数据日期",
            "factor_name": "因子",
            "group": "模块",
            "data_source": "数据源",
            "raw_value": "原始值",
            "zscore_value": "z-score",
            "directional_score": "方向分",
            "asof_time": "可用时间",
        }
    )
    return _round_numeric(table[columns].sort_values(["信号日期", "模块", "因子"]))


def _label_display_table(labels: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "日期",
        "市场收益",
        "开收盘方向",
        "日内振幅",
        "实体占比",
        "收盘位置",
        "趋势日",
        "上行趋势日",
        "下行趋势日",
        "大亏日",
        "震荡日",
    ]
    if labels.empty:
        return pd.DataFrame(columns=columns)
    table = labels.copy()
    table["date"] = pd.to_datetime(table["date"]).dt.strftime("%Y-%m-%d")
    table["open_close_direction"] = table["open_close_direction"].map(_direction_label)
    table = table.rename(
        columns={
            "date": "日期",
            "market_return": "市场收益",
            "open_close_direction": "开收盘方向",
            "intraday_range": "日内振幅",
            "body_ratio": "实体占比",
            "close_location": "收盘位置",
            "trend_day_flag": "趋势日",
            "up_trend_day_flag": "上行趋势日",
            "down_trend_day_flag": "下行趋势日",
            "big_loss_day_flag": "大亏日",
            "choppy_day_flag": "震荡日",
        }
    )
    return _round_numeric(table[columns].sort_values("日期", ascending=False))


def _label_summary_text(label: dict[str, Any]) -> str:
    if not label:
        return "该信号日尚无收盘后结果标签。"
    tags = []
    if bool(label.get("trend_day_flag")):
        tags.append("趋势日")
    if bool(label.get("up_trend_day_flag")):
        tags.append("上行趋势日")
    if bool(label.get("down_trend_day_flag")):
        tags.append("下行趋势日")
    if bool(label.get("big_loss_day_flag")):
        tags.append("大亏日")
    if bool(label.get("choppy_day_flag")):
        tags.append("震荡日")
    tag_text = "、".join(tags) if tags else "普通交易日"
    return f"收盘后结果：{tag_text}；市场收益 {_format_percent(label.get('market_return'))}。"


def _override_summary_table(row: dict[str, Any]) -> pd.DataFrame:
    if not row:
        return pd.DataFrame()
    raw_bias = row.get("raw_score_bias") or _raw_score_bias(row.get("total_score"))
    final_bias = row.get("final_bias") or row.get("bias_label")
    risk_override = row.get("risk_override") or ""
    if raw_bias == final_bias or not risk_override:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "Raw Score Bias": _bias_label(raw_bias),
                "Risk Override": risk_override,
                "Final Bias": _bias_label(final_bias),
                "Override Reason": row.get("override_reason") or _override_reason_from_flags(row.get("risk_flags_json", [])),
            }
        ]
    )


def _bias_diagnostics_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=["最终风向", "样本数", "平均收益", "中位数收益", "胜率", "大涨日率", "大亏日率", "趋势日率", "最大亏损"]
        )
    table = frame.copy()
    table["final_bias"] = table["final_bias"].map(_bias_label)
    table = _format_diagnostic_percentages(table)
    return table.rename(
        columns={
            "final_bias": "最终风向",
            "sample_count": "样本数",
            "mean_market_return": "平均收益",
            "median_market_return": "中位数收益",
            "win_rate": "胜率",
            "big_up_day_rate": "大涨日率",
            "big_loss_day_rate": "大亏日率",
            "trend_day_rate": "趋势日率",
            "max_loss": "最大亏损",
        }
    )


def _score_bucket_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=["总分区间", "样本数", "平均收益", "中位数收益", "胜率", "大涨日率", "大亏日率", "趋势日率", "最大亏损"]
        )
    table = _format_diagnostic_percentages(frame.copy())
    return table.rename(
        columns={
            "score_bucket": "总分区间",
            "sample_count": "样本数",
            "mean_market_return": "平均收益",
            "median_market_return": "中位数收益",
            "win_rate": "胜率",
            "big_up_day_rate": "大涨日率",
            "big_loss_day_rate": "大亏日率",
            "trend_day_rate": "趋势日率",
            "max_loss": "最大亏损",
        }
    )


def _trend_probability_bucket_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["趋势概率区间", "样本数", "实际趋势日率"])
    table = frame.copy()
    table["actual_trend_day_rate"] = table["actual_trend_day_rate"].map(_format_percent)
    return table.rename(
        columns={
            "trend_probability_bucket": "趋势概率区间",
            "sample_count": "样本数",
            "actual_trend_day_rate": "实际趋势日率",
        }
    )


def _factor_diagnostics_table(frame: pd.DataFrame, sort_mode: str) -> pd.DataFrame:
    columns = [
        "因子",
        "样本数",
        "平均方向分",
        "收益相关性",
        "大亏相关性",
        "趋势日相关性",
        "大亏识别分",
        "方向关系强度",
        "近60日收益相关",
        "近120日收益相关",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    table = frame.copy()
    if sort_mode == "方向收益关系最强":
        table = table.sort_values("directional_relationship_strength", ascending=False)
    elif sort_mode == "关系最弱或反向":
        table = table.assign(_weakness=table["directional_relationship_strength"].abs()).sort_values(
            ["corr_next_market_return", "_weakness"],
            ascending=[True, True],
        )
    else:
        table = table.sort_values("big_loss_detection_score", ascending=False)
    table = table.drop(columns=["_weakness"], errors="ignore")
    table = table.rename(
        columns={
            "factor_name": "因子",
            "sample_count": "样本数",
            "mean_directional_score": "平均方向分",
            "corr_next_market_return": "收益相关性",
            "corr_big_loss_day_flag": "大亏相关性",
            "corr_trend_day_flag": "趋势日相关性",
            "big_loss_detection_score": "大亏识别分",
            "directional_relationship_strength": "方向关系强度",
            "recent_60d_corr_return": "近60日收益相关",
            "recent_120d_corr_return": "近120日收益相关",
        }
    )
    return _round_numeric(table[columns])


def _factor_quintile_table(quintiles: pd.DataFrame, factor_name: str) -> pd.DataFrame:
    table = quintiles[quintiles["factor_name"] == factor_name].copy()
    if table.empty:
        return pd.DataFrame(columns=["因子", "五分位", "样本数", "平均次日/当日市场收益", "大亏日率"])
    table["avg_next_market_return"] = table["avg_next_market_return"].map(_format_percent)
    table["big_loss_day_rate"] = table["big_loss_day_rate"].map(_format_percent)
    return table.rename(
        columns={
            "factor_name": "因子",
            "factor_quintile": "五分位",
            "sample_count": "样本数",
            "avg_next_market_return": "平均次日/当日市场收益",
            "big_loss_day_rate": "大亏日率",
        }
    )


def _format_diagnostic_percentages(table: pd.DataFrame) -> pd.DataFrame:
    output = table.copy()
    percentage_columns = [
        "mean_market_return",
        "median_market_return",
        "win_rate",
        "big_up_day_rate",
        "big_loss_day_rate",
        "trend_day_rate",
        "max_loss",
    ]
    for column in percentage_columns:
        if column in output.columns:
            output[column] = output[column].map(_format_percent)
    return output


def _engine_summary_table(scores: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "date",
        "raw_score_bias",
        "final_bias",
        "bias_label",
        "risk_override",
        "total_score",
        "confidence",
        "trend_day_probability",
        "trend_direction_bias",
    ]
    existing = [column for column in columns if column in scores.columns]
    table = scores[existing].copy()
    if "raw_score_bias" not in table.columns:
        table["raw_score_bias"] = table["total_score"].map(_raw_score_bias)
    if "final_bias" not in table.columns:
        table["final_bias"] = table["bias_label"]
    if "risk_override" not in table.columns:
        table["risk_override"] = ""
    table["date"] = pd.to_datetime(table["date"]).dt.strftime("%Y-%m-%d")
    table["raw_score_bias"] = table["raw_score_bias"].map(_bias_label)
    table["final_bias"] = table["final_bias"].map(_bias_label)
    table["trend_direction_bias"] = table["trend_direction_bias"].map(_trend_label)
    table["risk_override"] = table["risk_override"].replace("", "无")
    table = table.rename(
        columns={
            "date": "信号日期",
            "raw_score_bias": "原始分数风向",
            "final_bias": "最终风向",
            "risk_override": "风险覆盖",
            "total_score": "总分",
            "confidence": "置信度",
            "trend_day_probability": "趋势日概率",
            "trend_direction_bias": "趋势方向",
        }
    )
    table = table.drop(columns=["bias_label"], errors="ignore")
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
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value) * 100:.1f}%"


def _format_float(value: Any) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):.3f}"


def _trading_posture(latest: dict[str, Any]) -> str:
    label = latest.get("final_bias") or latest.get("bias_label")
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


def _raw_score_bias(total_score: Any) -> str:
    score = float(total_score or 0.0)
    if score >= 30:
        return "Risk-On"
    if score <= -30:
        return "Risk-Off"
    return "Neutral"


def _override_reason_from_flags(risk_flags: list[dict[str, Any]]) -> str:
    if not risk_flags:
        return ""
    reasons = []
    for flag in risk_flags:
        factor_name = flag.get("factor_name", "unknown_factor")
        factor_score = _format_float(flag.get("factor_score"))
        threshold = _format_float(flag.get("threshold"))
        reasons.append(f"{factor_name} crossed hard Risk-Off threshold ({factor_score} <= {threshold})")
    return "; ".join(reasons)


def _trend_label(value: Any) -> str:
    labels = {
        "up": "上行",
        "down": "下行",
        "unclear": "不明确",
    }
    return labels.get(str(value), "N/A")


def _direction_label(value: Any) -> str:
    labels = {
        "up": "上行",
        "down": "下行",
        "flat": "平盘",
    }
    return labels.get(str(value), str(value))


def _data_mode_label(value: str) -> str:
    labels = {
        "snapshot": "Local market snapshot",
        "wind": "Localized Wind data",
        "ifind": "Localized iFinD data",
    }
    return labels.get(value, value)



if __name__ == "__main__":
    main()
