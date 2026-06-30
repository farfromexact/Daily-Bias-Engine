"""Streamlit dashboard for the Daily Bias Engine."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Mapping

import numpy as np
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
WEIGHT_REPORT_ROOT = PROJECT_ROOT / "reports" / "weight_optimizer"
LIQUIDITY_AVAILABILITY_PATH = PROJECT_ROOT / "data" / "liquidity_data_availability.csv"
LIQUIDITY_RAW_PANEL_PATH = PROJECT_ROOT / "data" / "liquidity_raw_panel.csv"
LIQUIDITY_CHART_ROOT = PROJECT_ROOT / "data" / "liquidity_charts"

APP_USAGE_GUIDE = """
### 这个系统是什么

Daily Bias Engine 是一个盘前市场风向仪。它不直接给交易指令，而是把多个已经本地化的真实市场数据因子合成一个“今天适合偏进攻、等待、还是防守”的环境判断。

### 每天应该先看什么

1. 先看 Overview 顶部六个指标：信号日期、市场风向、总分、趋势日概率、趋势方向、置信度。
2. 再看“每日环境卡片”：这是把数字翻译成人话后的当天摘要。
3. 如果风向或总分看起来反直觉，去看“正向驱动 / 负向驱动”，它会告诉你今天主要是谁在拉高或压低总分。
4. 如果最终风向被风险覆盖改写，优先看“风险硬标记”。硬风险会覆盖普通加权分数。
5. 想知道系统为什么长期有效或失效，去 Backtest、Backtest Diagnostics、Factor Diagnostics。
6. 想看期权链和 Gamma/Vol 结构，去 Options；想看权重优化研究，去 Weight Diagnostics。

### 信号日期和数据日期的关系

信号日期通常是“下一交易日开盘前要看的日期”。系统只使用这个信号日前已经可见的数据。比如 2026-06-16 的信号，通常使用 2026-06-15 收盘后已经落地的数据。表格里的 data_date 必须早于或等于可见数据日，不能偷看信号日之后的结果。

### 分数怎么理解

每个因子先算原始值，再转成 z-score，再映射为 directional_score，最后乘以权重贡献到总分。总分大致可理解为：

- 大幅正数：环境偏 Risk-On，适合更积极地寻找多头/趋势机会。
- 接近 0：环境不明确，系统建议等待或降低交易频率。
- 大幅负数：环境偏 Risk-Off，优先防守和控制回撤。

这不是收益预测的保证。它是环境过滤器，目的是减少在差环境里过度出手。

### 为什么有些数据看起来是 proxy

