# Daily Bias Engine 使用手册

本文面向第一次使用本系统的人，目标是让你知道它是什么、怎么更新真实数据、怎么看 Streamlit 页面、以及常见问题怎么处理。

## 1. 系统定位

Daily Bias Engine 是一个盘前市场环境过滤器，不是自动交易系统，也不是逐笔预测器。

它把真实行情数据本地化成快照，然后用规则化因子输出每天盘前的市场风向：

- `Risk-On`：风险偏好较强。
- `Neutral`：信号不够偏向，或多空信息互相抵消。
- `Risk-Off`：风险偏好较弱，或触发硬风险规则。

当前版本坚持两个原则：

- 生产使用只读真实本地化数据，不提供 mock 数据选项。
- 盘前信号不能使用同一交易日收盘后才知道的数据。

举例：如果最新原始数据截止 `2026-06-12` 收盘，系统生成的是 `2026-06-15` 盘前信号。这里的 `2026-06-15` 是信号日期，`2026-06-12` 是因子数据日期。

## 2. 系统由哪些部分组成

### 主市场风向模块

主模块读取 `data/snapshots/` 下的市场快照，计算：

- 股指期货基差和持仓变化。
- 利率变化。
- ETF 和资金流 proxy。
- 海外隔夜市场。
- A 股市场结构 proxy。
- 总分、风向标签、趋势强度分、风险覆盖。

### 期权状态模块

期权模块读取 `data/options_wind/` 下的期权链，支持：

- `SSE50`
- `CSI300`
- `CSI1000`

输出包括 GEX、vanna、charm、vega、关键行权价、IV、偏斜、风险分数和 overlay 建议。

### Streamlit 看板

Streamlit 是主要使用入口。它不会实时请求 Wind，而是读取已经落地的本地快照。

### 脚本层

脚本负责把外部 API 数据本地化：

- `scripts/update_wind_data.py`：日常总入口，增量更新主市场和期权数据。
- `scripts/fetch_wind_snapshot.py`：更新主市场快照。
- `scripts/fetch_wind_options_snapshot.py`：更新 Wind 期权链。

## 3. 安装和环境准备

进入项目目录：

```powershell
cd "C:\Users\macon\Documents\Daily Bias Engine"
```

