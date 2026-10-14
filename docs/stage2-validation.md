# Stage 2 — Agent Core Validation

日期：2026-10-14（Asia/Shanghai）。**核心闸门通过：已有真实 DeepSeek → Qloo → 地点检查 → 排序 → 3 张探索卡片的可复现链路。** 这不代表实时营业、预算、活动场次或路线已验证；结果状态为 `partial`。

## 实际实现

- Python 3.12 标准库核心与 CLI，无运行时第三方依赖。未覆盖 PoC 文件，未初始化 Git、提交或部署。
- DeepSeek JSON 意图提取、严格字段/类型验证；坐标必须由调用方明确提供，模型不能生成实体 ID 或地点。
- Qloo 服务器固定为赛事地址；真实 `/search`、`/v2/tags` 与 `/v2/insights`。名称/类型不唯一则 `needs_input`，只有当前候选内的 ID 可确认。
- 使用明确 WKT 点与半径，检查返回坐标实际距离；不使用会把纽约解析为州的地名过滤。
- 类别、关闭标记、地址/坐标缺失、半径、排除项、去重和显式历史过滤；不因亲和度高绕过硬约束。
- 至多检查 6 个 Qloo 提供的网站；限制大小/超时/跳转，校验所有 DNS 地址为公网并固定 TLS 连接 IP，网页只提取文本，不执行脚本或作为模型指令。
- 网站能对应名称时仅标记 `website_name_corroborated`，不是分店、实时营业或活动验证。失败不展示未经检查的可点击 URL。
- 根据名称证据和同请求内 rank 排序，类别多样性控制；不跨请求比较 affinity。最多 3 张带来源和不确定性卡片。
- Qloo 单客户端网络调用最多 14 次、至少间隔 300ms、最多重试一次、300s 内存缓存、月度剩余 <=10 保留额；当前仅进程内保护，尚无公共 Demo 的全局限额机制。
- 安全错误分类，区分 `error`、`empty`、`needs_input`、`partial`。缓存和网络结果有不同 source 标签与逐次工具记录。

状态链为 `INTENT_PARSED → TASTE_RETRIEVED → CANDIDATES_CHECKED → RANKED → PRESENTED`；刻意使用 CHECKED 而非声称所有现实约束 VERIFIED。

## 真实验证

自然语言：“我在纽约，喜欢 Miles Davis，想探索独立书店，避免商场和酒店。”提供明确的纽约区域坐标，半径 10km。

- DeepSeek v4-pro HTTP 200；提取 city=new_york、artist 兴趣、bookstore 类别与 mall/hotel 排除项，未编造预算/时间。
- 成功运行共 3 次 Qloo 请求（类型限定实体搜索、场所标签查询、Insights），返回 4 个原始候选，经检查呈现 3 张卡片。
- 3 张卡片中 2 个网站可对应名称，1 个网站不可达；所有卡片的实际预算、实时营业、公众访问和行程时间仍为 unverified。
- Pro 此次意图解析 usage：416 prompt tokens、116 completion tokens、532 total tokens；服务端回报模型 deepseek-v4-pro。未推算美元费用。
- 用户授权自行选择 Pro/Flash。另以官方当前 Flash 标识 deepseek-flash 实测预算/时间输入，HTTP 200，正确提取 USD 50、180 分钟、open_now=true、bookstore；426 prompt +84 completion =510 total tokens。
- 官方文档说明 legacy deepseek-v4-flash 当前路由至新版 Flash。代码允许官方当前名和旧名，记录请求名与回报名；没有暗中切换供应商或凭据。

另运行一次使用已审核模型 intent 的核心验证器：重新请求 3 次 Qloo 后，共享私有内存缓存测试三条分支。

| 分支 | 实际结果 |
|---|---|
| 文化兴趣 + 附近书店 | 3 张 partial 探索卡片 |
| 加入 USD 50、180 分钟、现在营业 | empty；未知成本/访问时间/即时营业拦截全部候选 |
| 排除首轮已展示的 3 个 ID | 返回剩余 1 个；没有重现被排除 ID |
| 两条后续分支 | 没有增加 Qloo 网络调用，cache hit 在工具记录中可见 |

这些排除 ID 是验证器的显式测试反馈，不代表真实用户曾到访。无历史时结果的 novelty 为 unknown，系统不会宣称必然新颖。

## 发现并修复的集成问题

前两次整链路尝试没有返回卡片，保留了失败证据：

1. `/search` 实际 `results` 为数组，与 Insights 的 `results.entities` 不同；初版归一化拒绝了该结构，已修正。
2. Search 实体类别实际在 `types[]`，与 Insights 的 `subtype` 不同；初版正确拒绝未确认类型，补充类型归一化后成功。

这两项是适配器问题，不是 API 鉴权或数据覆盖失败。没有把错误隐藏为静态示例。

## 自动检查与证据

执行：

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m cityplay --query '<public cultural request>' --lat <LAT> --lon <LON> --radius-m 10000
PYTHONPATH=src python3 scripts/validate_stage2.py --source <successful-private-run.json>
```

测试为合成数据，不依赖真实 Key；覆盖硬约束、同名确认、类别/位置/历史过滤、缓存标签、401、429、503、网络失败、调用额度、SSRF、模型字段验证及凭据 repr。

真实完整结果与模型统计保存在 Git 忽略的 `.qloo-private/stage2/`，文件 0600、目录 0700。公开文档只记审核后统计/结构，不保存真实 Qloo 实体列表或网页正文。最终 26 项合成测试全部通过；Qloo/DeepSeek 两个 Key 的逐值文件扫描通过，Python 语法、私有 JSON 有效性及 0600 权限检查通过。验证器再次实测缓存标签正确，3 次网络调用产生 3 张初轮卡片、0 张硬约束卡片、1 张反馈后卡片。

## 后续闸门

下一阶段可以接 Web 输入、结构化意图确认、消歧选择、来源/不确定性卡片和换一批。暂不能把 partial 改成“现在可去”：需要授权地点/官网的分店及营业、活动、费用和路线核验。严格市内边界、地图坐标基准和公开 Demo 的共享限额也尚未实现。

模型语义抽取仍需用户确认；schema 校验不能证明其理解所有自由文本。常见明确预算/时间/现在营业/市内边界/酒店与商场排除若被模型漏提取，规则守卫会要求澄清；未知运营条件会拦截，其他复杂条件必须在意图确认界面暴露，不能悄然忽略。

官方模型依据：[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)、[Models](https://api-docs.deepseek.com/api/list-models/)、[First API Call](https://api-docs.deepseek.com/guides/codex)。
