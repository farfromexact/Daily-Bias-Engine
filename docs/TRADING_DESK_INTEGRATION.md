# 交易台接入与日内 GEX

Daily Bias Engine 提供两项独立的研究读数。市场风向来自已发布的 Wind 日度快照，作用域是 A 股整体。日内 GEX 按指数品种每五分钟估计一次，返回偏正、偏负或证据不足。两者各自携带行情时间和生成时间。

## 本机运行

激活项目虚拟环境，确认 Wind 已登录且本地已有上一交易日的标准期权链。在一个终端选择一种采集方式。

```bash
# 更新三个品种的最近已完成时段
python scripts/update_intraday_gex.py

# 复算指定品种的历史行情，按实际生成时间保存
python scripts/update_intraday_gex.py --product CSI300 --as-of 2026-11-23T14:55

# 连续采集，收齐一个五分钟窗口后更新，Ctrl+C 结束
python scripts/update_intraday_gex.py --watch
```

另开终端启动只读接口。默认绑定本机回环地址。服务和看板读取落盘快照，可以在 Wind 离线时使用。采集进程串行访问 Wind，原始盘口只在内存中处理，逐合约五分钟汇总缓存位于 `data/raw/wind/intraday_gex/`。已生成的品种报告位于 `data/options_wind/intraday_gex/`。

```bash
python -m daily_bias_engine.desk_api --port 8507
curl --noproxy '*' http://127.0.0.1:8507/v1/desk/context/IF
curl --noproxy '*' -G http://127.0.0.1:8507/v1/desk/context/IF \
  --data-urlencode 'as_of=2026-11-23T14:55:00+08:00'
```

看板默认链接指向 8506。若部署在其他端口或主机，启动接口时通过 `--dashboard-url` 填入交易台浏览器可访问的看板地址。接口还支持 `--snapshot-root` 和 `--options-root` 配置快照目录。

若交易台运行在另一台 Windows 机器，可将已授权的市场与品种快照同步到该机，在当地启动同一个只读接口。FastAPI 仍访问本机 8507。采集保留在登录 Wind 的主机上，盘中使用时把跨机传输时间计入延迟。

## HTTP 契约 v1

| 路径 | 用途 |
| --- | --- |
| `GET /healthz` | 进程存活及协议版本。行情可用性见下方每项读数的状态。 |
| `GET /v1/desk/context/IH` | 上证 50，SSE50 的 ETF 及股指期权 |
| `GET /v1/desk/context/IF` | 沪深 300，CSI300 的沪深 ETF 及股指期权 |
| `GET /v1/desk/context/IM` | 中证 1000，CSI1000 股指期权 |

三个品种端点都可接收一个 `as_of` 参数。无时区的时间按上海时间处理，响应使用带 `+08:00` 的 ISO 8601。无参数时取请求时刻。历史请求只返回该时刻之前**已生成**且行情截止不晚于查询时刻的快照。盘后补算的 14:55 报告可用于看板复盘，从它的实际生成时刻起才可用于接口回放。相同截止时刻如有修订，回放取当时可见的最新版。

| 字段 | 含义 |
| --- | --- |
| `schema_version`, `root`, `product`, `as_of` | 协议版本 1、期货品种、期权品种组、查询时点 |
| `market_bias` | `scope=A_share_market`，`benchmark=000300.SH`。三个端点共享这项市场背景。含 `bias`、`raw_bias`、`score`、`risk_override`、`signal_date`、`data_through`、`published_at`、`snapshot_id` 和海外成分 `overseas_components` |
| `intraday_gex` | `sign` 为 `positive`、`negative` 或 `indeterminate`。含 `reasons`、`window_start`、行情截止 `as_of`、生成时间 `computed_at`、`prior_chain_date`、`index_code` 和方法版本 `method` |
| `intraday_gex.flow` | `passive_change_rmb_per_1pct` 为样本已判向成交引起的被动方 GEX 净变化。单位为人民币元 / 标的变动 1%。`imbalance` 为净变化除以已判向总量，`classified_share` 为能判向的 Gamma 加权成交占比。分母为零时返回 JSON `null` |
| `intraday_gex.price_response` | 当天指数相邻一分钟收益相关系数 `lag1_return_corr`、有效收益对数 `return_pairs`、同时间段历史交易日数和四分位数 |
| `intraday_gex.coverage` | 分母是上一交易日仍存续、可定价合约的无符号 GEX。含样本合约列表及数量、选中份额、实际覆盖的窗口均值及末段值，比例均为 0–1 |
| `dashboard_url` | 指向同一合约组日内看板的深链接，页面可以选择历史行情和截止时间 |

市场风向 `status` 取 `same_day_snapshot`（信号日为当日）、`next_session_preview`（未来信号日的已发布预览）、`prior_session` 或 `unavailable`。信号日相同也应保留实际发布时间，判断 09:20 时可见的信号应明确传入当时的 `as_of`。

日度更新脚本在轮换完整 Wind 快照前，将其中已发布的风向与原始时间存入 `data/snapshots/market_bias_history/`。接口可继续按时间读取这些小记录。缺少留存记录的历史时段返回 `unavailable`。

日内 GEX 的 `status` 取 `recent`（同日且距观察截止最多 10 分钟）、`delayed`、`midday_close`、`session_close`、`prior_session` 或 `unavailable`。收盘状态表示记录的窗口截止时间。报告中的覆盖率另行描述实际到达的盘口和分钟线。无快照时对应对象仅保证返回 `status`，GEX 另返回 `sign=indeterminate`。客户端应接受空值。非法时间、未来时间或未知参数返回 400，未知品种或路由返回 404，快照读取失败返回 503。

