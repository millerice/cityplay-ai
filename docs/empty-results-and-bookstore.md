# 空结果诊断与书店过滤修正

2026-10-14。原“条件保留了，证据还不够”统一提示错误地混淆了API未返回地点、类别过滤、营业/费用证据不足，以及本轮已展示等情形。

引擎新增diagnostics：retrieved_count、rejection_counts（仅计数，不公开被排除地点ID）、empty_reason。Web接口传递诊断，页面分别显示“查询未返回地点”“返回地点但条件未匹配”“本轮地点已展示”。明确区分缓存重复查询与扩大范围，不把0结果解释成整城无地点。

真实/v2/tags查询验证Book store（urn:tag:category:place）与Independent Bookstore（urn:tag:setting:qloo）存在区别。通用bookstore兴趣及书店过滤使用动态解析的普通类别标签；没有硬编码真实ID。原独立书店限定仅在原用户明确写独立/independent/indie bookstore或相应兴趣信号时采用。Web会话保留原输入中的独立书店限定，确认界面仍沿用现有bookstore类别，不引入新协议；修改限定需重新解析原需求。

无兴趣信号的真实类别基线：10km附近、take5，上海1个候选，主类别Craft store；纽约5个，主类别包括Book store和Comic book store。当前保守的书店类别白名单仍为Book store/bookstore，漫画专门店尚未扩展。基线统计不能当作最终推荐数量。

真实浏览器“上海/喜欢书店/10km”完整流程：返回1个候选，类别不匹配排除1个，最终0卡片；页面明确解释原因，没有把手工用品店当书店，没有伪造推荐。

56项Python测试与6个探索策略场景通过，新增普通/独立过滤区分、API0候选/类别排除/已展示诊断测试。原预算、时间、即时营业和范围过滤继续生效。前端语法检查通过。修改文件：src/cityplay/engine.py、src/cityplay/web.py、web/app.js、tests/test_core.py、tests/test_web.py。实际截图保留在私有目录stage3/bookstore-empty-reason.jpg。
