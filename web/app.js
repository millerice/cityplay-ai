"use strict";

const $ = (id) => document.getElementById(id);
const state = {city: "new_york", csrf: null, presets: {}, draft: null, busy: false, result: null, dirty: false, confirmedIntent: null};
const categories = {bookstore: "书店", coffee: "咖啡", live_music: "现场音乐", park: "公园", museum: "博物馆"};
const excludeCategories = {...categories, hotel: "酒店", mall: "商场", recording_studio: "录音室", tourist_attraction: "旅游景点"};
const entityTypes = {"": "未指定类型", artist: "音乐人", movie: "电影", book: "书籍", brand: "品牌", person: "公众人物", podcast: "播客", tv_show: "剧集", video_game: "游戏"};
const cities = {new_york: "纽约附近", shanghai: "上海附近"};
const errors = {
  INVALID_PROFILE_OUTPUT: "画像证据未通过检查，答案已保留，请重试。",
  PROFILE_INPUT_TOO_LONG: "合并后内容太长，请减少标签或缩短原有文字。",
  PROFILE_CONFLICTING_SELECTIONS: "同一标签同时被选为喜欢和避免，请修改后确认。",
  PROFILE_ALREADY_CONFIRMED: "这份画像已确认，请重新生成草稿后再修改。",
  QLOO_AUTH: "Qloo 鉴权失败。请在本机检查服务端配置。",
  QLOO_AUTH_MISSING: "尚未配置 Qloo 服务端凭据。",
  DEEPSEEK_AUTH_MISSING: "尚未配置 DeepSeek 服务端凭据。",
  DEEPSEEK_HTTP_ERROR: "模型服务当前未能完成解析，请稍后再试。",
  DEEPSEEK_INVALID_OUTPUT: "模型输出未通过检查，请调整描述后重试。",
  INVALID_MODEL_INTENT: "模型连续两次返回的需求结构未通过检查。原输入已保留，请重试。",
  INTENT_TOO_MANY_REQUIREMENTS: "需要确认的条件较多，请分成两次探索；原输入已保留。",
  NETWORK_TIMEOUT_OR_UNAVAILABLE: "外部服务超时或暂不可达，请稍后再试。",
  QLOO_RATE_LIMIT: "Qloo 当前请求受限，请稍后再试。",
  QLOO_HTTP_ERROR: "Qloo 请求未成功，这轮没有生成替代推荐。",
  QLOO_RESPONSE_SHAPE: "Qloo 返回的数据未通过检查，请稍后再试。",
  CALL_BUDGET_EXHAUSTED: "这轮请求额度已用完，请缩小兴趣或场所范围。",
  MONTHLY_QUOTA_RESERVE: "Qloo 可用额度不足，已暂停新请求。",
  WEB_PROCESS_BUDGET_EXHAUSTED: "本地预览的调用预算已用完。",
  JOB_ALREADY_RUNNING: "当前任务仍在进行，请等待它完成。",
  LOCAL_REQUEST_LIMIT: "操作较频繁，请一分钟后再试。",
  LOCAL_SERVICE_BUSY: "服务正在处理其他探索，请稍后再试。",
  DRAFT_EXPIRED: "这份需求已过期，请重新理解需求。",
  CONFIRM_INTENT_FIRST: "请先确认探索需求。",
  AREA_CITY_MISMATCH: "探索中心与所选城市不一致，请调整范围并重新理解需求。",
  SENSITIVE_INPUT_REJECTED: "描述中似乎包含凭据或联系方式，请移除后再试。",
  INVALID_INPUT_OR_LOCAL_STATE: "输入或本地状态未通过检查，请重新理解需求。",
  INVALID_REQUEST: "输入未通过检查，请检查数值和选择。",
  INTERNAL_ERROR: "本地服务遇到错误，请重新尝试。",
  INVALID_SESSION_OR_CSRF: "预览会话已过期，请刷新页面。",
};
const clarificationTranslations = {
  "Budget constraint needs an explicit amount and currency.": "预算需要明确金额与币种。",
  "Time constraint needs confirmation.": "请确认你能用来探索的时间。",
  "Immediate opening constraint needs confirmation.": "请确认是否必须现在营业。",
  "Administrative boundary constraint needs confirmation.": "请确认是否必须在城市行政边界内。",
  "Explicit hotel exclusion needs confirmation.": "请确认是否排除酒店。",
  "Explicit mall exclusion needs confirmation.": "请确认是否排除商场。",
  "The requested city differs from the selected area; choose a matching area.": "描述中的城市与当前范围不同，请重新选择区域；若接受当前范围，可取消这条要求。",
};

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = String(text);
  return element;
}
function notice(message) {
  $("notice").textContent = message;
  $("notice").hidden = !message;
}
function showError(error) {
  let message = errors[error?.code] || "暂时未能完成这轮探索，请稍后重试。";
  if (error?.details?.field) {
    const field = error.details.field;
    const interest = /^interests\[(\d+)\]\.query$/.exec(field);
    const clarification = /^clarifications\[(\d+)\]$/.exec(field);
    message += interest ? ` 第 ${Number(interest[1])+1} 个兴趣关键词为空、类型不正确或超长。` : clarification ? ` 第 ${Number(clarification[1])+1} 条待确认条件为空、类型不正确或超长。` : ` 校验字段：${field}。`;
  }
  notice(message);
}
function setBusy(value, kind = "discover") {
  state.busy = value;
  $("query-fields").disabled = value;
  $("confirm-fields").disabled = value;
  $("again-button").disabled = value;
  $("compare-button").disabled = value;
  $("progress-panel").hidden = !value;
  if (value) {notice(""); progress(kind === "parse" ? "PARSING" : "INTENT_PARSED");}
}
function progress(stage) {
  const entries = {
    PARSING: [0, "正在理解你的需求", "整理文化兴趣、想探索的场所，以及必须满足的条件。"],
    INTENT_PARSED: [1, "正在探索真实兴趣关联", "查询 Qloo，确认人物或作品，再寻找附近候选。"],
    TASTE_RETRIEVED: [2, "正在检查地点与来源", "检查类别与范围，读取候选网站的名称线索。"],
    CANDIDATES_CHECKED: [3, "正在整理建议", "按证据、检索顺序与类别多样性选择少量候选。"],
    RANKED: [3, "正在整理建议", "为每个候选整理来源和仍需确认的条件。"],
    PRESENTED: [3, "正在整理结果", "即将呈现这轮探索。"],
  };
  const value = entries[stage] || entries.INTENT_PARSED;
  $("progress-title").textContent = value[1];
  $("progress-description").textContent = value[2];
  [...$("progress-steps").children].forEach((item, i) => {item.className = i < value[0] ? "done" : i === value[0] ? "active" : "";});
}
async function request(path, payload) {
  const response = await fetch(path, payload ? {method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": state.csrf}, body: JSON.stringify(payload)} : {});
  const data = await response.json();
  if (!response.ok) throw data.error || {code: "INTERNAL_ERROR"};
  return data;
}
async function job(path, payload) {
  const started = await request(path, payload);
  // Poll actual job state. There is no fabricated percentage or timed progress sequence.
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    const current = await request(`/api/jobs/${encodeURIComponent(started.job_id)}`);
    if (current.status === "failed") throw current.error;
    if (current.status === "completed") return current.result;
    progress(current.progress);
  }
}
function resetDraft() {
  state.draft = null; state.result = null; state.confirmedIntent = null; state.dirty = false;
  $("confirmation").hidden = true; $("results").hidden = true; CityPlayMap.render([]); notice("");
}
function area() {
  return {lat: Number($("latitude").value), lon: Number($("longitude").value), radius_m: Number($("radius").value)};
}
function setCity(city) {
  if (state.busy || !state.presets[city]) return;
  state.city = city;
  document.querySelectorAll(".city-button").forEach((button) => {const selected = button.dataset.city === city; button.classList.toggle("selected", selected); button.setAttribute("aria-pressed", String(selected));});
  $("latitude").value = state.presets[city].lat;
  $("longitude").value = state.presets[city].lon;
  $("area-label").textContent = state.presets[city].label;
  resetDraft();
}
function addInterest(value = {kind: "entity", query: "", entity_type: "artist"}) {
  const container = $("interest-fields");
  if (container.children.length >= 3) return;
  const row = node("div", "interest-row");
  const input = node("input"); input.type = "text"; input.required = true; input.maxLength = 100; input.value = value.query; input.className = "interest-query"; input.setAttribute("aria-label", `兴趣 ${container.children.length + 1}`);
  const kind = node("select", "interest-kind"); kind.setAttribute("aria-label", "兴趣形式");
  for (const [key, label] of Object.entries({entity: "人物 / 作品", tag: "兴趣概念"})) {const option = node("option", "", label); option.value = key; kind.append(option);}
  kind.value = value.kind;
  const type = node("select", "interest-type"); type.setAttribute("aria-label", "人物或作品类型");
  for (const [key, label] of Object.entries(entityTypes)) {const option = node("option", "", label); option.value = key; type.append(option);}
  type.value = value.entity_type || ""; type.disabled = kind.value === "tag";
  kind.addEventListener("change", () => {type.disabled = kind.value === "tag";});
  const remove = node("button", "remove-interest", "×"); remove.type = "button"; remove.setAttribute("aria-label", "移除这个兴趣");
  remove.addEventListener("click", () => {row.remove(); $("add-interest").hidden = container.children.length >= 3;});
  row.append(input, kind, type, remove); container.append(row); $("add-interest").hidden = container.children.length >= 3;
}
function checks(container, options, selected, name) {
  container.replaceChildren();
  for (const [value, text] of Object.entries(options)) {const label = node("label"); const input = node("input"); input.type = "checkbox"; input.name = name; input.value = value; input.checked = selected.includes(value); label.append(input, node("span", "", text)); container.append(label);}
}
function renderIntent(draft) {
  state.draft = draft;
  state.dirty = false;
  const intent = draft.intent;
  $("interest-fields").replaceChildren();
  intent.interests.forEach(addInterest);
  if (!intent.interests.length) addInterest();
  checks($("category-fields"), categories, intent.categories, "categories");
  checks($("exclude-fields"), excludeCategories, intent.exclude_categories, "exclusions");
  $("minutes").value = intent.available_minutes ?? "";
  $("budget").value = intent.max_budget?.amount ?? "";
  $("currency").value = intent.max_budget?.currency || "USD";
  $("open-now").checked = intent.open_now; $("novelty").checked = false; $("strict-city").checked = false;
  $("default-plan").textContent = [intent.strict_city ? "本轮按所选中心和半径探索，暂不限制行政市界。" : "", intent.novelty_requested ? "尚无完整到访记录，本轮提供探索候选，不保证从未去过。" : ""].filter(Boolean).join(" ");
  $("default-plan").hidden = !$("default-plan").textContent;
  const clarifications = $("clarifications"); clarifications.replaceChildren(); clarifications.hidden = !intent.clarifications.length;
  if (intent.clarifications.length) {
    clarifications.append(node("strong", "", "已为本轮整理默认方案"), node("p", "", "默认使用摘要中的兴趣和已明确的条件。以下尚未明确或无法执行的要求，本轮暂不执行；勾选表示仍要求满足它。你可以直接确认默认方案。"));
    for (const message of intent.clarifications) {const label = node("label"); const input = node("input"); input.type = "checkbox"; input.checked = false; input.value = message; label.append(input, node("span", "", clarificationTranslations[message] || message)); clarifications.append(label);}
  }
  $("confirmed-area").textContent = `${cities[draft.city]} · 中心 ${draft.area.lat.toFixed(4)}, ${draft.area.lon.toFixed(4)} · ${draft.area.radius_m / 1000} km`;
  $("intent-details").open = !intent.interests.length;
  updateIntentSummary();
  $("confirmation").hidden = false; $("results").hidden = true;
  $("confirmation").scrollIntoView({behavior: "smooth", block: "start"});
}
function readIntent() {
  const interests = [...$("interest-fields").children].map((row) => ({query: row.querySelector(".interest-query").value.trim(), kind: row.querySelector(".interest-kind").value, entity_type: row.querySelector(".interest-kind").value === "entity" ? row.querySelector(".interest-type").value || null : null}));
  return {city: state.draft.city, interests,
    categories: [...$("category-fields").querySelectorAll("input:checked")].map((input) => input.value),
    exclude_categories: [...$("exclude-fields").querySelectorAll("input:checked")].map((input) => input.value),
    available_minutes: $("minutes").value === "" ? null : Number($("minutes").value),
    max_budget: $("budget").value === "" ? null : {amount: Number($("budget").value), currency: $("currency").value},
    open_now: $("open-now").checked, novelty_requested: $("novelty").checked, strict_city: $("strict-city").checked,
    clarifications: [...$("clarifications").querySelectorAll("input:checked")].map((input) => input.value)};
}
function updateIntentSummary() {
  if (!state.draft) return;
  const intent = readIntent();
  const names = intent.interests.map(x => x.query).filter(Boolean);
  const places = intent.categories.map(x => categories[x]);
  const parts = [`根据${names.length ? "「" + names.join("、") + "」" : "你选择的兴趣"}，在${cities[state.draft.city]} ${state.draft.area.radius_m / 1000} km 范围内${places.length ? "探索" + places.join("、") : "寻找值得了解的地点"}。`];
  if (intent.exclude_categories.length) parts.push("避开" + intent.exclude_categories.map(x => excludeCategories[x]).join("、") + "。");
  const limits = [];
  if (intent.available_minutes !== null) limits.push(`${intent.available_minutes} 分钟以内`);
  if (intent.max_budget) limits.push(`预算 ${intent.max_budget.amount} ${intent.max_budget.currency}`);
  if (intent.open_now) limits.push("必须现在营业");
  if (intent.novelty_requested) limits.push("必须从未去过");
  if (intent.strict_city) limits.push("必须在市界内");
  if (limits.length) parts.push(limits.join(" · ") + "。");
  $("intent-summary").textContent = parts.join(" ") + " 同名或近似标签由系统默认匹配，仅用于本次探索；没有匹配的兴趣本轮略过，原画像不变。";
}
function editRequest() {$("intent-details").open = true;$("confirmation").scrollIntoView({behavior: "smooth", block: "start"}); $("discover-button").focus({preventScroll: true});}
function message(title, description) {
  const container = $("result-message"); container.replaceChildren(node("h3", "", title), node("p", "", description));
  const button = node("button", "text-button", "修改探索条件 ↗"); button.type = "button"; button.addEventListener("click", editRequest); container.append(button); container.hidden = false;
}
function renderChoices(question) {
  const container = $("choices"); container.replaceChildren(); container.hidden = false;
  container.append(node("h3", "", `你说的「${question.query}」，是哪个？`), node("p", "", "系统已选好本次探索的默认候选，你可以直接确认，也可以修改。此选择不更改兴趣画像。"));
  const form = node("form");
  for (const candidate of question.choices || []) {
    const label = node("label", "choice-option"); const input = node("input"); input.type = "radio"; input.name = "choice"; input.value = candidate.id; input.required = true; input.checked = candidate === question.choices[0];
    const description = node("div"); description.append(node("span", "", candidate.name));
    const type = candidate.type?.replace("urn:entity:", "");
    description.append(node("small", "", `${entityTypes[type] || "文化标签"}${candidate.release_year ? ` · ${candidate.release_year}` : ""}`));
    label.append(input, description); form.append(label);
  }
  if (!question.choices?.length) {container.append(node("p", "", "没有足够清晰的候选，请修改兴趣关键词后再试。")); return;}
  const button = node("button", "primary-button", "确认选择并继续 ↗"); button.type = "submit"; form.append(button);
  form.addEventListener("submit", async (event) => {event.preventDefault(); const selected = form.querySelector("input:checked"); if (!selected || state.busy) return; button.disabled = true; try {await discover({draft_id: state.draft.draft_id, again: true, selections: {[question.field]: selected.value}});} finally {button.disabled = false;}});
  container.append(form);
}
function renderCard(card, index) {
  const article = node("article", "experience-card");
  const top = node("div", "card-top");
  top.append(node("span", "card-number", `0${index+1}`), node("span", "card-category", categories[card.category] || {"book store": "书店", "cafe": "咖啡", "live music venue": "现场音乐", "park": "公园"}[card.category] || "城市探索"), node("span", "card-symbol", card.category === "coffee" ? "◉" : card.category === "live_music" ? "♫" : "▤"));
  const body = node("div", "card-body");
  body.append(node("h3", "", card.name), node("p", "card-distance", `${(card.straight_line_distance_m/1000).toFixed(1)} km · 与所选中心的直线距离`), node("p", "card-why", card.recommendation_mode === "category_baseline" ? "Qloo 同类别基线，未添加文化兴趣信号；采用相同类别与范围检查。" : `本轮采用 ${(card.taste_inputs || []).map(x=>x.name).join("、") || "你选择的文化兴趣"} 作为 Qloo 信号。这是图谱返回的候选，已通过类别与范围检查。`), node("p", "card-address", card.address));
  const evidence = node("div", "card-evidence"); evidence.append(node("span", "evidence-tag", "Qloo 真实候选"));
  if (card.verification.identity === "website_name_corroborated") evidence.append(node("span", "evidence-tag", "网站名称可对应"));
  else evidence.append(node("span", "evidence-tag unverified", "网站线索待核验"));
  if (card.novelty === "not_in_provided_seen_list") evidence.append(node("span", "evidence-tag", "本轮未展示"));
  body.append(evidence, node("p", "card-note", "探索候选 · 出发前请确认营业、费用与公众访问。"));
  if (card.verification.website) {
    try {const url = new URL(card.verification.website); if (url.protocol === "https:" && !url.username && !url.password) {const link = node("a", "card-link", "查看来源网站 ↗"); link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer"; body.append(link);}} catch (_) { /* No unvalidated hyperlink. */ }
  }
  article.id = `place-card-${index}`;
  const locate = node("button", "secondary-button", "在地图上查看 ⌖"); locate.type="button"; locate.addEventListener("click", () => CityPlayMap.focus(index)); body.append(locate);
  article.append(top, body); return article;
}
function renderResult(result) {
  state.result = result;
  $("comparison-result").replaceChildren();
  $("comparison-panel").hidden = result.status !== "partial";
  const evidence=$("agent-evidence");evidence.replaceChildren();evidence.hidden=result.status!=="partial";
  if (!evidence.hidden) {
    evidence.append(node("strong", "", "Agent 本轮采用的文化信号"),node("p","",(result.taste_inputs||[]).map(x=>`${x.name}（${entityTypes[x.type?.replace("urn:entity:","")]||"Qloo 兴趣标签"}）`).join("、")),node("p","field-help","识别文化实体 → 查询 Qloo 跨领域关联 → 检查类别与位置 → 保留少量候选。网站状态单独标注，不编造喜好原因或营业信息。"));
  }
  CityPlayMap.render(result.cards || [], state.draft?.area);
  $("results").hidden = false; $("cards").replaceChildren(); $("choices").hidden = true; $("result-message").hidden = true; $("decision-details").hidden = true;
  $("again-button").hidden = result.status !== "partial";
  $("results-subtitle").textContent = "";
  if (result.status === "error") {message("这轮检索未能完成", errors[result.error?.code] || "服务未能提供可靠结果，请稍后再试。");}
  else if (result.status === "needs_input") {
    $("results-title").textContent = "已整理好下一步方案。";
    const question = result.questions.find((item) => typeof item === "object");
    if (question) renderChoices(question);
    else {
      const intent = state.confirmedIntent || readIntent();
      let description = "请检查上面的兴趣、区域和待确认条件，调整后继续。";
      if (intent.novelty_requested) description = "尚无你的完整到访记录，无法保证从未去过。若愿意先探索相关候选，可取消“必须从未去过”。";
      else if (intent.strict_city) description = "当前支持坐标附近范围，尚未核验市界。如果接受附近范围，可取消“必须在市界内”。";
            const unresolved = (result.questions || []).filter(x => typeof x === "string");
      const reasons = unresolved.map(x => clarificationTranslations[x] || ({
        "Provide at least one public cultural interest.": "目前没有可用于匹配的兴趣，请补充具体音乐、电影或兴趣关键词。",
        "Administrative city boundaries are not verified; choose a radius or provide a verified boundary service.": "本轮建议使用已选中心和半径，暂不限制行政市界。",
        "Provide places already visited, or relax the requirement to guarantee something new.": "本轮提供探索候选，暂不保证从未去过。"
      }[x] || x));
      message("本轮建议这样继续", reasons.join(" ") || description);
      if (intent.interests.length) {
        const button = node("button", "primary-button", "采用可执行方案，继续探索 ↗"); button.type="button";
        button.addEventListener("click", () => {const revised=structuredClone(intent);revised.clarifications=[];revised.strict_city=false;revised.novelty_requested=false;discover({draft_id:state.draft.draft_id,intent:revised});});
        $("result-message").append(node("p", "", "继续将暂不执行待确认要求和市界/未到访保证；明确的预算、时间与排除项仍保留。"),button);
      }
    }
  } else if (result.status === "empty") {
    $("results-title").textContent = "这轮，没有足够可靠的候选。";
    const intent = state.confirmedIntent || readIntent();
    const hasOperationalConstraints = intent.max_budget !== null || intent.available_minutes !== null || intent.open_now;
    const diagnostic = result.diagnostics;
    const scope = `${cities[state.draft.city]}所选中心附近 ${state.draft.area.radius_m/1000} km`;
    const reasonLabels = {explicitly_seen:"本轮已展示",duplicate:"重复地点",unsuitable_or_unknown_category:"场所类别不匹配或未知",excluded_category:"属于本轮排除类别",missing_entity_identity:"缺少地点身份",not_place:"不是地点",qloo_reports_closed:"数据标记已关闭",missing_or_outside_coordinates:"坐标缺失或超出范围",missing_address:"缺少地址",budget_unverified:"费用未核实",visit_and_travel_time_unverified:"体验和交通时间未核实",open_now_unverified:"即时营业未核实"};
    if (diagnostic?.empty_reason === "no_api_candidates") {
      $("results-title").textContent = "这次查询，没有返回地点。";
      message("这次查询没有返回地点", `Qloo 在${scope}内，按本轮兴趣和类别过滤返回 0 个地点。没有候选进入后续过滤；这不代表附近没有这些场所。扩大范围或换个类别可能有帮助，重复同一查询通常不会增加结果。`);
    } else if (diagnostic?.empty_reason === "already_shown") {
      $("results-title").textContent = "本轮匹配地点，已经展示过了。";
      message("本轮匹配地点已经展示过", `Qloo 返回了 ${diagnostic.retrieved_count} 个候选，但都是重复或本轮已展示的地点。可修改兴趣或范围开启新一轮探索。`);
    } else if (diagnostic?.empty_reason === "filtered_candidates") {
      $("results-title").textContent = "找到了地点，但条件未匹配。";
      const reasons = Object.entries(diagnostic.rejection_counts || {}).map(([reason,count])=>`${reasonLabels[reason]||"未通过检查"} ${count} 个`).join("；");
      message("返回了地点，但没有符合本轮条件的候选", `Qloo 返回 ${diagnostic.retrieved_count} 个候选。排除原因：${reasons}。系统没有将这些地点当作符合要求的推荐。`);
    } else message("本轮没有可展示的匹配", hasOperationalConstraints ? "费用、时间或营业要求仍保留，但没有可核实的匹配结果。" : "目前没有可用于本轮推荐的匹配结果。原输入保留，可换个兴趣或范围尝试。");
  } else {
    $("results-title").textContent = "这几个方向，值得了解。";
    result.cards.forEach((card, index) => $("cards").append(renderCard(card, index)));
    const matched = result.cards.filter((card) => card.verification.identity === "website_name_corroborated").length;
    const source = {live_qloo: "本轮真实检索", cached_qloo: "私有缓存 · 最多 5 分钟", mixed_qloo: "真实检索与私有缓存"}[result.source] || "Qloo 数据";
    $("results-subtitle").textContent = `${result.cards.length} 个真实候选 · ${matched} 个网站名称可对应 · ${source}`;
    $("decision-details").hidden = false;
    const detail = $("decision-content"); detail.replaceChildren();
    for (const [title, description] of [["为什么与你有关", "兴趣经确认后用于 Qloo 文化关联检索；这不是对个人喜好的概率预测。"], ["为什么出现在这里", "通过场所类别、坐标半径、重复与排除检查，再按来源证据和检索顺序选择。"], ["还需要确认什么", "营业、实际费用、活动场次与公众访问尚未独立核验。没有到访历史，也不保证必然新颖。"]]) {const section = node("div"); section.append(node("strong", "", title), node("span", "", description)); detail.append(section);}
  }
  $("results").scrollIntoView({behavior: "smooth", block: "start"});
}
function proposeDiscoveryStep(result, confirmedIntent, draftId) {
  const question = result.questions?.find(x => x && typeof x === "object");
  if (!question) return null;
  const position = /^interests\.(\d+)$/.exec(question.field);
  const interest = position && confirmedIntent?.interests[Number(position[1])];
  const expectedType = interest?.kind === "entity" && interest.entity_type ? "urn:entity:" + interest.entity_type : null;
  const candidates = (question.choices || []).filter(x => typeof x.id === "string" && x.id && typeof x.name === "string" && (!expectedType || x.type === expectedType));
  const choice = candidates.find(x => x.name.toLowerCase() === String(question.query).toLowerCase()) || candidates[0];
  if (choice) return {payload:{draft_id:draftId,again:true,selections:{[question.field]:choice.id}},
    note:`本次「${question.query}」采用 Qloo 候选「${choice.name}」。`};
  const match = /^interests\.(\d+)$/.exec(question.field);
  if (!match || !confirmedIntent) return null;
  const intent = structuredClone(confirmedIntent);
  const index = Number(match[1]);
  if (index >= intent.interests.length) return null;
  intent.interests.splice(index, 1);
  return {intent,payload:{draft_id:draftId,intent},terminal:!intent.interests.length,
    note:`「${question.query}」没有可用匹配，本轮先略过。`};
}

async function discover(payload) {
  if (state.busy) return;
  if (payload.again && state.dirty) {notice("你修改了需求，请先点击“确认，开始探索”，再按新条件换一批。"); editRequest(); return;}
  if (payload.intent) {state.confirmedIntent = structuredClone(payload.intent); state.dirty = false;}
  setBusy(true);
  try {
    let result = await job("/api/discover", payload);
    const adjustments = [];
    for (let attempt = 0; attempt < 4 && result.status === "needs_input"; attempt++) {
      const step = proposeDiscoveryStep(result, state.confirmedIntent, state.draft.draft_id);
      if (!step) break;
      adjustments.push(step.note);
      if (step.terminal) {result={...result,status:"empty",questions:[],cards:[]};break;}
      if (step.intent) state.confirmedIntent=step.intent;
      result = await job("/api/discover", step.payload);
    }
    renderResult(result);
    if (adjustments.length) notice(adjustments.join(" ") + " 这些调整仅用于本次探索，原输入和兴趣画像已保留。");
  } catch (error) {showError(error);} finally {setBusy(false);}
}

$("query-form").addEventListener("submit", async (event) => {
  event.preventDefault(); if (state.busy || !state.csrf) return;
  resetDraft(); setBusy(true, "parse");
  try {const draft = await job("/api/parse", {query: $("query").value.trim(), city: state.city, area: area()}); renderIntent(draft);} catch (error) {showError(error);} finally {setBusy(false);}
});
$("confirm-form").addEventListener("invalid", () => {$("intent-details").open = true;}, true);
$("confirm-form").addEventListener("submit", async (event) => {event.preventDefault(); if (!state.draft) return; await discover({draft_id: state.draft.draft_id, intent: readIntent()});});
$("again-button").addEventListener("click", () => state.draft && discover({draft_id: state.draft.draft_id, again: true}));
$("add-interest").addEventListener("click", () => addInterest());
$("confirm-form").addEventListener("input", () => {state.dirty = true; updateIntentSummary();});
$("confirm-form").addEventListener("change", updateIntentSummary);
$("interest-fields").addEventListener("click", () => {updateIntentSummary();});
$("interest-fields").addEventListener("click", (event) => {if (event.target.closest(".remove-interest")) state.dirty = true;});
$("add-interest").addEventListener("click", () => {state.dirty = true; updateIntentSummary();});
document.querySelectorAll(".city-button").forEach((button) => button.addEventListener("click", () => setCity(button.dataset.city)));
for (const id of ["radius", "latitude", "longitude"]) $(id).addEventListener("change", () => {if (!state.busy) resetDraft();});
document.querySelectorAll("[data-example]").forEach((button) => button.addEventListener("click", () => {
  const examples = {books: "喜欢 Miles Davis，想探索独立书店，避开酒店和商场。", coffee: "喜欢爵士，想找咖啡场所，避开酒店和商场。", movie: "喜欢电影《Blade Runner》，想探索咖啡场所，避开酒店和商场。"};
  $("query").value = examples[button.dataset.example]; $("query").focus();
}));
request("/api/session").then((session) => {
  state.csrf = session.csrf; state.presets = session.presets;
  $("service-status").lastChild.textContent = session.configured.qloo && session.configured.model ? " 服务端已配置" : " 服务端待配置";
  if (!session.configured.qloo || !session.configured.model) notice("请在本机配置 Qloo 与 DeepSeek 凭据后再开始探索。");
}).catch(() => {$("service-status").lastChild.textContent = " 服务暂不可达"; notice("本地服务暂不可达，请刷新后重试。");});

$("compare-button").addEventListener("click", async () => {
  if (state.busy || !state.draft || !state.result) return;
  if (state.dirty) {notice("你修改了条件，请先确认新的探索方案，再比较。");return;}
  const original=state.result;
  const output=$("comparison-result");output.replaceChildren(node("p","","正在按相同条件查询基线…"));setBusy(true);
  try {
    const baseline=await job("/api/compare",{draft_id:state.draft.draft_id});output.replaceChildren();
    if (baseline.status==="error") {output.append(node("p","",errors[baseline.error?.code]||"基线查询未完成。"));return;}
    if (baseline.status==="needs_input") {output.append(node("p","","当前基线条件也需要进一步核实，本轮无法完成公平对照。"));return;}
    const common=baseline.cards.filter(x=>original.cards.some(y=>x.entity_id===y.entity_id)).length;
    output.append(node("p","",`文化口味方案 ${original.cards.length} 个展示候选；无文化信号基线 ${baseline.cards.length} 个；展示集合重合 ${common} 个。列表差异不代表偏好或满意度提升。`));
    const list=node("ol");for(const card of baseline.cards)list.append(node("li","",`${card.name} · ${card.address}`));output.append(list);
    if(!baseline.cards.length)output.append(node("p","","基线没有通过相同检查的展示候选；此结果不证明文化方案更优。"));
  } catch(error){output.replaceChildren(node("p","",errors[error.code]||"对照暂时未完成，请重试。"));}finally{setBusy(false);}
});
