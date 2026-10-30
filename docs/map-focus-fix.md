# 地图连续定位修复

2026-10-15。点击卡片定位依次调用 `setResultView('map')` 和 `CityPlayMap.focus(index)`。旧版 resize 同时执行 fitBounds（最高 zoom 15），focus 执行 setView（zoom 16），各自排入下一帧。Leaflet 的异步缩放可能让前一操作覆盖后一操作。实际 Leaflet 1.9.4 配合项目代码、明确标注的合成地点复现：首次定位到 16，换地点首击回到 15，再击才到目标 16。

修复后，普通 resize 仅更新尺寸；新一批推荐才标记需要全局适配。若手机地图尚隐藏，保留首次适配意图，待可见再执行。单点定位取消未执行的帧、停止已有移动，以非动画 setView 定位并打开对应弹窗。连续请求只执行最后一项；结果清空或重绘会撤销旧定位任务。

实际 Leaflet 浏览器验收：地点一 → 地点二，以及一 → 二 → 一，均一次点击定位到对应目标并保持 zoom 16。测试数据仅验证交互，不作为 Qloo 推荐或能力数据。未消耗真实 API 调用。

回归命令：

```sh
node tests/test_map_focus.cjs
node tests/test_exploration_policy.cjs
```

新增测试覆盖连续目标、重复 resize 保持视野、同帧快速切换、隐藏地图首次适配、清空结果撤销旧定位。
