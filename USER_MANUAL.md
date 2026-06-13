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
- 总分、风向标签、趋势日概率、风险覆盖。

### 期权状态模块

期权模块读取 `data/options_ifind/` 下的期权链，支持：

- `SSE50`
- `CSI300`
- `CSI1000`

输出包括 GEX、vanna、charm、vega、关键行权价、IV、偏斜、风险分数和 overlay 建议。

### Streamlit 看板

Streamlit 是主要使用入口。它不会实时请求 iFinD，而是读取已经落地的本地快照。

### 脚本层

脚本负责把外部 API 数据本地化：

- `scripts/update_ifind_data.py`：日常总入口，增量更新主市场和期权数据。
- `scripts/fetch_ifind_snapshot.py`：更新主市场快照。
- `scripts/fetch_ifind_options_snapshot.py`：更新 iFinD 期权链。

## 3. 安装和环境准备

进入项目目录：

```powershell
cd "C:\Users\macon\Documents\Daily Bias Engine"
```

安装项目和测试依赖：

```powershell
python -m pip install -e ".[test]"
```

运行测试：

```powershell
pytest
```

iFinD 取数需要本机安装并可导入 `iFinDPy`，同时设置账号密码环境变量。不要把账号密码写入仓库文件。

PowerShell 示例：

```powershell
$env:IFIND_USERNAME="你的账号"
$env:IFIND_PASSWORD="你的密码"
```

这些变量只对当前 PowerShell 会话生效。

## 4. 推荐日常使用流程

每天更新数据并看结果的常规顺序：

1. 打开 PowerShell，进入项目目录。
2. 设置 iFinD 环境变量。
3. 运行日常增量更新脚本。
4. 启动或刷新 Streamlit。

日常总入口：

```powershell
python scripts\update_ifind_data.py
```

它会先增量更新主市场快照，再增量更新 `SSE50`、`CSI300`、`CSI1000` 期权链。没有新数据时会直接退出，不生成空快照。

查看将要更新的区间但不调用 iFinD：

```powershell
python scripts\update_ifind_data.py --dry-run
```

### 4.1 更新主市场快照

默认是增量优先：

```powershell
python scripts\fetch_ifind_snapshot.py
```

如果本地已经有 iFinD 快照，它只请求旧快照最新原始日期之后的新数据，然后与本地三年历史合并并重新计算完整 snapshot。如果本地没有 iFinD 快照，它会自动初始化最近三年。

指定截止日期：

```powershell
python scripts\fetch_ifind_snapshot.py --end 2026-06-12 --years 3
```

强制重拉三年全量：

```powershell
python scripts\fetch_ifind_snapshot.py --full-refresh --years 3
```

指定完整区间：

```powershell
python scripts\fetch_ifind_snapshot.py --start 2023-06-12 --end 2026-06-12
```

脚本会写入：

```text
data/snapshots/<生成时间>_ifind_<开始日期>_<结束日期>/
```

Streamlit 会自动读取 `data/snapshots/` 中生成时间最新的快照。

注意：即使 API 只增量取一天，模型计算仍使用合并后的历史数据，因为 5 日变化、20 日 z-score、60/120 日标签和诊断都需要历史窗口。

### 4.2 更新期权链

更新某一天全部产品：

```powershell
python scripts\fetch_ifind_options_snapshot.py --date 2026-06-12
```

更新某一天单个产品：

```powershell
python scripts\fetch_ifind_options_snapshot.py --date 2026-06-12 --product CSI300
```

更新一段区间全部产品：

```powershell
python scripts\fetch_ifind_options_snapshot.py --start-date 2026-01-01 --end-date 2026-06-12
```

更新一段区间的多个指定产品：

```powershell
python scripts\fetch_ifind_options_snapshot.py --start-date 2026-01-01 --end-date 2026-06-12 --product SSE50 --product CSI300
```

默认输出目录是：

