# Leaflet / Qloo 坐标兼容验证

日期：2026-10-14。结论：字段和投影接口兼容已验证，地理基准一致尚未证明。

真实Hackathon API调用2次：纽约/上海各以明确POINT中心、10公里半径、take=2请求/v2/insights，共4条地点坐标。Key仅服务端读取，没有输出。原始坐标只存于忽略提交的`.qloo-private/leaflet-test/index.html`，本报告不发布真实API数据。

使用实际Leaflet1.9.4浏览器运行L.latLng(lat,lon)，再以L.CRS.EPSG3857.project/unproject测试。4/4输入和投影值有效，纬度/经度未颠倒，球面距离往返误差最大约1.59e-9米。这是数值误差，不是地点定位精度。

| 接口 | 顺序/用途 |
|---|---|
| Qloo实体 | location.lat与location.lon |
| Qloo WKT过滤 | POINT(lon lat) |
| Leaflet LatLng/marker | [lat, lon] |
| GeoJSON | [lon, lat] |
| Leaflet默认地图投影 | EPSG:3857，库负责将经纬度投影 |

资料：[Leaflet参考](https://leafletjs.com/reference)、[Qloo官方WKT说明](https://github.com/qloo/docs-public/blob/main/reference/insights-api-deep-dive.md)。所核对的Qloo说明未给出明确WGS84/GCJ02声明。没有独立同一实体的已知WGS84控制点，也没有完成底图落点偏移对照；因此不能把本次数值测试称为“上海无偏移”或“双方坐标系已确认一致”。

接入建议：保留原始lat/lon；Leaflet只调整参数顺序，不预先套用GCJ02转换，也不将经纬度手动替换成3857米坐标。上海在获得官方坐标基准声明或多个同一实体的独立控制点前标为“坐标基准待验证”；纽约同样尚未获得 datum 的正式保证。Leaflet没有替调用方识别输入datum的能力。选择GCJ02底图时需独立核对转换，不能沿用本报告作为转换依据。

私有测试页面使用本地Leaflet脚本，没有向底图供应商发送Qloo坐标，也没有加载地图瓦片。测试服务器8788已停止，主项目未新增地图功能。

## 地图预览接入（2026-10-14）

已在推荐结果中加入Leaflet1.9.4，JS/CSS及BSD许可证保存在`web/vendor/`，不依赖运行时CDN加载组件。底图使用OpenStreetMap公共标准瓦片，仅用于当前低流量预览；遵循署名、浏览器缓存和Referer政策，正式上线需重新评估瓦片服务。HTTP仅允许该瓦片主机加载图片，脚本仍仅限本地；Referrer-Policy调整为strict-origin-when-cross-origin，跨站发送origin，不发送兴趣文本。

`web/map.js`直接使用卡片`location.lat/lon`，没有添加基准转换。标记与卡片编号对应，弹窗展示名称、地址和原始经纬度，可从卡片定位地图，也可从弹窗回到卡片。显示所选探索范围圆；地图初始视野包含本轮推荐点，空结果时隐藏地图，换批清除旧标记。范围圆可能在地点近景中超出视野，可缩小查看。未索取设备定位，也没有接入路线/行程时间服务。

真实纽约候选已在浏览器落点；卡片点击、弹窗和瓦片加载验证通过，8个可见瓦片均成功加载，浏览器无JS错误。这只证明地图展示与原坐标传递成功，未构成地点入口位置或datum准确性证明。390px移动端页面scrollWidth390px，地图348×300px，无横向溢出。截图在`.qloo-private/stage3/leaflet-live-map.jpg`及`leaflet-mobile.jpg`，不加入公开资料。

54项Python测试与6个探索策略场景通过，扩展了静态资源和CSP/Referer检查。新增`web/map.js`与`web/vendor/`；修改`web/index.html`、`web/app.js`、`web/styles.css`、`src/cityplay/web.py`及`tests/test_web.py`。主预览服务在8787运行。

参考：[Leaflet快速入门](https://leafletjs.com/examples/quick-start/)、[OpenStreetMap瓦片政策](https://operations.osmfoundation.org/policies/tiles/)。