系统使用的底层数据是真实 iFinD 本地数据，但有些因子本身是 proxy。例如 ETF 成交额用于近似 ETF 资金流，A 股宽度用 50、300、科创、创业板指数涨跌来近似市场广度。proxy 的含义是“因子口径是替代变量”，不是假数据。
"""

HELP_TEXT = {
    "signal_date_select": "选择要查看的信号日期。信号日期不是原始行情日期，而是系统给出盘前判断的日期；它通常使用前一交易日收盘后已经可见的数据。",
    "metric_signal_date": "当前展示的盘前信号日期。比如 2026-06-16 表示这是给 2026-06-16 交易日使用的环境判断。",
    "metric_market_bias": "最终市场风向。Risk-On 表示环境偏进攻；Neutral 表示等待或轻仓观察；Risk-Off 表示防守优先。最终风向可能被风险硬标记覆盖。",
    "metric_total_score": "所有因子按配置权重加权后的总分。正数偏多，负数偏空，接近 0 表示信号不强。它不是收益率预测，而是环境分数。",
    "metric_trend_probability": "系统估计当天出现趋势日的概率。趋势日指市场更可能单边扩展，而不是窄幅震荡。概率高不代表方向确定，还要结合趋势方向。",
    "metric_trend_direction": "系统根据标签和因子结构估计的趋势方向：上行、下行或不明确。方向不明确时，即使趋势概率较高，也不应直接理解为单边看多或看空。",
    "metric_confidence": "置信度来自总分强度和风险覆盖后的综合结果。置信度高表示系统当前判断更集中；置信度低表示因子分歧较大或总分接近中性。",
    "metric_observations": "参与回测评估的历史样本天数。样本越多，统计结果越稳定；但市场结构变化也会让很久以前的样本参考价值下降。",
    "metric_bias_accuracy": "方向命中率衡量 Risk-On 后市场上涨、Risk-Off 后市场下跌、Neutral 后市场相对平稳的比例。它不是单笔交易胜率。",
    "metric_trend_precision": "趋势日 precision 表示系统认为趋势概率较高的日子里，有多少最终真的成为趋势日。它衡量信号发出后的准确性。",
    "metric_trend_recall": "趋势日 recall 表示所有真实趋势日里，系统提前识别到了多少。它衡量系统漏掉趋势日的程度。",
    "metric_big_loss_filter": "大亏日过滤率衡量系统在历史大亏日之前或当天给出防守提示的能力。它越高，说明风控过滤越有效。",
    "metric_false_risk_off": "Risk-Off 误伤率衡量系统提示防守但市场并未走坏的比例。误伤率太高会错过机会，太低可能说明保护不足。",
    "section_daily_card": "每日环境卡片把总分、趋势概率、风险覆盖和主要驱动翻译成一句操作语境。它适合做当天第一眼的环境摘要。",
    "section_risk_override": "风险覆盖表示某些硬风险条件触发后，系统会把普通加权分数降级。它用于避免总分还可以、但底层风险已经恶化的情况。",
    "section_positive_drivers": "正向驱动列出今天贡献最高的多头或 Risk-On 因子。贡献值等于因子分数乘以权重。",
    "section_negative_drivers": "负向驱动列出今天拖累总分的因子。它帮助判断是利率、海外、期货结构、资金流还是 A 股结构在压制环境。",
    "section_hard_risk": "风险硬标记是比普通加权更强的保护规则。如果某个因子跌破硬风险阈值，最终风向可能被强制转为 Risk-Off。",
    "section_selected_factors": "这里展示当前信号日期实际用到的全部因子行，包括原始值、z-score、方向分、数据日期和可用时间。",
    "section_all_factor_history": "全历史因子明细用于审计和排查。它不是每天必须看的表，主要用来确认某个因子在历史上怎么变化。",
    "section_engine_summary": "每日信号总览列出历史每一天的原始风向、最终风向、风险覆盖、总分、置信度和趋势判断。",
    "section_engine_explain": "引擎解释展示某一天的完整拆解：分项分、风险标记、驱动因子和全部因子贡献。",
    "section_sub_scores": "分项分按模块聚合，例如海外、期货、ETF/融资、A 股结构、利率债券。它能告诉你今天的总分主要来自哪个模块。",
    "section_factor_contribution": "全部因子贡献展示每个因子的方向分、权重和最终贡献。贡献加总后形成总分，再经过风险规则得到最终风向。",
    "section_labels": "标签是收盘后才能知道的真实市场结果，用来评估盘前信号，不参与当天盘前判断。",
    "section_backtest_summary": "回测摘要把历史信号和之后真实标签对齐，评估方向命中率、趋势日识别、亏损日过滤和误伤情况。",
    "section_metrics_explain": "指标解释把回测里的专业指标翻译成普通语言。新用户应先看这一块再读详细表格。",
    "section_daily_review": "逐日复盘逐天列出信号和结果，适合检查某段时间为什么命中或失效。",
    "section_bias_diagnostics": "按最终风向分组统计不同风向后的平均收益、胜率、趋势日率和最大亏损，用于判断风向标签是否有区分度。",
    "section_score_bucket": "总分分桶把历史总分分成区间，观察高分、低分和中性分数后的真实市场表现。",
    "section_trend_bucket": "趋势概率分桶检查系统给出的趋势概率是否和真实趋势日发生率一致。",
    "section_factor_diagnostics": "因子诊断从历史角度检查每个因子和后续收益、亏损日、趋势日的关系。它是研究工具，不是当天交易指令。",
    "factor_sort_mode": "选择因子诊断表的排序口径：按亏损识别能力、方向收益关系，或寻找关系弱/反向的因子。",
    "factor_quintile": "查看单个因子分成五档后，后续市场表现是否有单调性。它用于判断因子有没有稳定区分度。",
    "section_logic": "Logic 页解释系统如何从真实数据生成因子、因子如何变成方向分、方向分如何合成总分。",
    "section_options": "Options 页读取本地 iFinD 期权链，计算关键行权价、GEX、Vanna、Charm、隐波和偏度结构，用于辅助指数风险和波动率判断。",
    "option_product": "选择期权品种：SSE50、CSI300、CSI1000。不同品种对应不同指数和期权链。",
    "option_trade_date": "选择期权链交易日。期权数据必须等 iFinD 有完整当日链和参考收盘价后才能落地。",
    "section_option_key_levels": "关键价位包括现货、put wall、call wall、最大 gamma 行权价等，用于观察期权仓位可能影响的价格区域。",
    "section_option_exposures": "敞口展示 GEX、Vanna、Charm、Vega 等聚合结果。它们衡量做市商对价格、波动率和时间变化的敏感度。",
    "section_option_vol": "波动率和偏度展示 30 日 IV、偏度、风险反转等，用于判断波动率风险溢价和尾部保护需求。",
    "section_option_overlay": "Recommended Overlay 是期权模块给现货/指数 beta 和期权结构的建议倾向。它是风控辅助，不自动覆盖主引擎。",
    "section_option_factor": "Option Factor Row 把期权链压缩成一行可进入模型的因子结果。",
    "metric_option_regime": "期权模块根据 GEX、Vanna、Charm、隐波和偏度综合判断的期权市场状态。",
    "metric_option_direction": "期权链对方向的倾向分。正值偏多，负值偏空；它只反映期权结构，不直接替代主市场风向。",
    "metric_option_risk": "期权链给出的风险分。数值越高，表示期权结构中的尾部或对冲压力越需要关注。",
    "metric_vol_carry": "隐含波动率相对 realized/期限结构的 carry 倾向。它用于判断卖波动或买保护是否更占优。",
    "metric_tail_risk": "尾部风险分，主要来自偏度、风险反转和保护需求。高值表示市场对下行保护需求更强。",
    "metric_beta_multiplier": "期权模块建议的 beta 调整倍数。小于 1 表示降低指数暴露，大于 1 表示期权结构允许更积极。",
    "GEX By Strike": "按行权价汇总的 Gamma Exposure。它帮助观察哪些行权价附近可能存在较强的对冲压力或支撑/压制区域。",
    "Spot Grid GEX": "假设现货价格移动到不同位置时重新估算 GEX，用于观察价格变化后期权仓位对市场的潜在影响。",
    "IV Term Structure": "不同期限的隐含波动率结构。近端高于远端通常表示短期事件或压力溢价较强。",
    "Skew Curve": "不同行权价或 delta 附近的隐含波动率偏斜。偏度越陡，通常说明尾部保护需求越强。",
    "section_weight_diag": "Weight Diagnostics 是权重研究页。它只生成诊断和推荐，不会自动覆盖生产配置。",
    "section_weight_recommendation": "最终推荐说明当前优化权重是否值得进入人工评审。系统不会自动采用任何推荐权重。",
    "section_weight_comparison": "权重对比展示当前权重、优化权重和 blended 权重。blended 是 0.6 当前权重 + 0.4 优化权重，再经过约束投影。",
    "section_constraint_check": "约束检查确认权重是否满足单因子、单模块、利率、ETF+融资、非负等限制。",
    "section_fold_performance": "Fold performance 展示严格时间序列 walk-forward 每一折的训练区间、测试区间和样本外表现。",
    "section_factor_stability": "Factor stability 衡量每个因子的 rolling IC、稳定性排名和权重波动率。稳定性差的因子不应轻易加权。",
    "section_return_bucket": "Return bucket analysis 检查不同分数区间后的次日收益和方向命中情况。",
    "section_risk_bucket": "Risk bucket analysis 检查风险分数高低对大亏损日过滤、误报和漏报的影响。",
    "section_regime_diag": "Regime diagnostics 按趋势、波动率、压力和海外环境分组检查因子表现，防止平均数掩盖不同市场状态。",
    "metric_current_weights": "当前生产配置正在使用的权重。Weight Diagnostics 不会自动修改它。",
    "metric_optimized_weights": "优化器根据历史 walk-forward 诊断得到的研究权重，只用于评估，不代表已经采用。",
    "metric_blended_weights": "候选 blended 权重：0.6 当前权重 + 0.4 优化权重，并经过约束投影。仍需人工批准。",
    "metric_adoption_status": "采用状态。当前系统默认 shadow mode，表示只展示研究结果，不自动覆盖生产配置。",
    "section_liquidity": "Liquidity 页只读取本地 CSV/SVG 文件，不会在 Streamlit 运行时访问 iFinD、Wind、FRED、Yahoo 或其他在线源。",
    "section_liquidity_availability": "数据可得性表记录每个美元流动性指标最终由哪个本地拉数结果支持，以及失败原因。",
    "section_liquidity_panel": "Raw panel 是本地拉取后的宽表。后续部署时把这个 CSV 一起提交到 Git，Streamlit 只负责展示。",
}


def run_dashboard_pipeline(snapshot_dir: str | Path | None = None) -> dict[str, Any]:
    """Run the dashboard pipeline from a local market-data snapshot."""

    if snapshot_dir is None:
        snapshots = list_snapshots(SNAPSHOT_ROOT)
        if not snapshots:
            raise FileNotFoundError(f"No local market snapshot found under {SNAPSHOT_ROOT}.")
        snapshot_dir = snapshots[0].path
    try:
        return _load_dashboard_snapshot_outputs(snapshot_dir)
    except Exception as exc:
        result = run_pipeline_from_snapshot(snapshot_dir=snapshot_dir, config_dir=CONFIG_DIR)
        result["snapshot_load_mode"] = "raw_fallback"
        result["snapshot_load_warning"] = (
            "Precomputed snapshot outputs were unavailable or invalid; "
            f"recalculated from raw snapshot data. Detail: {exc}"
        )
        return result


def _load_dashboard_snapshot_outputs(snapshot_dir: str | Path) -> dict[str, Any]:
    output_dir = Path(snapshot_dir) / "outputs"
    paths = {
        "factors": output_dir / "factor_daily.parquet",
        "scores": output_dir / "bias_daily.parquet",
        "labels": output_dir / "market_result_daily.parquet",
        "metrics": output_dir / "metrics.json",
        "report": output_dir / "report.json",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Snapshot is missing precomputed outputs: {missing}")
    return {
        "factors": pd.read_parquet(paths["factors"]),
        "scores": pd.read_parquet(paths["scores"]),
        "labels": pd.read_parquet(paths["labels"]),
        "metrics": json.loads(paths["metrics"].read_text(encoding="utf-8")),
        "report": json.loads(paths["report"].read_text(encoding="utf-8")),
        "data_mode": "snapshot",
        "raw": {},
        "snapshot_load_mode": "outputs",
    }


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


@st.cache_data(show_spinner="Loading weight diagnostics...")
def _cached_weight_diagnostics(report_path: str, report_mtime_ns: int) -> dict[str, Any]:
    _ = report_mtime_ns
    return json.loads(Path(report_path).read_text(encoding="utf-8"))


@st.cache_data(show_spinner="Loading local liquidity data...")
def _cached_liquidity_data(
    availability_path: str,
    availability_mtime_ns: int,
    raw_panel_path: str,
    raw_panel_mtime_ns: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    _ = (availability_mtime_ns, raw_panel_mtime_ns)
    return _load_liquidity_data(availability_path, raw_panel_path)


def _help_text(key: str) -> str | None:
    return HELP_TEXT.get(key)


def _subheader(label: str, help_key: str | None = None) -> None:
    st.subheader(label, help=_help_text(help_key or label))


def _render_first_time_guide() -> None:
    with st.expander("第一次使用说明：这个系统怎么看", expanded=False):
        st.markdown(APP_USAGE_GUIDE)



def main() -> None:
    st.set_page_config(page_title="市场风向机", layout="wide")
    st.title("市场风向机 / Daily Bias Engine")
    _render_first_time_guide()

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

    latest_signal_date = signal_dates[-1]
    snapshot_key = snapshot_info.path.name if snapshot_info is not None else "no_snapshot"
    selected_date = st.selectbox(
        "选择信号日期",
        signal_dates,
        index=len(signal_dates) - 1,
        key=f"signal_date_{snapshot_key}_{latest_signal_date}",
        help=_help_text("signal_date_select"),
    )
    selected_row = _selected_engine_row(scores, selected_date)
    selected_explanation = selected_row.get("explanation", {}) if selected_row else {}
    selected_label = _selected_label_row(labels, selected_date)
    selected_factors = _factor_rows_for_date(factors, selected_date)

    st.caption(_data_status_text(result, snapshot_info, scores))

    (
        overview,
        factors_tab,
        engine_tab,
        labels_tab,
        backtest_tab,
        backtest_diagnostics_tab,
        factor_diagnostics_tab,
        weight_diag_tab,
        options_tab,
        liquidity_tab,
        logic_tab,
    ) = st.tabs(
        [
            "Overview",
            "Factors",
            "Engine",
            "Labels",
            "Backtest",
            "Backtest Diagnostics",
            "Factor Diagnostics",
            "Weight Diagnostics",
            "Options",
            "Liquidity",
            "Logic",
        ]
    )

    with overview:
        columns = st.columns(6)
        columns[0].metric("信号日期", selected_date, help=_help_text("metric_signal_date"))
        columns[1].metric("市场风向", _bias_label(selected_row.get("bias_label") if selected_row else None), help=_help_text("metric_market_bias"))
        columns[2].metric("总分", _format_float(selected_row.get("total_score") if selected_row else None), help=_help_text("metric_total_score"))
        columns[3].metric(
            "趋势日概率",
            f"{_format_float(selected_row.get('trend_day_probability') if selected_row else None)}%",
            help=_help_text("metric_trend_probability"),
        )
        columns[4].metric("趋势方向", _trend_label(selected_row.get("trend_direction_bias") if selected_row else None), help=_help_text("metric_trend_direction"))
        columns[5].metric("置信度", f"{_format_float(selected_row.get('confidence') if selected_row else None)}%", help=_help_text("metric_confidence"))

        _subheader("每日环境卡片", "section_daily_card")
        st.write(_trading_posture(selected_row))

        override = _override_summary_table(selected_row)
        if not override.empty:
            _subheader("风险覆盖", "section_risk_override")
            st.dataframe(override, width="stretch", hide_index=True)

        label_text = _label_summary_text(selected_label)
        if label_text:
            st.caption(label_text)

        driver_columns = st.columns(2)
        with driver_columns[0]:
            _subheader("正向驱动", "section_positive_drivers")
            st.dataframe(_drivers_table(selected_explanation.get("positive_drivers", [])), width="stretch", hide_index=True)
        with driver_columns[1]:
            _subheader("负向驱动", "section_negative_drivers")
            st.dataframe(_drivers_table(selected_explanation.get("negative_drivers", [])), width="stretch", hide_index=True)

        _subheader("风险硬标记", "section_hard_risk")
        risk_flags = _record_list(selected_row.get("risk_flags_json", [])) if selected_row else []
        if risk_flags:
            st.dataframe(_risk_flags_table(risk_flags), width="stretch", hide_index=True)
        else:
            st.write("无")

    with factors_tab:
        _subheader(f"{selected_date} 信号使用的因子", "section_selected_factors")
        st.dataframe(_factor_display_table(selected_factors), width="stretch", hide_index=True)
        with st.expander("查看全部历史因子明细"):
            st.dataframe(_factor_display_table(factors), width="stretch", hide_index=True)

    with engine_tab:
        _subheader("每日信号总览", "section_engine_summary")
        st.dataframe(_engine_summary_table(scores), width="stretch", hide_index=True)

        _subheader(f"{selected_date} 引擎解释", "section_engine_explain")
        detail_columns = st.columns(5)
        detail_columns[0].metric("市场风向", _bias_label(selected_row.get("bias_label") if selected_row else None), help=_help_text("metric_market_bias"))
        detail_columns[1].metric("总分", _format_float(selected_row.get("total_score") if selected_row else None), help=_help_text("metric_total_score"))
        detail_columns[2].metric(
            "趋势日概率",
            f"{_format_float(selected_row.get('trend_day_probability') if selected_row else None)}%",
            help=_help_text("metric_trend_probability"),
        )
        detail_columns[3].metric("趋势方向", _trend_label(selected_row.get("trend_direction_bias") if selected_row else None), help=_help_text("metric_trend_direction"))
        detail_columns[4].metric("置信度", f"{_format_float(selected_row.get('confidence') if selected_row else None)}%", help=_help_text("metric_confidence"))

        _subheader("分项分", "section_sub_scores")
        st.dataframe(_sub_scores_table(selected_row.get("sub_scores", {}) if selected_row else {}), width="stretch", hide_index=True)

        _subheader("风险硬标记", "section_hard_risk")
        risk_flags = _record_list(selected_row.get("risk_flags_json", [])) if selected_row else []
        if risk_flags:
            st.dataframe(_risk_flags_table(risk_flags), width="stretch", hide_index=True)
        else:
            st.write("无风险硬标记。")

        driver_columns = st.columns(2)
        with driver_columns[0]:
            _subheader("正向驱动", "section_positive_drivers")
            st.dataframe(_drivers_table(selected_explanation.get("positive_drivers", [])), width="stretch", hide_index=True)
        with driver_columns[1]:
            _subheader("负向驱动", "section_negative_drivers")
            st.dataframe(_drivers_table(selected_explanation.get("negative_drivers", [])), width="stretch", hide_index=True)

        _subheader("全部因子贡献", "section_factor_contribution")
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
            _subheader(f"{selected_date} 收盘后标签", "section_labels")
            st.dataframe(_label_display_table(pd.DataFrame([selected_label])), width="stretch", hide_index=True)
        else:
            st.info(f"{selected_date} 还没有对应的收盘后标签。最近一个信号日通常是下一交易日开盘前信号。")
        _subheader("全部标签", "section_labels")
        st.dataframe(_label_display_table(labels), width="stretch", hide_index=True)

    with backtest_tab:
        _subheader("回测摘要", "section_backtest_summary")
        st.markdown(_backtest_plain_language(metrics))
        metric_columns = st.columns(6)
        metric_columns[0].metric("样本天数", str(metrics.get("observations", 0)), help=_help_text("metric_observations"))
        metric_columns[1].metric("方向命中率", _format_percent(metrics.get("bias_accuracy")), help=_help_text("metric_bias_accuracy"))
        metric_columns[2].metric("趋势日 precision", _format_percent(metrics.get("trend_day_precision")), help=_help_text("metric_trend_precision"))
        metric_columns[3].metric("趋势日 recall", _format_percent(metrics.get("trend_day_recall")), help=_help_text("metric_trend_recall"))
        metric_columns[4].metric("大亏日过滤率", _format_percent(metrics.get("big_loss_day_filter_rate")), help=_help_text("metric_big_loss_filter"))
        metric_columns[5].metric("Risk-Off 误伤率", _format_percent(metrics.get("false_risk_off_rate")), help=_help_text("metric_false_risk_off"))

        _subheader("指标解释", "section_metrics_explain")
        st.dataframe(_metrics_explanation_table(metrics), width="stretch", hide_index=True)

        _subheader("逐日复盘", "section_daily_review")
        st.dataframe(_backtest_review_table(scores, labels), width="stretch", hide_index=True)

    with backtest_diagnostics_tab:
        _subheader("按最终风向分组", "section_bias_diagnostics")
        st.caption("这些统计只把开盘前信号与同一信号日收盘后的 realized label 对齐，不会回灌到因子生成。")
        st.dataframe(_bias_diagnostics_table(bias_return_diagnostics(scores, labels)), width="stretch", hide_index=True)

        _subheader("总分分桶", "section_score_bucket")
        st.dataframe(_score_bucket_table(score_bucket_diagnostics(scores, labels)), width="stretch", hide_index=True)

        _subheader("趋势概率分桶", "section_trend_bucket")
        st.dataframe(
            _trend_probability_bucket_table(trend_probability_bucket_diagnostics(scores, labels)),
            width="stretch",
            hide_index=True,
        )

    with factor_diagnostics_tab:
        diagnostics = factor_diagnostics(factors, labels)
        factor_summary = diagnostics["summary"]
        quintiles = diagnostics["quintiles"]

        _subheader("因子诊断", "section_factor_diagnostics")
        sort_mode = st.selectbox(
            "排序方式",
            ["大亏识别最强", "方向收益关系最强", "关系最弱或反向"],
            help=_help_text("factor_sort_mode"),
        )
        st.dataframe(_factor_diagnostics_table(factor_summary, sort_mode), width="stretch", hide_index=True)

        factor_options = sorted(quintiles["factor_name"].dropna().unique().tolist()) if not quintiles.empty else []
        if factor_options:
            selected_factor = st.selectbox("查看五分位表现", factor_options, help=_help_text("factor_quintile"))
            st.dataframe(_factor_quintile_table(quintiles, selected_factor), width="stretch", hide_index=True)
        else:
            st.info("当前没有足够数据生成因子五分位表现。")

    with weight_diag_tab:
        _render_weight_diagnostics_tab()

    with options_tab:
        _render_options_tab(_available_option_snapshots())

    with liquidity_tab:
        _render_liquidity_tab()

    with logic_tab:
        _subheader("系统如何使用这些因子", "section_logic")
        st.markdown(
            """
            当前版本是规则引擎，不是机器学习模型。每个因子先计算原始值，再做 20 日滚动 z-score，
            然后按风险方向映射成 `directional_score`。最终因子得分为 `directional_score * 100`，
            引擎按配置权重加权得到 `-100` 到 `+100` 的总分。

            日收盘数据只生成下一交易日的开盘前信号，因此表里的 `data_date` 必须早于 `date`。

            **注意：当前快照来自真实 iFinD 本地数据。这里的 proxy 通常指“因子口径是替代变量”，
            不是说底层行情是假数据。** 例如 ETF 成交额是真实 iFinD 数据，但它只是 ETF 净申购的
            proxy；指数样本上涨比例是真实 iFinD 价格派生结果，但它只是全市场上涨家数的 proxy。
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
    _subheader("Local Option State", "section_options")
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
        product_group = st.selectbox("Option product", products, index=default_product, help=_help_text("option_product"))
    dates = option_snapshots.get(product_group, [])
    with controls[1]:
        trade_date = st.selectbox("Trade date", dates, index=len(dates) - 1, help=_help_text("option_trade_date"))

    try:
        factors, payload, plots = _cached_option_state(product_group, trade_date, str(OPTION_DATA_ROOT))
    except Exception as exc:
        st.error(f"Local option state failed: {exc}")
        return

    overlay = payload.get("recommended_overlay", {})
    metric_columns = st.columns(6)
    metric_columns[0].metric("Regime", str(payload.get("regime", "N/A")), help=_help_text("metric_option_regime"))
    metric_columns[1].metric("Direction", _format_float(payload.get("option_direction_score")), help=_help_text("metric_option_direction"))
    metric_columns[2].metric("Risk", _format_float(payload.get("option_risk_score")), help=_help_text("metric_option_risk"))
    metric_columns[3].metric("Vol carry", _format_float(payload.get("vol_carry_score")), help=_help_text("metric_vol_carry"))
    metric_columns[4].metric("Tail risk", _format_float(payload.get("tail_risk_score")), help=_help_text("metric_tail_risk"))
    metric_columns[5].metric("Beta x", _format_float(overlay.get("beta_multiplier")), help=_help_text("metric_beta_multiplier"))

    st.caption(str(payload.get("explanation", "")))

    summary_columns = st.columns(3)
    with summary_columns[0]:
        _subheader("Key Levels", "section_option_key_levels")
        st.dataframe(_option_payload_table(payload.get("key_levels", {})), width="stretch", hide_index=True)
    with summary_columns[1]:
        _subheader("Exposures", "section_option_exposures")
        st.dataframe(_option_payload_table(payload.get("exposures", {})), width="stretch", hide_index=True)
    with summary_columns[2]:
        _subheader("Vol / Skew", "section_option_vol")
        vol_skew = {**payload.get("vol", {}), **payload.get("skew", {})}
        st.dataframe(_option_payload_table(vol_skew), width="stretch", hide_index=True)

    overlay_table = _option_payload_table(
        {
            "allow_short_vol": overlay.get("allow_short_vol"),
            "prefer_option_structure": overlay.get("prefer_option_structure"),
        }
    )
    _subheader("Recommended Overlay", "section_option_overlay")
    st.dataframe(overlay_table, width="stretch", hide_index=True)

    _subheader("Option Factor Row", "section_option_factor")
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