```text
data/options_ifind/
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

当前仓库不再使用 GitHub Actions 自动调用 iFinD 取数。iFinD 数据更新由你在本地机器上手动执行，本地机器需要已经安装 iFinD 终端/API，并且当前 Python 能导入 `iFinDPy`。

本地日常更新入口：

```powershell
python scripts\update_ifind_data.py
```

这个脚本会增量更新主市场 snapshot 和 `SSE50`、`CSI300`、`CSI1000` 期权链，并只保留最近 2 个 iFinD 主市场快照。Streamlit Cloud 不直接调用 iFinD；它只读取 GitHub 仓库中已经提交的最新 parquet。

如果希望外网 Streamlit Cloud 也显示最新数据，本地提数后提交并 push：

```powershell
git add -f data\snapshots data\options_ifind
git commit -m "chore(data): update local iFinD snapshots"
git push
```

浏览器打开：

```text
http://localhost:8506/
```

如果页面仍显示旧数据，先刷新页面；如果仍旧，重启 Streamlit 进程。Streamlit 读取的是本地最新快照目录，不会在页面里直接调用 iFinD。

## 7. 如何确认数据已经更新

查看最新主快照：

```powershell
Get-ChildItem data\snapshots | Sort-Object Name -Descending | Select-Object -First 3 Name
```

用 Python 读取最新快照摘要：

```powershell
python -c "from pathlib import Path; import json; from daily_bias_engine.pipeline import list_snapshots; s=list_snapshots(Path('data/snapshots'))[0]; m=json.loads((s.path/'manifest.json').read_text(encoding='utf-8')); print(s.path); print(m['source'], m['start_date'], m['end_date']); print(m['latest'])"
```

查看期权数据日期：

```powershell
Get-ChildItem data\options_ifind\normalized_chain\product_group=CSI300 | Sort-Object Name -Descending | Select-Object -First 5 Name
```

生成单日 CSI300 期权状态 JSON：

```powershell
python -m daily_bias_engine.options.reports.daily_option_state --date 2026-06-12 --product CSI300 --data-root data\options_ifind
```

## 8. Streamlit 页面怎么看

### Overview

这是最常用页面。重点看：

- 信号日期：当前正在查看哪一天的盘前信号。
- 市场风向：`Risk-On`、`Neutral` 或 `Risk-Off`。
- 总分：`-100` 到 `+100`。
- 趋势日概率：系统认为当天可能走出趋势日的概率。
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

展示历史信号和事后市场结果的整体评估。

### Backtest Diagnostics

按风向、分数区间、趋势概率区间拆开看历史表现。

### Factor Diagnostics

逐个因子看和后续市场结果的关系，用于判断因子是否仍有解释力。

### Options

展示本地 iFinD 期权链计算出的状态，包括：

- regime：期权状态分类。
- key levels：spot、put wall、call wall、max gamma strike、zero gamma。
- exposures：GEX、vanna、charm、vega。
- vol：IV、RV、VRP、IV percentile。
- skew：put skew、call skew、risk reversal。
- recommended overlay：对主市场仓位的期权 overlay 建议。

### Logic

展示因子逻辑说明。若发现文字编码异常，以本文档和代码为准。

## 9. 主市场分数怎么理解

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

趋势日概率不是方向预测。它回答的是“当天是否更可能走出趋势结构”，而不是“涨还是跌”。趋势方向由 `trend_direction_bias` 单独表示。

## 10. 当前主因子清单

| 因子 | 模块 | 原始含义 | 方向 |
| --- | --- | --- | --- |
| `equity_index_futures_basis` | 股指期货结构 | IF 连续合约相对沪深300现货的基差 | 基差改善偏 Risk-On |
| `futures_open_interest_momentum` | 股指期货结构 | IF 持仓量 5 日变化 | 持仓回升暂偏 Risk-On |
| `rates_change_5d` | 利率 | `DR007.IB` 5 日变化 | 利率上行偏 Risk-Off |
| `yield_curve_slope` | 利率 | iFinD EDB 30Y 国债收益率 - 10Y 国债收益率 | 曲线变陡暂偏 Risk-On |
| `etf_flow_proxy` | ETF/资金流 | 510300、510500 成交额 5 日变化 | 成交额回升偏 Risk-On |
| `margin_balance_momentum` | ETF/资金流 | 当前由 ETF 成交额派生的两融 proxy | proxy 回升偏 Risk-On |
| `overseas_market_momentum` | 海外隔夜 | 美国、日本、韩国指数的加权单日涨跌 | 海外上涨偏 Risk-On |
| `overseas_volatility_pressure` | 海外隔夜 | 美国、日本、韩国指数加权日内振幅 | 波动放大偏 Risk-Off |
| `ashare_breadth_proxy` | A 股结构 | 上证50、沪深300、科创50、创业板指上涨比例 proxy | 扩散改善偏 Risk-On |
| `ashare_turnover_momentum` | A 股结构 | 上证50、沪深300、科创50、创业板指成交量 5 日变化 | 成交回升暂偏 Risk-On |

注意：

- `proxy` 不是假数据，而是指因子口径是替代变量。
- 海外隔夜当前使用 `SPX.GI`、`N225.GI`、`KS11.GI`，权重分别为美国 80%、日本 10%、韩国 10%；如果某个市场当日缺数据，则按当日可用指数的权重重新归一。
- A 股市场宽度当前使用 `000016.SH`、`000300.SH`、`000688.SH`、`399006.SZ`，对应上证50、沪深300、科创50、创业板指。
- 期限利差使用 `L001618299`（中债国债到期收益率:30年）减 `L001619604`（中债国债到期收益率:10年）；取不到真实 EDB 时不会伪造。
- `margin_balance_momentum` 当前还不是两融真实余额，是用 ETF 成交额派生的 proxy。

## 11. 期权状态怎么理解

期权状态命令：

```powershell
python -m daily_bias_engine.options.reports.daily_option_state --date 2026-06-12 --product CSI300 --data-root data\options_ifind
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

