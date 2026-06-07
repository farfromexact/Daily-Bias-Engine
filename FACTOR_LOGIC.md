# Factor Logic

本文档解释当前 Daily Bias Engine MVP 中每个因子的用途、计算公式、方向映射和限制。

## 总体流程

1. 使用 Wind 或 Mock 获取日频数据。
2. 每个原始因子先计算 `raw_value`。
3. 对 `raw_value` 做 20 日滚动 z-score，至少 3 个样本。
4. 将 z-score 按方向映射到 `directional_score`：
   - `+1` 代表强 Risk-On。
   - `0` 代表中性。
   - `-1` 代表强 Risk-Off。
5. 因子得分 = `directional_score * 100`。
6. 引擎按 `configs/factor_weights.yaml` 加权，输出 `-100` 到 `+100` 的总分。
7. 日收盘数据生成下一交易日的开盘前信号，所以 `data_date < signal date`。

## 当前因子

| 因子 | 模块 | 原始值 | 方向 |
| --- | --- | --- | --- |
| `equity_index_futures_basis` | 股指期货结构 | 期货收盘价 / 沪深300收盘价 - 1 | 基差改善偏 Risk-On |
| `futures_open_interest_momentum` | 股指期货结构 | 持仓量 5 日变化率 | 持仓上升偏 Risk-On |
| `rates_change_5d` | 利率与债券 | 平均利率 5 日差分 | 利率上行偏 Risk-Off |
| `yield_curve_slope` | 利率与债券 | 长端利率 - 短端利率 | 曲线变陡暂偏 Risk-On |
| `etf_flow_proxy` | ETF 与资金流 | ETF 成交额 5 日变化率 | 成交额放大偏 Risk-On |
| `margin_balance_momentum` | ETF 与资金流 | 两融余额或 proxy 的 5 日变化率 | 杠杆资金回升偏 Risk-On |
| `overseas_market_momentum` | 海外隔夜 | 海外资产 1 日收益率 | 海外上涨偏 Risk-On |
| `overseas_volatility_pressure` | 海外隔夜 | 海外资产日内振幅 | 波动放大偏 Risk-Off |
| `ashare_breadth_proxy` | A股市场结构 | 样本指数上涨比例 - 0.5 | 扩散度提高偏 Risk-On |
| `ashare_turnover_momentum` | A股市场结构 | 样本指数成交量 5 日变化率 | 成交放大暂偏 Risk-On |

## 重要限制

当前版本仍是研究框架，不是最终投研模型：

- 股指期货结构尚未完整展开 IF/IH/IC/IM 相对强弱。
- ETF 资金流仍使用成交额 proxy，不是真实净申购。
- 两融数据仍是 proxy。
- 海外隔夜尚未接入 A50、VIX、CNH、美元、美债。
- A股市场结构尚未接全市场上涨家数、涨跌停、行业扩散度。
- 利率模块尚未升级为“股债关系分类”。

因此，当前分数可以用来验证框架和数据链路，但不应直接视为可交易结论。