def _render_weight_diagnostics_tab(report_root: Path | str = WEIGHT_REPORT_ROOT) -> None:
    _subheader("Weight Diagnostics", "section_weight_diag")
    st.caption("Shadow mode only. current_weights is production; optimized weights are diagnostics; constrained_blended_weights is a shadow candidate.")
    report_path = Path(report_root) / "latest_weight_diagnostics.json"
    if not report_path.exists():
        st.info(
            "No weight diagnostics report found. Run "
            "`python -m daily_bias_engine.weight_optimizer --snapshot-root data/snapshots --config-dir configs --output-dir reports/weight_optimizer` first."
        )
        return

    try:
        report = _cached_weight_diagnostics(str(report_path), report_path.stat().st_mtime_ns)
    except Exception as exc:
        st.error(f"Weight diagnostics report failed to load: {exc}")
        return

    recommendation = report.get("recommendation", {})
    oos_summary = report.get("oos_summary", {})
    st.caption(
        f"Report created: {report.get('created_at', 'N/A')} | "
        f"OOS samples: {oos_summary.get('sample_count', 'N/A')}"
    )
    metric_columns = st.columns(4)
    metric_columns[0].metric("current_weights", "production", help=_help_text("metric_current_weights"))
    metric_columns[1].metric("optimized_weights", "diagnostic", help=_help_text("metric_optimized_weights"))
    metric_columns[2].metric("constrained_blended", "shadow", help=_help_text("metric_blended_weights"))
    metric_columns[3].metric("adoption_status", str(report.get("adoption_status", "not adopted")), help=_help_text("metric_adoption_status"))

    _subheader("Final recommendation", "section_weight_recommendation")
    st.write(recommendation.get("recommendation", "review_required"))
    st.write(recommendation.get("should_any_weight_be_adopted_into_production_now", "No."))

    _subheader("Weight comparison", "section_weight_comparison")
    st.dataframe(_weight_comparison_table(report), width="stretch", hide_index=True)

    _subheader("Constraint check", "section_constraint_check")
    st.dataframe(_constraint_check_table(report.get("constraint_checks", {})), width="stretch", hide_index=True)

    _subheader("Fold performance", "section_fold_performance")
    st.dataframe(_weight_fold_table(report.get("walk_forward_folds", [])), width="stretch", hide_index=True)

    _subheader("Factor stability", "section_factor_stability")
    st.dataframe(_weight_factor_stability_table(report.get("factor_stability", [])), width="stretch", hide_index=True)

    bucket_columns = st.columns(2)
    with bucket_columns[0]:
        _subheader("Return bucket analysis", "section_return_bucket")
        st.dataframe(_round_numeric(pd.DataFrame(report.get("bucket_analysis_return", []))), width="stretch", hide_index=True)
    with bucket_columns[1]:
        _subheader("Risk bucket analysis", "section_risk_bucket")
        st.dataframe(_round_numeric(pd.DataFrame(report.get("bucket_analysis_risk", []))), width="stretch", hide_index=True)

    _subheader("Regime diagnostics", "section_regime_diag")
    st.dataframe(_weight_regime_table(report.get("regime_diagnostics", {})), width="stretch", hide_index=True)