首次创建项目虚拟环境并安装依赖。已有环境时直接激活。

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
```

运行测试：

```powershell
pytest
```

使用官方 Wind API 登录本机账号。在项目虚拟环境中运行 `python scripts/configure_wind.py`，脚本会查找已安装的 SDK 并写入该环境的 `WindPy.pth`。macOS 默认位置为 `/Applications/Wind API.app/Contents/python`。Windows 支持通过 `--wind-python-dir` 指定包含 `WindPy.py` 的目录。首次取数时在官方 Wind API 登录窗口完成认证。

## 4. 推荐日常使用流程

每天更新数据并看结果的常规顺序：

1. 打开 PowerShell，进入项目目录。
2. 确认 Wind API 已登录，与 Trading Desk 错开 WindPy 采集时段。
3. 运行日常增量更新脚本。
4. 启动或刷新 Streamlit。

日常总入口：

```powershell
python scripts\update_wind_data.py
```

它会先增量更新主市场快照，再增量更新 `SSE50`、`CSI300`、`CSI1000` 期权链。期权首次取最近一个交易日，之后从各产品最后一个已保存日期继续。可用 `--options-start YYYY-MM-DD` 补历史。

查看将要更新的区间但不调用 Wind：

```powershell
python scripts\update_wind_data.py --dry-run
```

### 4.1 更新主市场快照

默认是增量优先：

```powershell
python scripts\fetch_wind_snapshot.py
```

增量更新从各序列最后有效日期中最早需要补数的日期开始，重新计算完整快照。首次更新或早期 Wind 快照缺少当前品种时，重新获取最近三年的历史。

指定截止日期：

```powershell
python scripts\fetch_wind_snapshot.py --end 2026-06-12 --years 3
```

强制重拉三年全量：

```powershell
python scripts\fetch_wind_snapshot.py --full-refresh --years 3
```

指定完整区间：

```powershell
python scripts\fetch_wind_snapshot.py --start 2023-06-12 --end 2026-06-12
```

脚本会写入：

```text
data/snapshots/<生成时间>_wind_<开始日期>_<结束日期>/
```

Streamlit 会自动读取 `data/snapshots/` 中生成时间最新的 Wind 快照。

注意：即使 API 只增量取一天，模型计算仍使用合并后的历史数据，因为 5 日变化、20 日 z-score、60/120 日标签和诊断都需要历史窗口。

### 4.2 更新期权链

更新某一天全部产品：

```powershell
python scripts\fetch_wind_options_snapshot.py --date 2026-06-12
```

更新某一天单个产品：

```powershell
python scripts\fetch_wind_options_snapshot.py --date 2026-06-12 --product CSI300
```

更新一段区间全部产品：

```powershell
python scripts\fetch_wind_options_snapshot.py --start-date 2026-01-01 --end-date 2026-06-12
```

更新一段区间的多个指定产品：

```powershell
python scripts\fetch_wind_options_snapshot.py --start-date 2026-01-01 --end-date 2026-06-12 --product SSE50 --product CSI300
```

默认输出目录是：

```text
data/options_wind/
```

如果本地已经有同一天同产品的数据，脚本默认跳过。需要强制重拉时加：

```powershell
--overwrite
```

如果希望遇到第一个错误就停止，加：

```powershell
--fail-fast
```

## 5. 启动 Streamlit

默认端口：

```powershell
python -m streamlit run apps\streamlit_app.py
```

指定端口 `8506`：

```powershell
python -m streamlit run apps\streamlit_app.py --server.port 8506
```

## 6. 本地更新和部署数据

在安装官方 Wind API 并已配置 WindPy 的本地机器上运行更新。

本地日常更新入口：

```powershell
python scripts\update_wind_data.py
```

这个脚本会增量更新主市场 snapshot 和 `SSE50`、`CSI300`、`CSI1000` 期权链，并只保留最近 2 个 Wind 主市场快照。Streamlit Cloud 不直接调用 Wind；它只读取 GitHub 仓库中已经提交的最新 parquet。

如果希望外网 Streamlit Cloud 也显示最新数据，本地提数后提交并 push：

```powershell
git add -- data/snapshots data/options_wind
git commit -m "chore(data): update local Wind snapshots"
git push
```

浏览器打开：

```text
http://localhost:8506/
```

如果页面仍显示旧数据，先刷新页面；如果仍旧，重启 Streamlit 进程。Streamlit 读取的是本地最新快照目录，不会在页面里直接调用 Wind。

## 7. 如何确认数据已经更新

查看最新主快照：

```powershell
Get-ChildItem data\snapshots -Directory -Filter "*_wind_*" | Sort-Object Name -Descending | Select-Object -First 3 Name
```

用 Python 读取最新快照摘要：

```powershell
python -c "from pathlib import Path; import json; from daily_bias_engine.pipeline import list_snapshots; s=list_snapshots(Path('data/snapshots'), source='wind')[0]; m=json.loads((s.path/'manifest.json').read_text(encoding='utf-8')); print(s.path); print(m['source'], m['start_date'], m['end_date']); print(m['latest'])"
```

查看期权数据日期：

```powershell
Get-ChildItem data\options_wind\normalized_chain\product_group=CSI300 | Sort-Object Name -Descending | Select-Object -First 5 Name
```

生成单日 CSI300 期权状态 JSON：

```powershell
python -m daily_bias_engine.options.reports.daily_option_state --date 2026-06-12 --product CSI300 --data-root data\options_wind
```

## 8. 权重诊断报告

权重诊断模块只生成报告和推荐，不会覆盖 `configs/factor_weights.yaml`。

运行：

```powershell
python -m daily_bias_engine.weight_optimizer --snapshot-root data\snapshots --config-dir configs --output-dir reports\weight_optimizer
```

输出内容包括：

- 每一折 walk-forward 的训练区间、测试区间、`return_weights`、`risk_weights` 和测试指标。
- 每个因子的 return/risk rolling IC、稳定性排名和权重波动率。
- `current_weights`、`optimized_return_weights`、`optimized_risk_weights`、`constrained_blended_weights`。
- `raw_blended_weights` 到 `constrained_blended_weights` 的约束投影检查。
- return/risk score 分桶、regime diagnostics、leakage checks 和 permutation sanity check。
- 约束检查结果，包括单因子、单模块、利率、ETF 成交额与融资余额、`yield_curve_slope` 等限制。

这些输出用于人工审阅，不会被 Streamlit 或引擎自动加载。

## 9. Streamlit 页面怎么看

### Overview

这是最常用页面。重点看：

- 信号日期：当前正在查看哪一天的盘前信号。
- 市场风向：`Risk-On`、`Neutral` 或 `Risk-Off`。
- 总分：`-100` 到 `+100`。
- 趋势强度分由总分绝对值和硬风险标记计算，范围为 0 到 100。各档位的历史趋势日发生率见 Backtest Diagnostics。
- 趋势方向：`up`、`down` 或 `unclear`。
- 正向驱动和负向驱动：解释当前分数主要由哪些因子贡献。
- 风险覆盖：极端风险因子触发时，会覆盖普通加权总分。

### Factors

展示当前信号日所有因子的原始值、z-score、方向分和贡献。适合检查“为什么今天分数这么高/低”。

### Engine

展示规则引擎输出，包括总分、分组得分、最终标签和解释字段。适合做模型审计。

### Labels

展示事后市场结果标签，例如市场收益、趋势日、下跌日、震荡日。这些标签只用于回测和评估，不能用于生成同一天盘前信号。

### Backtest

并列展示收盘到收盘和开盘到收盘两种三分类命中率，对照每日给 Neutral 的基准。中性区间取配置中的绝对收益阈值，默认 0.3%。大亏日明确防守率只计盘前为 Risk-Off 的日期，旁边给出分子、分母和误报率。

### Backtest Diagnostics

按风向、分数区间、趋势强度区间拆开看历史表现。

### Factor Diagnostics

逐个因子看和后续市场结果的关系，用于判断因子是否仍有解释力。

### Options

展示本地 Wind 期权链计算出的状态，包括：

- regime：期权状态分类。
- key levels：spot、put wall、call wall、max gamma strike、zero gamma。
- exposures：GEX、vanna、charm、vega。
- vol：IV、RV、VRP、IV percentile。
- skew：put skew、call skew、risk reversal。
- recommended overlay：对主市场仓位的期权 overlay 建议。

### Logic

展示因子逻辑说明。若发现文字编码异常，以本文档和代码为准。

## 10. 主市场分数怎么理解

总分范围：

```text
-100 到 +100
```

默认阈值：

```text
score >= +30  => Risk-On
-30 < score < +30 => Neutral
score <= -30 => Risk-Off
```

方向约定：

- 正贡献支持 Risk-On。
- 负贡献支持 Risk-Off。
- 接近 0 表示信息不足或互相抵消。

趋势强度分反映规则强度。趋势方向由 `trend_direction_bias` 单独表示。

## 11. 当前主因子清单

| 因子 | 模块 | 原始含义 | 方向 |
| --- | --- | --- | --- |
| `equity_index_futures_basis` | 股指期货结构 | IF 连续合约相对沪深300现货的基差 | 基差改善偏 Risk-On |
| `futures_open_interest_momentum` | 股指期货结构 | IF 持仓量 5 日变化 | 持仓回升暂偏 Risk-On |
| `rates_change_5d` | 利率 | `DR007.IB` 5 日变化 | 利率上行偏 Risk-Off |
| `yield_curve_slope` | 利率 | Wind EDB 30Y 国债收益率 - 10Y 国债收益率 | 曲线变陡暂偏 Risk-On |
| `etf_flow_proxy` | ETF/资金流 | 510300、510500 成交额 5 日变化 | 成交额回升偏 Risk-On |
| `margin_balance_momentum` | ETF/资金流 | 两只 ETF 的 Wind 融资余额合计相对五个交易日前的变化率 | 融资余额回升偏 Risk-On |
| `overseas_market_momentum` | 海外隔夜 | 美国、日本、韩国指数的加权单日涨跌 | 海外上涨偏 Risk-On |
| `overseas_volatility_pressure` | 海外隔夜 | 美国、日本、韩国指数加权日内振幅 | 波动放大偏 Risk-Off |
| `ashare_breadth_proxy` | A 股结构 | 上证50、沪深300、科创50、创业板指上涨比例 proxy | 扩散改善偏 Risk-On |
| `ashare_turnover_momentum` | A 股结构 | 上证50、沪深300、科创50、创业板指成交量 5 日变化 | 成交回升暂偏 Risk-On |

注意：

- `proxy` 不是假数据，而是指因子口径是替代变量。
- 海外隔夜当前使用 `SPX.GI`、`N225.GI`、`KS11.GI`，权重分别为美国 80%、日本 10%、韩国 10%；如果某个市场当日缺数据，则按当日可用指数的权重重新归一。
- A 股市场宽度当前使用 `000016.SH`、`000300.SH`、`000688.SH`、`399006.SZ`，对应上证50、沪深300、科创50、创业板指。
- 期限利差使用 `S0059752`（中债国债到期收益率:30年）减 `S0059749`（中债国债到期收益率:10年）；取不到真实 EDB 时不会伪造。
- `margin_balance_momentum` 使用 510300.SH 和 510500.SH 的 Wind WSD `mrg_long_bal`。T 日余额从 T+2 盘前起使用，数据日期和模型可用日期分别展示。

## 12. 期权状态怎么理解

期权状态命令：

```powershell
python -m daily_bias_engine.options.reports.daily_option_state --date 2026-06-12 --product CSI300 --data-root data\options_wind
```

核心字段：

| 字段 | 含义 |
| --- | --- |
| `option_direction_score` | 期权层面对方向的支持程度 |
| `option_risk_score` | 期权层面的风险压力 |
| `vol_carry_score` | 波动率 carry 环境 |
| `tail_risk_score` | 尾部风险压力 |
| `regime` | 期权状态分类 |
| `put_wall` | 主要 put 持仓墙 |
| `call_wall` | 主要 call 持仓墙 |
| `max_gamma_strike` | gamma 最大集中的行权价 |
| `zero_gamma` | gamma 符号切换位置，可能为空 |
| `gex_1pct` | 标的移动 1% 对应的 gamma exposure |
| `vanna_1vol` | IV 移动 1 vol 对应的 vanna exposure |
| `charm_1day` | 一天时间流逝对应的 charm exposure |
| `vega_1vol` | IV 移动 1 vol 对应的 vega exposure |
| `iv_30d` | 约 30 天 ATM IV |
| `put_skew_25d` | 25 delta put skew |
| `risk_reversal_25d` | 25 delta risk reversal |

重要限制：

- 当前期权层没有真实交易商持仓数据。
- exposure 的方向依赖模式参数，默认报告使用当前实现的假设口径。
- GEX、vanna、charm、vega 应作为风险结构参考，不应单独作为交易指令。

## 13. 本地数据目录

| 目录 | 用途 | 是否应提交 Git |
| --- | --- | --- |
| `data/snapshots/` | Wind 市场快照，Streamlit 主模块读取 | 按部署需要 |
| `data/raw/wind/` | Wind 原始请求缓存 | 否 |
| `data/options_wind/` | Wind 期权链，Streamlit 期权模块读取 | 按部署需要 |
| `.streamlit_logs/` | 本地 Streamlit 日志 | 否 |

原始请求缓存和本机配置由 Git 忽略。部署所用的 Wind 快照按第 6 节更新。

## 14. 常见问题

### 页面提示没有本地市场快照

先运行：

```powershell
python scripts\fetch_wind_snapshot.py
```

然后重启或刷新 Streamlit。

### Options 页面没有数据

先运行：

```powershell
python scripts\fetch_wind_options_snapshot.py --date 2026-06-12
```

如果看的是历史日期，把 `--date` 改成对应交易日。

### WindPy 导入或登录失败

用当前虚拟环境运行 `python scripts/configure_wind.py --check` 检查 SDK 路径。首次连接时请完成官方 Wind API 登录，并检查账号的 Python API、历史行情与 EDB 权限。权限或额度错误会保留 Wind 原始错误码。

### 期权拉数中间失败

区间拉取时，脚本会记录失败日期和产品。可先不加 `--fail-fast`，让可成功的日期先落地。修复后再对失败日期单独重拉：

```powershell
python scripts\fetch_wind_options_snapshot.py --date 2026-06-12 --product CSI300 --overwrite
```

### Streamlit 端口被占用

换端口：

```powershell
python -m streamlit run apps\streamlit_app.py --server.port 8507
```

### 页面看起来还是旧数据

确认最新快照是否已经写入 `data/snapshots/`。如果已经写入，刷新页面；仍旧则停止 Streamlit 后重新启动。

## 15. 开发和校验

跑完整测试：

```powershell
pytest
```

只校验主要文件语法：

```powershell
python -m py_compile apps\streamlit_app.py scripts\fetch_wind_snapshot.py scripts\fetch_wind_options_snapshot.py scripts\update_wind_data.py
```

查看 Git 状态：

```powershell
git status --short
```

提交前确认不要把以下内容加入 Git：

- 真实账号密码。
- `data/raw/wind/` 原始请求审计缓存。
- 本地日志文件。

`data/snapshots/` 和 `data/options_wind/` 中的部署用 Parquet 可以按部署需要由你本地手动提交。

## 16. 当前版本限制

当前系统已经可以从 Wind 本地化主市场数据和期权链，并在 Streamlit 中展示真实数据结果。但它仍是研究系统，不是生产交易系统。

主要限制：

- 主因子仍是 v1 代表性口径，部分字段是 proxy。
- `yield_curve_slope` 依赖 Wind EDB 的 30Y/10Y 国债收益率；取不到时不会伪造。
- ETF 流入流出还没有接入真实份额或申赎数据。
- 融资余额只覆盖两只样本 ETF。
- A 股市场宽度暂用指数样本替代全市场上涨家数。
- 期权层没有真实交易商仓位，只能用 OI 和希腊值推导风险结构。

使用时应把它看作盘前风险环境仪表盘，而不是单独的买卖信号。

## 17. 2026-11-23 系统复核与改进顺序

本次从同一段沪深 300 行情重算了 2023-11-23 至 2026-11-23 的信号。726 个行情日对应 725 个可复盘信号。首日用于生成次日信号，最后一个信号面向 11 月 24 日，等待收盘后评价。

| 核对项 | 结果 |
| --- | --- |
| 日期对齐 | 使用 Wind 上交所日历后，可复盘样本从 705 天增至 725 天。2026 年国庆后首个信号采用 9 月 30 日境内收盘和 10 月 7 日海外收盘。 |
| ETF 资金参与 | 换用两只 ETF 分别披露的融资余额后，融资与成交额两个方向分的同期相关系数从 0.999998 降至 0.230。 |
| 三分类命中 | 收盘到收盘为 33.1%，始终中性的基准为 28.6%。开盘到收盘为 31.0%，相应基准为 28.8%。 |
| 大亏日预警 | 45 个大亏日中，40 天给出中性或防守，11 天明确给出防守。全样本有 176 次防守提示，随后大亏的比例为 6.25%，全部日期的大亏比例为 6.21%。 |
| 候选权重 | 滚动样本外验证共 29 折、599 天。候选收益分数的方向命中为 304/599，95% 区间为 46.8% 至 54.7%。生产权重继续沿用原配置。 |
| 看板响应 | 同一台 Mac 使用 Streamlit AppTest 测量，总览首次加载从 6.04 秒降至 0.66 秒。首次渲染的表格从 41 张降为 4 张。 |
| 美元流动性 | 净流动性统一使用百万美元。历史净流动性序列截至 2026-06-29，标普和纳斯达克对照图使用 Wind 历史收盘价。 |

美联储资产和 TGA 的原始单位是百万美元，隔夜逆回购的原始单位是十亿美元，计算时将后者乘以 1,000。[WALCL](https://fred.stlouisfed.org/series/WALCL) · [WTREGEN](https://fred.stlouisfed.org/series/WTREGEN) · [RRPONTSYD](https://fred.stlouisfed.org/series/RRPONTSYD)

### 接下来优先验证的三件事

1. **留存交易日 09:20 的实际判断。** 保存首次发布的信号、生成时间、快照编号、各因子实际参与权重和缺失市场。盘后重算结果单独对照。2026-11-23 晚的海外因子仅有韩国当日收盘，覆盖原设权重的 10%。两项海外风险都越过阈值，使次日预览从中性转为防守。首页标明覆盖比例及触发来源。
2. **用新的交易日复核硬风险规则。** 对同一批日期并行记录当前规则、关闭单项硬风险覆盖、始终中性这三种结果。按开盘到收盘收益、明确预警率、误报率和样本数比较，同时报告换手及成本假设。现有候选权重继续作影子对照。
3. **优先扩充独立数据。** 为 ETF 加入份额和净申赎，为市场宽度加入上涨家数，为期权连续保存三品种日终链。当前 Wind 期权链仅覆盖 11 月 20 日和 23 日，年度 IV 分位需要更长历史。
