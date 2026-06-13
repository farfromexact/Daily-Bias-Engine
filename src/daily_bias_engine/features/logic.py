"""Human-readable factor logic metadata."""

from __future__ import annotations

FACTOR_LOGIC = [
    {
        "factor_name": "equity_index_futures_basis",
        "group": "股指期货结构",
        "data_source": "iFinD 真实日频收盘价：IF.CFE 与 000300.SH。",
        "raw_formula": "期货收盘价 / 沪深300现货指数收盘价 - 1",
        "normalization": "20日滚动 z-score，至少3个样本；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "基差更强、贴水收敛或升水扩大，解释为风险偏好改善，偏 Risk-On。",
        "caveat": "数据是真实 iFinD 本地快照；MVP 口径只用 IF 与沪深300，尚未展开 IF/IH/IC/IM 跨品种结构。",
    },
    {
        "factor_name": "futures_open_interest_momentum",
        "group": "股指期货结构",
        "data_source": "iFinD 真实日频期货持仓量：IF.CFE oi。",
        "raw_formula": "期货持仓量 5 日变化率",
        "normalization": "20日滚动 z-score；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "持仓上升被视为风险参与度提高，偏 Risk-On；持仓回落偏谨慎。",
        "caveat": "真实生产版需要结合价格方向区分增仓上涨、增仓下跌、减仓反弹。",
    },
    {
        "factor_name": "rates_change_5d",
        "group": "利率与债券",
        "data_source": "iFinD 真实利率序列：DR007.IB。",
        "raw_formula": "DR007.IB 的 5 日差分",
        "normalization": "20日滚动 z-score；方向分使用负号，即利率上行偏 Risk-Off",
        "direction": "当前 MVP 将利率上行解释为估值/流动性压力，利率下行偏支持风险资产。",
        "caveat": "后续应升级为股债关系分类，区分宽松型 Risk-On 与避险型 Risk-Off。",
    },
    {
        "factor_name": "yield_curve_slope",
        "group": "利率与债券",
        "data_source": "iFinD EDB：L001618299 中债国债到期收益率:30年；L001619604 中债国债到期收益率:10年。",
        "raw_formula": "30年国债到期收益率 - 10年国债到期收益率",
        "normalization": "20日滚动 z-score；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "曲线变陡被暂时解释为增长预期改善，偏 Risk-On。",
        "caveat": "该因子已显式绑定 30Y 与 10Y 的 iFinD EDB 指标 ID；取不到真实 EDB 时不伪造数据。",
    },
    {
        "factor_name": "etf_flow_proxy",
        "group": "ETF 与资金流",
        "data_source": "iFinD 真实 ETF 日频成交额：510300.SH、510500.SH。",
        "raw_formula": "ETF 成交额 5 日变化率",
        "normalization": "20日滚动 z-score；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "ETF 成交额放大被视为资金参与增强，偏 Risk-On。",
        "caveat": "这里的 proxy 指因子口径：成交额是真实 iFinD 数据，但它不等于真实 ETF 净申购/份额变化。",
    },
    {
        "factor_name": "margin_balance_momentum",
        "group": "ETF 与资金流",
        "data_source": "当前由真实 iFinD ETF 成交额派生演示字段；尚未接真实两融余额。",
        "raw_formula": "margin_balance 5 日变化率；若无真实字段则由成交额生成演示 proxy",
        "normalization": "20日滚动 z-score；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "融资/杠杆资金回升偏 Risk-On，回落偏 Risk-Off。",
        "caveat": "这是当前最需要替换的 proxy：快照真实，但该字段不是 iFinD 两融真实字段。",
    },
    {
        "factor_name": "overseas_market_momentum",
        "group": "海外隔夜",
        "data_source": "真实海外指数日频价格：SPX.GI、N225.GI、KS11.GI。",
        "raw_formula": "单个指数先算 1 日收益率，再按 SPX 80%、N225 10%、KS11 10% 加权；若某市场缺数据，则按当日可用权重重归一。",
        "normalization": "20日滚动 z-score；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "海外市场上涨偏 Risk-On，下跌偏 Risk-Off。",
        "caveat": "当前覆盖美国、日本、韩国；后续可加入 A50、VIX、CNH、美元、美债等风险变量。",
    },
    {
        "factor_name": "overseas_volatility_pressure",
        "group": "海外隔夜",
        "data_source": "真实海外指数高低价：SPX.GI、N225.GI、KS11.GI；振幅为由价格派生的波动 proxy。",
        "raw_formula": "单个指数先算 (high - low) / close，再按 SPX 80%、N225 10%、KS11 10% 加权。",
        "normalization": "20日滚动 z-score；方向分使用负号，即波动放大偏 Risk-Off",
        "direction": "海外波动压力上升偏 Risk-Off，波动回落偏 Risk-On。",
        "caveat": "这里的 proxy 指波动压力口径；生产版应优先接 VIX、CNH、美元、美债。",
    },
    {
        "factor_name": "ashare_breadth_proxy",
        "group": "A股市场结构",
        "data_source": "真实指数日频开收盘价：000016.SH、000300.SH、000688.SH、399006.SZ。",
        "raw_formula": "样本指数中 close > open 的比例 - 0.5",
        "normalization": "20日滚动 z-score；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "上涨扩散度提高偏 Risk-On，扩散度走弱偏 Risk-Off。",
        "caveat": "当前样本为上证50、沪深300、科创50、创业板指；仍是指数样本宽度 proxy，后续可接上涨家数、涨跌停、行业扩散度。",
    },
    {
        "factor_name": "ashare_turnover_momentum",
        "group": "A股市场结构",
        "data_source": "真实指数日频成交量：000016.SH、000300.SH、000688.SH、399006.SZ。",
        "raw_formula": "上证50、沪深300、科创50、创业板指成交量均值的 5 日变化率",
        "normalization": "20日滚动 z-score；方向分 = clip(zscore, -2, 2) / 2",
        "direction": "成交放大暂时解释为风险参与度提高，偏 Risk-On。",
        "caveat": "成交放大在下跌时也可能是风险释放，后续应与方向和亏钱效应联动。",
    },
]


def factor_logic_rows() -> list[dict[str, str]]:
    return FACTOR_LOGIC
