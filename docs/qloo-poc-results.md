# Qloo PoC Results and Evidence Index

日期：2026-10-14（Asia/Shanghai）。核心 PoC 已完成，完整结果与限制见 [能力报告](qloo-capability-report.md)。

## 真实实验

- 官方 Harness 0.1.26 的 10 次工作流：6 个 ok（4 组标签、2 城地理基线）；4 个 needs_input（同名实体歧义），没有将 exit 0 当作推荐成功。
- 原始 HTTP 共 30 次尝试（包含无 Key 对照、3 次限时重试及 8 次明确半径补测）：25 次 HTTP 200、1 次 400、1 次无 Key 401、3 次初始 transport/parse failure。失败请求也可能已经被服务端处理，不能直接用此数计算额度消耗。
- 确认 artist 与 movie 消歧 ID 后，音乐→电影和电影→音乐各 HTTP 200、5 条候选。两城兴趣地点对照均改变候选；地名 raw 基线与音乐人兴趣候选的 top-5 ID 交集均为 0。不是用户满意度提升证明。
- 纽约地名过滤实际解析为州；两组兴趣标签重试结果含 4/5 城市外候选。明确坐标 20km 过滤补测全部成功，返回坐标距离符合范围。
- 明确半径实验：上海独立书店 0、咖啡 2；纽约附近独立书店 4（含 Hoboken）、咖啡 5。只代表这组参数的小样本。
- 布尔参数最初编码为 False，得到 HTTP 400；修正为 lowercase false 后空标签查询 HTTP 200、0 条。旧失败证据保留。
- 响应限额：5/秒、10,000/月；末次成功月度剩余 9,961（动态快照）。没有压测 429/5xx，没有验证 Key 精确停用时间。

## 私有原始证据

全部位于 `.qloo-private/`，不可提交公开仓库。无 Key 值，目录 0700、文件 0600。

| 文件组 | 内容 |
|---|---|
| summary.json / tags-*.json | 首轮工作流统计和兴趣标签响应 |
| jazz-to-movie.json / scifi-to-artist.json | 同名消歧候选和 needs_input |
| resolved-*.json | 使用审核 ID 的跨领域 HTTP 200 |
| *-raw-*.json / followup-summary.json | 城市基线与实体/标签信号 raw 查询 |
| *-filter-*.json / focus-summary.json | setting/cuisine 地点过滤 |
| *-retry.json / retry-summary.json | 3 次 20s 失败请求的单次 45s 重试 |
| empty-tag-query.json | 旧的布尔编码失败 HTTP 400 |
| empty-tag-query-valid.json / empty-summary.json | 修正后的真实空结果 |
| auth-control.json | 没有 Key 的 HTTP 401 对照 |
| *-point-*.json / point-summary.json | 明确坐标 20km 范围复核 |

文件记录实际输入、GET 路径、参数、HTTP 状态、限额请求头和原始结果；summary 含时间戳与客户端耗时。CLI raw 与 normalized envelope 不同，具体字段路径已在能力报告核实。

## 安全与未完成项

凭据通过用户本地 `.env.local` 中 APIKey 读取，仅在请求头或子进程环境中使用。已执行合成 token 回显检查和项目文件逐值扫描：没有发现 Key 被复制到代码、文档或私有响应。公开 fixtures 明确标为 synthetic，不作真实成功证据。

尚未独立核验商家营业、活动场次、价格、时区、坐标基准、路线及公众可访问性；尚未验证 429/5xx 行为。不得将 Qloo 候选直接描述为“今天可以去、预算符合、活动正在举行”。