def _render_liquidity_tab(
    availability_path: Path | str = LIQUIDITY_AVAILABILITY_PATH,
    raw_panel_path: Path | str = LIQUIDITY_RAW_PANEL_PATH,
    chart_root: Path | str = LIQUIDITY_CHART_ROOT,
) -> None:
    _subheader("Global Dollar Liquidity", "section_liquidity")
    availability_file = Path(availability_path)
    raw_panel_file = Path(raw_panel_path)
    chart_dir = Path(chart_root)
    st.caption(
        "Local-only display. Refresh outside Streamlit with "
        "`python scripts/test_liquidity_data_availability.py --start 1990-01-01`, "
        "then commit the generated CSV/SVG files."
    )

    missing = [str(path) for path in (availability_file, raw_panel_file) if not path.exists()]
    if missing:
        st.info(f"Local liquidity files are missing: {missing}")
        return

    try:
        availability, panel = _cached_liquidity_data(
            str(availability_file),
            availability_file.stat().st_mtime_ns,
            str(raw_panel_file),
            raw_panel_file.stat().st_mtime_ns,
        )
    except Exception as exc:
        st.error(f"Local liquidity data failed to load: {exc}")
        return

    summary = _liquidity_summary(availability, panel)
    metric_columns = st.columns(6)
    metric_columns[0].metric("Indicators", f"{summary['success_count']}/{summary['indicator_count']}")
    metric_columns[1].metric("Latest Date", summary["latest_date"])
    metric_columns[2].metric("Net Liquidity", summary["net_liquidity"])
    metric_columns[3].metric("ON RRP", summary["on_rrp"])
    metric_columns[4].metric("TGA", summary["tga"])
    metric_columns[5].metric("DXY", summary["dxy"])

    source_table = _liquidity_source_table(availability)
    if not source_table.empty:
        st.caption("Actual sources found in the committed local dataset:")
        st.dataframe(source_table, width="stretch", hide_index=True)

    local_charts, interactive, availability_tab, raw_panel_tab = st.tabs(["Local Charts", "Interactive Panel", "Availability", "Raw Panel"])

    with local_charts:
        _render_liquidity_svg_grid(chart_dir)

    with interactive:
        available_columns = [column for column in panel.columns if column != "date"]
        default_columns = [column for column in _default_liquidity_chart_columns() if column in available_columns]
        selected_columns = st.multiselect("Indicators", available_columns, default=default_columns)
        normalize = st.checkbox("Index selected series to 100", value=len(selected_columns) > 1)
        chart_data = _liquidity_chart_data(panel, selected_columns, normalize=normalize)
        if chart_data.empty:
            st.info("No local liquidity panel data available for the selected indicators.")
        else:
            st.line_chart(chart_data)
            with st.expander("Selected local chart data"):
                st.dataframe(_round_numeric(chart_data.reset_index()), width="stretch", hide_index=True)

    with availability_tab:
        _subheader("Data Availability", "section_liquidity_availability")
        st.dataframe(_liquidity_availability_table(availability), width="stretch", hide_index=True)

    with raw_panel_tab:
        _subheader("Raw Liquidity Panel", "section_liquidity_panel")
        st.dataframe(_round_numeric(panel.sort_values("date", ascending=False)), width="stretch", hide_index=True)