## 12. 本地数据目录

| 目录 | 用途 | 是否应提交 Git |
| --- | --- | --- |
| `data/snapshots/` | 主市场快照，Streamlit 主模块读取 | 否 |
| `data/raw/ifind/` | iFinD 原始请求缓存 | 否 |
| `data/options_ifind/` | iFinD 期权链，Streamlit 期权模块读取 | 否 |
| `.streamlit_logs/` | 本地 Streamlit 日志 | 否 |

这些数据目录通常在 `.gitignore` 里忽略。仓库提交代码和配置，不提交本地行情数据和账号密码。

## 13. 常见问题

### 页面提示没有本地市场快照

先运行：

```powershell
python scripts\fetch_ifind_snapshot.py
```

然后重启或刷新 Streamlit。

### Options 页面没有数据

先运行：

```powershell
python scripts\fetch_ifind_options_snapshot.py --date 2026-06-12
```

如果看的是历史日期，把 `--date` 改成对应交易日。

### 提示 iFinD credentials are required

当前 PowerShell 没有设置账号密码环境变量。重新设置：

```powershell
$env:IFIND_USERNAME="你的账号"
$env:IFIND_PASSWORD="你的密码"
```

### iFinD 登录或导入失败

检查：

- 本机是否安装 iFinD 终端/API。
- 当前 Python 环境是否能 `import iFinDPy`。
- 账号密码是否有效。
- iFinD 授权是否过期。

### 期权拉数中间失败

区间拉取时，脚本会记录失败日期和产品。可先不加 `--fail-fast`，让可成功的日期先落地。修复后再对失败日期单独重拉：

```powershell
python scripts\fetch_ifind_options_snapshot.py --date 2026-06-12 --product CSI300 --overwrite
```

### Streamlit 端口被占用

换端口：

```powershell
python -m streamlit run apps\streamlit_app.py --server.port 8507
```

### 页面看起来还是旧数据

确认最新快照是否已经写入 `data/snapshots/`。如果已经写入，刷新页面；仍旧则停止 Streamlit 后重新启动。

## 14. 开发和校验

跑完整测试：

```powershell
pytest
```

只校验主要文件语法：

```powershell
python -m py_compile apps\streamlit_app.py scripts\fetch_ifind_snapshot.py scripts\fetch_ifind_options_snapshot.py scripts\update_ifind_data.py
```

查看 Git 状态：

```powershell
git status --short
```

提交前确认不要把以下内容加入 Git：

- 真实账号密码。
- `data/raw/ifind/` 原始请求审计缓存。
- 本地日志文件。

`data/snapshots/` 和 `data/options_ifind/` 中的公开 parquet 可以按部署需要提交；GitHub Actions 会自动提交这些数据更新。

## 15. 当前版本限制

当前系统已经可以从 iFinD 本地化主市场数据和期权链，并在 Streamlit 中展示真实数据结果。但它仍是研究系统，不是生产交易系统。

主要限制：

- 主因子仍是 v1 代表性口径，部分字段是 proxy。
- `yield_curve_slope` 依赖 iFinD EDB 的 30Y/10Y 国债收益率；取不到时不会伪造。
- ETF 流入流出还没有接入真实份额或申赎数据。
- 两融余额仍是 proxy。
- A 股市场宽度暂用指数样本替代全市场上涨家数。
- 期权层没有真实交易商仓位，只能用 OI 和希腊值推导风险结构。

使用时应把它看作盘前风险环境仪表盘，而不是单独的买卖信号。
