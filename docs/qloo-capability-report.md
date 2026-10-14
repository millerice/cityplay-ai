# Qloo Capability Report — Stage 1

核验日期：2026-10-14（Asia/Shanghai）。**真实鉴权、兴趣标签、跨领域推荐和上海/纽约初步覆盖已验证；具体请求与统计见下表。** 本报告不将候选当作已核验可访问场所，不预设完整城市覆盖。

## 环境与 Starter Kit 审查

已阅读交接文档 v1.1。项目初始仅有交接文档，无应用代码、依赖、Git 仓库或适用 AGENTS.md；未初始化 Git、提交或部署。Node v24.18.1、npm 11.16.0、Python 3.12.11。官方要求 Node >=22.19.0、Harness >=0.1.26；已隔离安装 Harness 0.1.26 于 `/tmp/cityplay-qloo-tools`，未修改全局 npm，安装禁用 lifecycle scripts。

已审查官方 README、CLI Workflow Starter、API_ACCESS、SAFE_USE、SUBMISSION、开发指南、Entity Type Parameter Guide、Parameter Reference，并核对已安装 Harness 工作流和 HTTP client 代码。部分 raw GitHub 请求超时，后通过 GitHub 网页取得内容；开发指南与参数文档通过官方 `.md` 页面读取。开发指南更新时间为 2026-10-07。

官方来源：

