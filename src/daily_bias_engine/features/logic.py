"""Human-readable factor logic metadata."""

from __future__ import annotations

FACTOR_LOGIC = [
    {
        "factor_name": "equity_index_futures_basis",
        "group": "股指期货结构",
        "raw_formula": "期货收盘价 / 沪深300现货指数收盘价 - 1",
        "normalization": "20日滚动 z-score，至少3个样本；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "基差更强、贴水收敛或升水扩大，解释为风险偏好改善，偏 Risk-On。",
        "caveat": "当前 MVP 只用 IF.CFE 与 000300.SH 的平均结构，尚未展开 IF/IH/IC/IM 跨品种结构。",
    },
    {
        "factor_name": "futures_open_interest_momentum",
        "group": "股指期货结构",
        "raw_formula": "期货持仓量 5 日变化率",
        "normalization": "20日滚动 z-score；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "持仓上升被视为风险参与度提高，偏 Risk-On；持仓回落偏谨慎。",
        "caveat": "真实生产版需要结合价格方向区分增仓上涨、增仓下跌、减仓反弹。",
    },
    {
        "factor_name": "rates_change_5d",
        "group": "利率与债券",
        "raw_formula": "利率序列平均值的 5 日差分",
        "normalization": "20日滚动 z-score；方向分使用负号，即利率上行偏 Risk-Off",
        "direction": "当前 MVP 将利率上行解释为估值/流动性压力，利率下行偏支持风险资产。",
        "caveat": "后续应升级为股债关系分类，区分宽松型 Risk-On 与避险型 Risk-Off。",
    },
    {
        "factor_name": "yield_curve_slope",
        "group": "利率与债券",
        "raw_formula": "较长期利率 - 较短期利率",
        "normalization": "20日滚动 z-score；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "曲线变陡被暂时解释为增长预期改善，偏 Risk-On。",
        "caveat": "当前根据传入序列排序取首尾，生产版需要显式指定 10Y-1Y、30Y-10Y 等期限结构。",
    },
    {
        "factor_name": "etf_flow_proxy",
        "group": "ETF 与资金流",
        "raw_formula": "ETF 成交额 5 日变化率",
        "normalization": "20日滚动 z-score；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "ETF 成交额放大被视为资金参与增强，偏 Risk-On。",
        "caveat": "当前是成交额 proxy，不等于真实 ETF 净申购；接 Wind 后应替换为申赎/份额口径。",
    },
    {
        "factor_name": "margin_balance_momentum",
        "group": "ETF 与资金流",
        "raw_formula": "margin_balance 5 日变化率；若无真实字段则由成交额生成演示 proxy",
        "normalization": "20日滚动 z-score；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "融资/杠杆资金回升偏 Risk-On，回落偏 Risk-Off。",
        "caveat": "当前 Wind pipeline 暂未接真实两融字段，仍是 proxy。",
    },
    {
        "factor_name": "overseas_market_momentum",
        "group": "海外隔夜",
        "raw_formula": "海外资产平均收盘价 1 日收益率",
        "normalization": "20日滚动 z-score；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "海外市场上涨偏 Risk-On，下跌偏 Risk-Off。",
        "caveat": "当前只用 SPX.GI、HSI.HI；后续应加入 A50、VIX、CNH、美元、美债。",
    },
    {
        "factor_name": "overseas_volatility_pressure",
        "group": "海外隔夜",
        "raw_formula": "海外资产平均 (high - low) / close",
        "normalization": "20日滚动 z-score；方向分使用负号，即波动放大偏 Risk-Off",
        "direction": "海外波动压力上升偏 Risk-Off，波动回落偏 Risk-On。",
        "caveat": "当前用价格振幅 proxy，生产版应优先接 VIX 与外汇压力。",
    },
    {
        "factor_name": "ashare_breadth_proxy",
        "group": "A股市场结构",
        "raw_formula": "样本指数中 close > open 的比例 - 0.5",
        "normalization": "20日滚动 z-score；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "上涨扩散度提高偏 Risk-On，扩散度走弱偏 Risk-Off。",
        "caveat": "当前只用指数样本 proxy，后续应接全市场上涨家数、涨跌停、行业扩散度。",
    },
    {
        "factor_name": "ashare_turnover_momentum",
        "group": "A股市场结构",
        "raw_formula": "样本指数成交量 5 日变化率",
        "normalization": "20日滚动 z-score；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "成交放大暂时解释为风险参与度提高，偏 Risk-On。",
        "caveat": "成交放大在下跌时也可能是风险释放，后续应与方向和亏钱效应联动。",
    },
]


def factor_logic_rows() -> list[dict[str, str]]:
    return FACTOR_LOGIC