def _load_liquidity_data(availability_path: Path | str, raw_panel_path: Path | str) -> tuple[pd.DataFrame, pd.DataFrame]:
    availability_file = Path(availability_path)
    raw_panel_file = Path(raw_panel_path)
    if not availability_file.exists():
        raise FileNotFoundError(f"Missing liquidity availability CSV: {availability_file}")
    if not raw_panel_file.exists():
        raise FileNotFoundError(f"Missing liquidity raw panel CSV: {raw_panel_file}")

    availability = pd.read_csv(availability_file, encoding="utf-8-sig")
    panel = pd.read_csv(raw_panel_file, encoding="utf-8-sig")
    if "date" not in panel.columns:
        raise ValueError("Liquidity raw panel must contain a date column.")
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
    panel = panel.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return availability, panel


def _liquidity_summary(availability: pd.DataFrame, panel: pd.DataFrame) -> dict[str, str]:
    success_col = "success / fail"
    success_count = int(availability[success_col].eq("success").sum()) if success_col in availability.columns else 0
    indicator_count = int(len(availability))
    latest_date = "N/A"
    if not panel.empty and "date" in panel.columns:
        dates = pd.to_datetime(panel["date"], errors="coerce").dropna()
        if not dates.empty:
            latest_date = dates.max().strftime("%Y-%m-%d")
    return {
        "indicator_count": str(indicator_count),
        "success_count": str(success_count),
        "latest_date": latest_date,
        "net_liquidity": _latest_liquidity_value(panel, "Dollar liquidity proxy / Fed Net Liquidity proxy"),
        "on_rrp": _latest_liquidity_value(panel, "ON RRP"),
        "tga": _latest_liquidity_value(panel, "TGA"),
        "dxy": _latest_liquidity_value(panel, "DXY"),
    }