- [Hackathon Developer Guide](https://docs.qloo.com/reference/qloo-llm-hackathon-developer-guide)
- [Starter Kit](https://github.com/qloo/qloo-hackathon-kit) / [CLI Workflow Starter](https://github.com/qloo/qloo-hackathon-kit/blob/main/starter/cli-workflow/README.md)
- [API Access](https://github.com/qloo/qloo-hackathon-kit/blob/main/docs/API_ACCESS.md) / [Safe Use](https://github.com/qloo/qloo-hackathon-kit/blob/main/docs/SAFE_USE.md) / [Submission](https://github.com/qloo/qloo-hackathon-kit/blob/main/docs/SUBMISSION.md)
- [Entity Type Parameters](https://docs.qloo.com/reference/available-parameters-by-entity-type) / [Parameter Reference](https://docs.qloo.com/reference/parameters)

## 服务器、凭据与证据保存

固定赛事服务器 `https://hackathon.api.qloo.com`；Harness 同时设置 `QLOO_BASE_URL` 和 `QLOO_TRUSTED_BASE_URL`，不回退 production/staging。GET 请求使用 `X-Api-Key` header；不将 Key 放 query、argv、源代码、聊天或日志。

用户本地 `.env.local` 的变量名为 `APIKey`，包装脚本将其在内存中映射为标准 `QLOO_API_KEY`。也支持标准变量名。文件权限设为 0600；`.gitignore` 忽略 `.env*`、编辑器 swap 和 `.qloo-private/`。脚本只打印状态和统计，不打印 Key 或完整响应。原始 JSON、请求参数及消歧候选保存于私有目录（0700 / 文件 0600），响应持久化前移除 Key 值；原始 HTTP 客户端拒绝重定向。没有读取邮件或发送个人资料。

官方指南明确禁止在公开仓库保存 Qloo response data，即使 Key 已脱敏。因此真实 fixture 留在本地，公开 fixture 仅为明确标记的合成数据。本报告只保留审核后的实验统计、结构和产品结论，不复制实体列表或描述。

## 真实请求与工作流

`qloo exec find_tags` 已成功：`jazz`、`indie bookstore`、`science fiction`、`coffee`，每组 limit=5，各返回 5 条。语义检索提供多个不同类型的候选；需人工确认兴趣标签、场所标签、音乐 genre 的用途，不能直接选第一项。

- `find_tags` → GET `/v2/tags`：`filter.query`、`feature.semantic_search=true`、`take`。
- 名称推荐先调用 `/search`。Miles Davis 同名 artist/person、Blade Runner 同名 movie/album/artist 导致 Harness `needs_input`，CLI exit=0；exit=0 不能单独视为推荐成功。
- 已人工确认 Miles Davis 的 **artist** 候选和 Blade Runner 的 **1982 movie** 候选，再从私有响应读取 ID；没有编造或硬编码实体 ID。
- GET `/v2/insights`：`filter.type=urn:entity:movie` + 音乐人 ID，和 `filter.type=urn:entity:artist` + 电影 ID，均 HTTP 200、各返回 5 条；证实音乐→电影、电影→音乐的跨领域关联。
- 首次两城地点对照使用 `filter.type=urn:entity:place`、`filter.location.query`、`filter.location.radius=0`、`take=5`。基线仅过滤城市，实验组分别增加实体/标签兴趣信号，比较同一城市候选是否变化。
- 地点标签实验额外增加 `filter.tags`；兴趣信号与硬类别过滤是不同用途。

真实状态表（延迟为客户端观测，包含网络；CLI 还包含进程启动和 resolver，不宜互相比较）：

| 实验 | 真实状态 / HTTP | 返回数 | 耗时 ms |
|---|---|---:|---:|
| tags-1 | ok | 5 | 3897 |
| tags-2 | ok | 5 | 3243 |
| tags-3 | ok | 5 | 2646 |
| tags-4 | ok | 5 | 2064 |
| jazz-to-movie | needs_input | — | 3437 |
| scifi-to-artist | needs_input | — | 3062 |
| shanghai-baseline | ok | 5 | 3171 |
| shanghai-jazz | needs_input | — | 1902 |
| new-york-baseline | ok | 5 | 13137 |
| new-york-jazz | needs_input | — | 2510 |
| resolved-jazz-to-movie | 200 | 5 | 5372 |
| resolved-scifi-to-artist | 200 | 5 | 5967 |
| shanghai-raw-baseline | 200 | 5 | 3007 |
| shanghai-raw-miles | 200 | 5 | 2507 |
| shanghai-raw-jazz-tag | 200 | 5 | 4949 |
| shanghai-raw-bookstore-tag | 200 | 5 | 2716 |
| shanghai-raw-coffee-tag | 200 | 5 | 6266 |
| new-york-raw-baseline | 200 | 5 | 4846 |
| new-york-raw-miles | 200 | 5 | 8729 |
| new-york-raw-jazz-tag | transport_or_parse_error | — | 21265 |
| new-york-raw-bookstore-tag | transport_or_parse_error | — | 21004 |
| new-york-raw-coffee-tag | transport_or_parse_error | — | 20832 |
| empty-tag-query | 400 | — | 649 |
| shanghai-filter-bookstore | 200 | 0 | 762 |
| shanghai-filter-coffee | 200 | 2 | 1572 |
| new-york-filter-bookstore | 200 | 3 | 3047 |
| new-york-filter-coffee | 200 | 5 | 2187 |
| new-york-raw-jazz-tag (retry) | 200 | 5 | 11970 |
| new-york-raw-bookstore-tag (retry) | 200 | 5 | 20763 |
| new-york-raw-coffee-tag (retry) | 200 | 5 | 12468 |
| empty-tag-query-valid | 200 | 0 | 1033 |
| shanghai-point-baseline | 200 | 5 | 3445 |
| shanghai-point-miles | 200 | 5 | 1569 |
| shanghai-point-bookstore | 200 | 0 | 1150 |
| shanghai-point-coffee | 200 | 2 | 2213 |
| new-york-point-baseline | 200 | 5 | 2597 |
| new-york-point-miles | 200 | 5 | 2930 |
| new-york-point-bookstore | 200 | 4 | 2491 |
| new-york-point-coffee | 200 | 5 | 2349 |

初始缺凭据时脚本 exit 4、未发请求；不是 API 401。随后已配置 Key 完成真实测试。无 Key 的独立对照请求实测 **HTTP 401**；返回 reason 表明请求没有 API Key，证明鉴权机制有效。

## 初步城市覆盖与产品含义

| 地名过滤、最多 5 条样本（纽约过滤实际为州） | 上海 | 纽约州 |
|---|---:|---:|
| 仅城市过滤 | 5 | 5 |
| 已确认爵士音乐人实体信号 | 5 | 5 |
| 同信号 + 独立书店 setting 标签过滤 | 0 | 3 |
| 同信号 + Coffee cuisine 标签过滤 | 2 | 5 |
| 音乐人信号结果有坐标 / 有地址 | 5/5、5/5 | 5/5、5/5 |
| 音乐人信号结果有非空 hours | 0/5 | 3/5 |
| 独立书店过滤结果有非空 hours | 无结果 | 3/3 |
| 咖啡过滤结果有非空 hours | 2/2 | 5/5 |

上海解析为上海；**`New York, NY` 实际解析范围为纽约州**，locality 中心在约 42.92 纬度。重试后的纽约书店/咖啡兴趣样本各有 4/5 位于纽约市以外，不可称为 NYC 候选。响应结构实际为 `query.localities.filter[]`（指南有页面写成其他 locality 路径，应以实测为准）。上海地点样本地理信息与上海总体范围相符；纽约部分样本证明仅靠地名字符串不能可靠约束城市。已追加官方 WKT POINT + 20,000 米半径实验，中心来自此前真实地点坐标，不编造经纬度。这是局部范围覆盖，不代表行政边界或全城覆盖。

上海基线 5 条有 4 条酒店；音乐人信号 5 条中 3 条酒店、1 条餐饮、1 条旅游景点。纽约音乐人信号 5 条包含 2 条录音室、2 条现场音乐场所、1 条乐器店。**兴趣信号确实改变候选，但文化亲和不意味着场所向公众开放或符合具体活动需求。**

上海独立书店兴趣信号返回酒店/餐饮，不是独立书店；coffee 兴趣信号与书店兴趣信号在本次上海样本给出同一有序候选及相同 affinity，不能据此声称个性化区分充分。独立书店 setting 硬过滤结果为 0，只能证明这一参数组合没有候选，不能宣称上海没有书店。

咖啡硬过滤也可能包含综合场所，例如纽约样本的主类别含酒吧和服饰店；要检查复合用途与真实可访问体验。上海咖啡过滤仅 2 条且为同一大型连锁相关场所，不足以支持“隐秘小众咖啡”承诺。

上海某样本 address 的区名与 geocode 的区名不同；元数据存在内部不一致。不能将所有地址/行政区字段当作已核实事实。上海营业时间缺失较多；纽约相对更适合先做可演示闭环，但不代表全球或全城覆盖完整。


### 明确坐标半径复核

因纽约地名歧义追加 WKT POINT + 20,000 米实验，中心分别来自两城此前真实基线地点坐标；**定义为附近范围，不是行政边界**。8 次请求均 HTTP 200；按返回经纬度计算球面直线距离，全部落在 20 公里范围内。

| 20 公里范围、take=5 | 上海中心附近 | 纽约中心附近 |
|---|---:|---:|
| 无兴趣基线 | 5 | 5 |
| 爵士音乐人信号 | 5 | 5 |
| 同信号 + 独立书店标签 | 0 | 4 |
| 同信号 + 咖啡标签 | 2 | 5 |
| 独立书店结果有 hours | — | 4/4 |
| 咖啡结果有 hours | 2/2 | 5/5 |

纽约附近书店含 Hoboken 候选，符合坐标半径，**不属于 NYC 行政范围**。若用户要求严格城市内，应另加确认过的行政边界核验。纽约附近音乐人信号 5 条均在约 5.3 公里以内，上海该组最远约 15.8 公里；这些是本地计算的直线距离，不是路线距离或交通时间。

## 实测 raw 字段与归一化限制

- 顶层 `success`、`results.entities[]`；有地理解析时 `query.localities.filter[]`。
- 实体 `entity_id`、`name`、`type`、`subtype`；实测 `type=urn:entity`、`subtype=urn:entity:place/movie/artist`。不要用 `type` 单字段判断类别。
- 亲和度位于 `results.entities[].query.affinity`；**不带兴趣信号的城市 raw 基线没有 affinity**。它不是个人喜好概率，也不能跨查询/跨类别直接比较。
- 坐标位于实体顶层 `location.lat/lon/geohash`；不在 `properties.geocode`。Harness compactEntity 丢弃顶层 location，不可据 CLI 简化输出断言没有坐标。
- 地点属性实测 `properties.address/geocode/hours/is_closed/website/primary_genre/price_level/price_range` 等。字段存在不等于有值；`price_range` 常是 `{from:null,to:null,currency:...}`，不能将非空对象当作已知价格。
- 音乐人信号样本：上海只有 1/5 具有数字价格边界、纽约 0/5；全部独立书店和咖啡过滤候选都没有数字价格边界。`price_level` 是等级，不能替代实际预算或票价。
- 非空 hours 是周营业表，存在跨午夜时段；没有独立确认时区、特殊营业日或实时营业状态。`is_closed=false` 不等于现在营业。
- Harness 声明 normalized schema `1.0-preview.1`、status/results/execution/provenance；该 envelope 与 raw schema 不同。既要保留原始字段路径，也要识别 `needs_input` 和空数组。
- 初次 CLI recommend 的 `feature.explainability=true` 未提供足以形成可靠解释的可用内容；不能承诺每条推荐有官方自然语言因果说明。

## 配额、故障与接口限制

真实响应头观察到 `X-Second-RateLimit-Limit=5`、`X-Month-RateLimit-Limit=10000`。末次成功响应月度剩余 9,961、秒级剩余 4；剩余量与 reset 值是动态快照，原值保存在私有响应文件；精确月度计费边界和 Key 停用日期仍 UNKNOWN。官方定性说明 Key 在评审结束后停用。

三次纽约标签 raw 请求在 20 秒预算内出现 transport/parse failure，没有 HTTP 状态，不能归因于服务器错误或城市无覆盖。各仅做一次 45 秒预算重试，三次重试均 HTTP 200、各 5 条；其中两组出现上述跨城市泄漏，结果见表。未压测；未实际触发 429、5xx。Harness client 代码默认单次 20 秒、最多 3 attempts、可重试 429/500/502/503/504、retry delay 上限 30 秒；PoC CLI 外层工作流 60 秒。直接 HTTP 实验不自动重试，重试实验显式限一次。

负向空标签实验最初出现 HTTP 400：Python query 将 boolean 编成 `False`，服务器要求 lowercase boolean。已修复为 `false/true`；保留原失败证据，修正后 HTTP 200、返回 0 条，另存原始证据，不覆盖旧失败结果。

官方指南提醒无效参数可能被静默忽略；HTTP 200 不足以证明过滤生效。此次通过 locality 解析、字段值及基线对照核验。旧 `/recs`、`/recommendations` 不支持；推荐只用 GET `/v2/insights`。API 不提供响应字段投影；在服务端提取所需数据。

## 后续实施建议与阶段闸门

**阶段 1 核心闸门通过：鉴权成功，有真实跨领域信号，完成双城初步覆盖和限制调查。** 地点营业现状/活动场次/路线时间/实际预算验证仍未完成；不作为本阶段已验证能力。

建议 CityPlay V1 以纽约及明确半径的周边范围作为主要演示区域，上海保留实验模式与数据不足提示；理由是此次样本的兴趣相关地点与营业表更充分，不是预设美国覆盖更好。上海功能仍可做，但不能直接承诺小众书店或独立咖啡推荐。

具体闭环：兴趣解析 → 按类型/年份消歧并允许用户确认 → 获取兴趣相关地点 → 场所类别及公众可访问性检查 → 使用授权地点/官网来源核验营业、预算和活动 → 提供 3 个带来源与确定性状态的建议。Qloo 负责文化关联及候选，现实可行性使用独立证据；无依据时留空或提示不足。

使用保留顶层坐标的服务端 HTTP 适配器是可行候选；CLI 保留作调查/复现工具。暂不构建完整 Web 脚手架。排序先用硬约束、去重与类别多样性，再使用同一请求内相对亲和；不先写伪精确综合评分。预算/时间信息不足的候选不能因 affinity 高而通过。

下一阶段需明确：授权地点核验数据源、费用与使用条款；坐标基准及地图兼容；真实营业核验；实体/标签确认 UI；服务端限额/缓存/超时与失败提示；评审期后的 Key 失效策略。上海扩大覆盖需要选择其他已验证类别与本地核验来源，不能将 0 条测试解释成整城不可用。

复现：

```sh
python3 scripts/qloo_poc.py --cli /tmp/cityplay-qloo-tools/node_modules/.bin/qloo
python3 scripts/qloo_followup.py
python3 scripts/qloo_followup.py --focus
python3 scripts/qloo_followup.py --retry-timeouts
python3 scripts/qloo_followup.py --empty-only
python3 scripts/qloo_followup.py --point
```

临时 Harness 目录清理后需重新安装或换成可用 qloo 路径。followup 依赖首次消歧/标签证据；候选变化时拒绝猜测选择。原始数据只在 `.qloo-private/` 内审核。安全包装已通过合成 token 回显测试：argv 无 Key、stdout/stderr 与落盘内容脱敏、服务器固定、私有权限正确；不将安全合成测试冒充 API 实验。

## 追加：CityPlay数据价值对照

同日完成25次真实Qloo请求、两城20组固定10km/take10对照及6个网站抽查。参见[数据价值验证报告](cityplay-data-value-report.md)。该轮区分兴趣信号与标签筛选，并单独统计目标类别匹配；不与此前take5实验合并为覆盖总量。