`flow.sign` 和 `price_response.sign` 分别给出该项证据对 GEX 的指向，取 `positive`、`negative` 或 `unclear`。例如 `lag1_return_corr=+0.29` 表示指数涨跌偏延续，超过对应历史门槛时 `price_response.sign=negative`。界面采用顶层 `intraday_gex.sign` 作为综合结论。

| `reasons` 项 | 交易台显示 |
| --- | --- |
| `low_chain_coverage` | 窗口平均或末段有效覆盖不足 |
| `insufficient_signed_flow` | 能判向的成交或更新次数不足 |
| `balanced_flow` | 期权买卖净失衡未达门槛 |
| `unclear_price_response` | 指数回撤或延续证据不足 |
| `conflicting_evidence` | 成交与价格证据方向相反 |

## 交易台接线

1. 在 Trading Desk 的 FastAPI 后端读取本机端点，按当前股指期货的品种前缀 IH、IF、IM 映射。使用独立的小缓存，例如按品种 30 秒刷新一次，总超时 1 秒。研究接口的慢响应或故障只更新研究卡片的状态，行情、持仓和委托照常刷新。
2. 通过现有 `/api/market-context` 为 React 提供研究对象。在对应品种的市场背景面板并列显示「A 股盘前风向」和「日内做市商 GEX」，分别展示信号日、截止时间与方向。保留 `dashboard_url` 用于下钻查看证据。其他品种无需请求。
3. 实盘界面仅将 `recent` 标作盘中更新，延迟、午休、收盘和旧交易日各用独立文案。切换品种时按品种重新取数。接口离线时可显示同品种最后成功读数及时间，标记离线。没有读数时显示「暂无数据」，`indeterminate` 显示「证据不足」。回放模式使用回放时钟请求 `as_of`，单独标记回放。
4. 接入交易台的 Wind 采集时，由其已有 Wind worker 串行调度查询，或由独立研究采集进程在独占 SDK 时运行。前端轮询只读缓存。首轮验收覆盖三个品种切换、实时与回放、午休、旧交易日、接口超时和独立关闭研究服务。当前交付为研究系统侧接口及此接线方案。

## 判断如何产生

每次观察只用当时及此前的行情。按 Wind 交易日历取上一交易日链，排除已到期和零持仓合约，按无符号 GEX 排序，累计到可定价链的 50% 或最多 20 份。对所选合约使用当时 ETF 或指数的价格、前收隐含波动率和剩余到期时间重算 Gamma。每日 Options 页单独使用做市商全卖出情景。

逐笔行情中，累计成交量和成交额的差分给出这一笔更新内的总量与均价。用严格早于更新、最多 3 秒前的有效买一卖一判向。最后成交价和增量均价都落在卖一时记主动买，两者都落在买一时记主动卖。价差内、跨价成交、过期或交叉报价以及 14:57 起的成交保留为未分类。价格必须处于同一侧的要求会牺牲覆盖，换取较少的混合成交误判。[Lee 与 Ready，成交方向识别](https://doi.org/10.1111/j.1540-6261.1991.tb02683.x)

假设做市商是被动方，主动卖出认购或认沽都会增加其 Gamma。每张合约按 `Gamma × 标的价² × 0.01 × 合约乘数` 折算。已判向主动卖出减主动买入得到窗口净变化。将窗口内已观测但未判向的成交全数计到两侧，给出 `sample_change_low` 和 `sample_change_high`。这个范围只覆盖有效样本，期初持仓、交易对手身份和样本外敞口未知。

价格证据来自同一连续交易时段最近至多 60 分钟。比较今天相邻一分钟收益相关性与此前最多 20 个交易日同一时段。每个窗口至少 30 对有效收益且达到约 80% 完整度，历史至少 8 天。相关性低于历史下四分位且低于 −0.10，作为偏正 Gamma 的回撤证据。超过上四分位且高于 +0.10，作为偏负 Gamma 的延续证据。流动性、消息及其他交易流也能引起同样的价格反应。[Barbon 与 Buraschi，Gamma Fragility](https://alexandria.unisg.ch/entities/publication/b0c4de3d-74dd-4e62-b465-2d0337fe2904)

最终方向要求两类证据同向。窗口平均与末段实际覆盖各至少 40%，已分类 Gamma 成交至少 50%，已判向更新至少 20 次，净失衡绝对值至少 15%。任一条件未满足就显示「证据不足」并带原因。所有阈值属于首版研究规则。用连续留存的盘中快照做样本外检验时，可按流动性和到期日分层，比较随后 15–30 分钟价格延续或回撤与同时间段基准，同时报告可判定率。验证真实持仓符号还需要带交易者身份的独立持仓资料。

## 首批快照的时间口径

2026-11-23 的 14:55 与 15:00 均为盘后生成。初次测算用严格早于成交时间的盘口，随后复核时要求报价来自更早的一秒，以统一不同交易所的时间精度。两个版本保留各自的生成时间，看板展示同一截止时刻的最新版本。

以沪深 300 的 15:00 复核版为例，已判向期权净失衡为 −3.48%，指数相邻分钟收益相关系数为 +0.294，末段有效覆盖为 31.8%。接口返回 `sign=indeterminate`，原因是 `low_chain_coverage` 与 `balanced_flow`。查询当天 15:00 的历史可见版本时，GEX 返回 `unavailable`，符合实际发布时间。