def _liquidity_source_table(availability: pd.DataFrame) -> pd.DataFrame:
    if "actual_source_found" not in availability.columns:
        return pd.DataFrame()
    table = (
        availability["actual_source_found"]
        .fillna("")
        .replace("", pd.NA)
        .dropna()
        .value_counts()
        .rename_axis("actual_source_found")
        .reset_index(name="indicator_count")
    )
    return table


def _liquidity_availability_table(availability: pd.DataFrame) -> pd.DataFrame:
    table = availability.copy()
    numeric_columns = [column for column in ("latest_value",) if column in table.columns]
    for column in numeric_columns:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    return _round_numeric(table)


def _latest_liquidity_value(panel: pd.DataFrame, column: str) -> str:
    if panel.empty or column not in panel.columns:
        return "N/A"
    values = pd.to_numeric(panel[column], errors="coerce").dropna()
    if values.empty:
        return "N/A"
    return f"{float(values.iloc[-1]):,.3f}"


def _default_liquidity_chart_columns() -> list[str]:
    return [
        "Dollar liquidity proxy / Fed Net Liquidity proxy",
        "ON RRP",
        "TGA",
        "SOFR",
        "3M Treasury Yield",
        "DXY",
        "HY OAS / High Yield Spread",
        "MOVE Index",
    ]


def _liquidity_chart_data(panel: pd.DataFrame, columns: list[str], *, normalize: bool) -> pd.DataFrame:
    if panel.empty or not columns:
        return pd.DataFrame()
    existing = [column for column in columns if column in panel.columns]
    if not existing:
        return pd.DataFrame()
    chart_data = panel[["date", *existing]].copy()
    chart_data["date"] = pd.to_datetime(chart_data["date"], errors="coerce")
    chart_data = chart_data.dropna(subset=["date"]).set_index("date").sort_index()
    chart_data = chart_data.apply(pd.to_numeric, errors="coerce")
    chart_data = chart_data.dropna(how="all")
    if chart_data.empty or not normalize:
        return chart_data

    indexed = pd.DataFrame(index=chart_data.index)
    for column in chart_data.columns:
        series = chart_data[column].dropna()
        if series.empty:
            continue
        first = float(series.iloc[0])
        if first == 0:
            continue
        indexed[column] = chart_data[column] / first * 100.0
    return indexed.dropna(how="all")


def _render_liquidity_svg_grid(chart_dir: Path) -> None:
    chart_specs = [
        ("Fed Net Liquidity vs SPX / Nasdaq", chart_dir / "fed_net_liquidity_vs_spx_nasdaq.svg"),
        ("ON RRP", chart_dir / "on_rrp.svg"),
        ("TGA", chart_dir / "tga.svg"),
        ("SOFR", chart_dir / "sofr.svg"),
        ("3M Treasury", chart_dir / "3m_treasury.svg"),
        ("DXY", chart_dir / "dxy.svg"),
        ("HY Spread", chart_dir / "hy_spread.svg"),
        ("MOVE", chart_dir / "move.svg"),
    ]
    for index in range(0, len(chart_specs), 2):
        columns = st.columns(2)
        for column, (title, path) in zip(columns, chart_specs[index : index + 2]):
            with column:
                _subheader(title)
                if path.exists():
                    st.markdown(path.read_text(encoding="utf-8"), unsafe_allow_html=True)
                else:
                    st.info(f"Local chart not found: {path}")


def _option_payload_table(values: dict[str, Any]) -> pd.DataFrame:
    rows = [{"Metric": key, "Value": _option_display_value(value)} for key, value in values.items()]
    return pd.DataFrame(rows)


def _option_display_value(value: Any) -> str:
    if not isinstance(value, bool) and _is_missing_scalar(value):
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
    _subheader(title)
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
        return result, str(result.get("snapshot_load_warning", ""))
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
    table["date"] = pd.to_datetime(table["date"])
    table = table.sort_values("date", ascending=False).reset_index(drop=True)
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
    dates = pd.to_datetime(scores["date"], errors="coerce").dropna().drop_duplicates().sort_values()
    return dates.dt.strftime("%Y-%m-%d").tolist()


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


def _risk_flags_table(risk_flags: Any) -> pd.DataFrame:
    records = _record_list(risk_flags)
    if not records:
        return pd.DataFrame(columns=["风险类型", "因子", "模块", "因子分", "触发阈值", "含义"])
    rows = []
    for flag in records:
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


def _drivers_table(drivers: Any) -> pd.DataFrame:
    records = _record_list(drivers)
    if not records:
        return pd.DataFrame(columns=["因子", "模块", "因子分", "贡献", "原始值", "z-score"])
    table = pd.DataFrame(records).rename(
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


def _factor_contribution_table(factors: Any) -> pd.DataFrame:
    records = _record_list(factors)
    if not records:
        return pd.DataFrame(columns=["数据日期", "因子", "模块", "方向分", "因子分", "权重", "贡献", "原始值", "z-score"])
    table = pd.DataFrame(records).rename(
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


def _weight_comparison_table(report: dict[str, Any]) -> pd.DataFrame:
    current = report.get("current_weights", {})
    return_weights = report.get("optimized_return_weights", {})
    risk_weights = report.get("optimized_risk_weights", {})
    blended = report.get("constrained_blended_weights", {})
    factors = sorted(set(current) | set(return_weights) | set(risk_weights) | set(blended))
    rows = []
    for factor in factors:
        rows.append(
            {
                "factor": factor,
                "current_weights": current.get(factor),
                "optimized_return_weights": return_weights.get(factor),
                "optimized_risk_weights": risk_weights.get(factor),
                "constrained_blended_weights": blended.get(factor),
            }
        )
    return _round_numeric(pd.DataFrame(rows))


def _constraint_check_table(checks: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for name, payload in checks.items():
        rows.append(
            {
                "weight_set": name,
                "pass": bool(payload.get("pass")) if isinstance(payload, dict) else False,
                "weight_sum": payload.get("weight_sum") if isinstance(payload, dict) else None,
                "fail_reason": "; ".join(payload.get("violations", [])) if isinstance(payload, dict) else "invalid check",
            }
        )
    return _round_numeric(pd.DataFrame(rows))


def _weight_fold_table(folds: list[dict[str, Any]]) -> pd.DataFrame:
    if not folds:
        return pd.DataFrame()
    columns = [
        "fold",
        "train_start",
        "train_end",
        "test_start",
        "test_end",
        "sample_count",
        "return_score_test_ic",
        "direction_hit_rate",
        "strong_signal_count",
        "strong_signal_hit_rate",
        "big_loss_count",
        "TP",
        "FP",
        "TN",
        "FN",
        "big_loss_capture_rate",
        "big_loss_precision_rate",
        "big_loss_avoidance_rate",
        "max_drawdown_proxy",
    ]
    table = pd.DataFrame([{column: fold.get(column) for column in columns} for fold in folds])
    return _round_numeric(table)


def _weight_factor_stability_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    columns = [
        "final_stability_rank",
        "factor_name",
        "return_ic_mean",
        "return_ic_abs_mean",
        "return_ic_volatility",
        "return_predictive_score",
        "risk_predictive_score",
        "weight_volatility",
        "optimized_return_weight",
        "optimized_risk_weight",
        "constrained_blended_weight",
    ]
    existing = [column for column in columns if column in rows[0]]
    return _round_numeric(pd.DataFrame(rows)[existing])


def _weight_regime_table(regimes: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for regime_type, items in regimes.items():
        for item in items:
            return_perf = item.get("return_score_performance", {})
            risk_perf = item.get("risk_score_performance", {})
            rows.append(
                {
                    "regime_type": regime_type,
                    "regime": item.get("regime"),
                    "sample_count": item.get("sample_count"),
                    "return_ic": return_perf.get("ic"),
                    "return_direction_hit_rate": return_perf.get("direction_hit_rate"),
                    "risk_capture_rate": risk_perf.get("big_loss_capture_rate"),
                    "risk_precision": risk_perf.get("precision"),
                    "failed_factors": ", ".join(item.get("failed_factors", [])),
                    "effective_factors": ", ".join(item.get("regime_effective_factors", [])),
                }
            )
    return _round_numeric(pd.DataFrame(rows))


def _round_numeric(table: pd.DataFrame) -> pd.DataFrame:
    output = table.copy()
    numeric_columns = output.select_dtypes(include="number").columns
    output[numeric_columns] = output[numeric_columns].round(3)
    return output


def _record_list(value: Any) -> list[dict[str, Any]]:
    if _is_missing_scalar(value):
        return []
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, pd.Series):
        value = value.tolist()
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _is_missing_scalar(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (Mapping, list, tuple, pd.Series, pd.DataFrame, np.ndarray)):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _format_percent(value: Any) -> str:
    if _is_missing_scalar(value):
        return "N/A"
    return f"{float(value) * 100:.1f}%"


def _format_float(value: Any) -> str:
    if _is_missing_scalar(value):
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


def _override_reason_from_flags(risk_flags: Any) -> str:
    records = _record_list(risk_flags)
    if not records:
        return ""
    reasons = []
    for flag in records:
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
        "ifind": "Localized iFinD data",
    }
    return labels.get(value, value)



if __name__ == "__main__":
    main()
