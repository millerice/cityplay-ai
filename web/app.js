"use strict";

const $ = (id) => document.getElementById(id);
const state = {city: "new_york", csrf: null, presets: {}, draft: null, busy: false, result: null, dirty: false, confirmedIntent: null, qlooReady: null, modelReady: null};
// Browser-supplied model credentials: kept only in this tab's memory. Never
// written to storage or disk; closing the tab clears them for good.
const modelConfig = {key: "", name: "deepseek-v4-pro"};
// Canonical zh labels remain the parsing/lookup source; display goes through categoryLabel().
const categories = {bookstore: "书店", coffee: "咖啡", live_music: "现场音乐", park: "公园", museum: "博物馆", restaurant: '餐厅', bakery: '烘焙甜点', gallery: '画廊', cinema: '电影院', theater: '剧院', record_store: '唱片店', clothing: '服饰店', garden: '花园'};
function selectedVenueCategories(source='library') {
  if(source==='seed')return $('seed-category').value?[$('seed-category').value]:[];
  return $('venue-custom').getAttribute('aria-pressed')==='true'?[...$('venue-choices').querySelectorAll('input:checked')].map(x=>x.value):[];
}
const excludeCategories = {...categories, hotel: "酒店", mall: "商场", recording_studio: "录音棚", tourist_attraction: "旅游景点"};
const entityTypes = {"": "未指定类型", artist: "音乐人", movie: "电影", book: "书籍", brand: "品牌", person: "公众人物", podcast: "播客", tv_show: "剧集", video_game: "游戏"};
// zh rendering of the server's English clarification strings; shown only in zh mode.
const clarificationTranslations = {
  "Budget constraint needs an explicit amount and currency.": "预算需要明确金额与币种。",
  "Time constraint needs confirmation.": "请确认你能用来探索的时间。",
  "Immediate opening constraint needs confirmation.": "请确认是否必须现在营业。",
  "Administrative boundary constraint needs confirmation.": "请确认是否必须在城市行政边界内。",
  "Explicit hotel exclusion needs confirmation.": "请确认是否排除酒店。",
  "Explicit mall exclusion needs confirmation.": "请确认是否排除商场。",
  "The requested city differs from the selected area; choose a matching area.": "描述中的城市与当前范围不同，请重新选择区域；若接受当前范围，可取消这条要求。",
  "Provide at least one public cultural interest.": "目前没有可用于匹配的兴趣，请补充具体音乐、电影或兴趣关键词。",
  "Administrative city boundaries are not verified; choose a radius or provide a verified boundary service.": "本轮建议使用已选中心和半径，暂不限制行政市界。",
  "Provide places already visited, or relax the requirement to guarantee something new.": "本轮提供探索候选，暂不保证从未去过。",
};
function localizedClarification(message) {
  return (LangState.lang === "zh" && clarificationTranslations[message]) || message;
}

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
  let message = errorMessage(error?.code);
  if (error?.details?.field) {
    const field = error.details.field;
    const interest = /^interests\[(\d+)\]\.query$/.exec(field);
    const clarification = /^clarifications\[(\d+)\]$/.exec(field);
    message += interest ? t("err.detailInterest", {n: Number(interest[1])+1}) : clarification ? t("err.detailClarification", {n: Number(clarification[1])+1}) : t("err.detailField", {field});
  }
  notice(message);
}
function setBusy(value, kind = "discover") {
  state.busy = value;document.querySelectorAll("#library-panel button,#library-panel input,#library-panel select").forEach(x=>x.disabled=value);if($("library-go"))$("library-go").disabled=value||$("library-go").dataset.hasPlan!=="true";
  document.querySelectorAll("#result-message button").forEach(button=>button.disabled=value);
  $("discover-button").disabled=value||!!state.draft?.city_conflict;
  $("library-next").disabled=value||$("library-next").dataset.canPage!=="true";
  $("query-fields").disabled = value; document.querySelectorAll("[data-mode]").forEach(b=>b.disabled=value);
  $("confirm-fields").disabled = value;
  $("again-button").disabled = value;
  $("compare-button").disabled = value; $("parallel-build").disabled=value;
  $("progress-panel").hidden = !value;
  if (value) {notice(""); progress(kind === "parse" ? "PARSING" : kind === "parallel" ? "PARALLEL_BUILD" : "INTENT_PARSED");}
}
function progress(stage) {
  const entries = {
    PARALLEL_BUILD: [1, "progress.parallel", "progress.parallelDesc"],
    PARSING: [0, "progress.parsing", "progress.parsingDesc"],
    INTENT_PARSED: [1, "progress.parsed", "progress.parsedDesc"],
    TASTE_RETRIEVED: [2, "progress.checked", "progress.checkedDesc"],
    CANDIDATES_CHECKED: [3, "progress.ranked", "progress.rankedDesc"],
    RANKED: [3, "progress.ranked", "progress.rankedDesc"],
    PRESENTED: [3, "progress.presented", "progress.presentedDesc"],
  };
  const value = entries[stage] || entries.INTENT_PARSED;
  $("progress-title").textContent = t(value[1]);
  $("progress-description").textContent = t(value[2]);
  [...$("progress-steps").children].forEach((item, i) => {item.className = i < value[0] ? "done" : i === value[0] ? "active" : "";});
}
async function refreshSession() {
  const session = await request("/api/session");
  state.csrf = session.csrf; state.presets = session.presets; state.qlooReady = session.configured.qloo;
  $("service-status-text").textContent = session.configured.qloo ? t("status.ready") : t("status.unconfigured");
  return session;
}
async function request(path, payload, retried = false) {
  const headers = {"Content-Type": "application/json", "X-CSRF-Token": state.csrf};
  if (payload && modelConfig.key) { headers["X-Model-Key"] = modelConfig.key; headers["X-Model-Name"] = modelConfig.name; }
  const response = await fetch(path, payload ? {method: "POST", headers, body: JSON.stringify(payload)} : {});
  const data = await response.json().catch(() => null);
  // A restarted server drops its in-memory sessions; re-bootstrap once and replay the request.
  if (response.status === 403 && payload && !retried && data && data.error && data.error.code === "INVALID_SESSION_OR_CSRF") {
    await refreshSession();
    return request(path, payload, true);
  }
  if (!response.ok) throw (data && data.error) || {code: "INTERNAL_ERROR"};
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
    progress(path==='/api/parallel'?'PARALLEL_BUILD':current.progress);
  }
}
function resetDraft() {
  $("query-form").hidden=false;document.body.classList.remove("showing-results"); state.draft = null; state.result = null; state.confirmedIntent = null; state.dirty = false; state.parallel=null; $("parallel-panel").hidden=true;
  $("confirmation").hidden = true; $("results").hidden = true; CityPlayMap.render([]); notice("");
}
function area() {
  return {lat: Number($("latitude").value), lon: Number($("longitude").value), radius_m: Number($("radius").value)};
}
function applyAreaLabels() {
  $("area-label").textContent = cityLabel(state.city);
  if($("library-center"))$("library-center").textContent = cityLabel(state.city) + t("library.centerSuffix");
}
function setCity(city) {
  if (state.busy || !state.presets[city]) return;
  state.city = city;if($("library-city"))$("library-city").value=city;
  document.querySelectorAll(".city-button").forEach((button) => {const selected = button.dataset.city === city; button.classList.toggle("selected", selected); button.setAttribute("aria-pressed", String(selected));});
  $("latitude").value = state.presets[city].lat;
  $("longitude").value = state.presets[city].lon;
  applyAreaLabels();
  resetDraft();
}
function addInterest(value = {kind: "entity", query: "", entity_type: "artist"}) {
  const container = $("interest-fields");
  if (container.children.length >= 3) return;
  const row = node("div", "interest-row");
  const input = node("input"); input.type = "text"; input.required = true; input.maxLength = 100; input.value = value.query; input.className = "interest-query"; input.setAttribute("aria-label", t("a11y.interest", {n: container.children.length + 1}));
  const kind = node("select", "interest-kind"); kind.setAttribute("aria-label", t("a11y.interestKind"));
  for (const [key, label] of Object.entries({entity: t("kind.entity"), tag: t("kind.tag")})) {const option = node("option", "", label); option.value = key; kind.append(option);}
  kind.value = value.kind;
  const type = node("select", "interest-type"); type.setAttribute("aria-label", t("a11y.interestType"));
  for (const key of [...Object.keys(entityTypes)]) {const option = node("option", "", typeLabel(key || "none")); option.value = key; type.append(option);}
  type.value = value.entity_type || ""; type.disabled = kind.value === "tag";
  kind.addEventListener("change", () => {type.disabled = kind.value === "tag";});
  const remove = node("button", "remove-interest", "×"); remove.type = "button"; remove.setAttribute("aria-label", t("a11y.removeInterest"));
  remove.addEventListener("click", () => {row.remove(); $("add-interest").hidden = container.children.length >= 3;});
  row.append(input, kind, type, remove); container.append(row); $("add-interest").hidden = container.children.length >= 3;
}
// Saved interests are unrestricted by the bounded per-exploration query.
function defaultTastePlan(items){
  return [...items.filter(x=>x.choice==='like').slice(-3),...items.filter(x=>x.choice==='curious').slice(-1)];
}
function renderTastePlan(container,items,plan,onChange=()=>{}){
  const signature=JSON.stringify(items.map(x=>[x.id,x.choice]));
  if(plan.signature!==signature){plan.signature=signature;plan.items=defaultTastePlan(items);}
  container.replaceChildren();container.hidden=!items.length;
  if(!items.length)return;
  container.append(node('strong','',t('plan.title')));
  const likes=plan.items.filter(x=>x.choice==='like'),curious=plan.items.filter(x=>x.choice==='curious');
  if(likes.length)container.append(node('p','',t('plan.familiar',{names:likes.map(x=>x.name).join(t('sep'))})));
  if(curious.length)container.append(node('p','',t(likes.length?'plan.curiousWith':'plan.curiousOnly',{names:curious.map(x=>x.name).join(t('sep'))})));
  if(!plan.items.length)container.append(node('p','',t('plan.empty')));
  const details=node('details');details.append(node('summary','',t('plan.changeSummary')));
  details.append(node('p','field-help',t('plan.changeHelp')));
  const choices=node('div','run-taste-options');
  for(const item of items){
    const label=node('label'),input=node('input');input.type='checkbox';input.disabled=!!plan.busy||state.busy;input.checked=plan.items.some(x=>x.id===item.id);input.value=item.id;
    input.addEventListener('change',()=>{
      plan.items=plan.items.filter(x=>x.id!==item.id);
      if(input.checked){
        const same=plan.items.filter(x=>x.choice===item.choice),limit=item.choice==='like'?3:1;
        if(same.length>=limit)plan.items=plan.items.filter(x=>x.id!==same[0].id);
        plan.items.push(item);
      }
      renderTastePlan(container,items,plan,onChange);container.querySelector('details').open=true;
      [...container.querySelectorAll('input')].find(x=>x.value===item.id)?.focus({preventScroll:true});
      onChange();
    });
    label.append(input,node('span','',`${t(item.choice==='like'?'plan.like':'plan.curious')}：${item.name}`));choices.append(label);
  }
  details.append(choices);container.append(details);
}
function checks(container, ids, selected, name, labeler = categoryLabel) {
  container.replaceChildren();
  for (const value of ids) {const label = node("label"); const input = node("input"); input.type = "checkbox"; input.name = name; input.value = value; input.checked = selected.includes(value); label.append(input, node("span", "", labeler(value))); container.append(label);}
}
function renderIntent(draft, review=true) {
  state.draft = draft;
  state.dirty = false;
  const intent = draft.intent;
  $("interest-fields").replaceChildren();
  intent.interests.forEach(addInterest);
  if (!intent.interests.length) addInterest();
  checks($("category-fields"), Object.keys(categories), intent.categories, "categories");
  checks($("exclude-fields"), Object.keys(excludeCategories), intent.exclude_categories, "exclusions", excludeLabel);
  $("minutes").value = intent.available_minutes ?? "";
  $("budget").value = intent.max_budget?.amount ?? "";
  $("currency").value = intent.max_budget?.currency || "USD";
  $("open-now").checked = intent.open_now; $("novelty").checked = intent.novelty_requested; $("strict-city").checked = intent.strict_city;
  $("default-plan").textContent = [intent.strict_city ? t("confirm.defaultBoundary") : "", intent.novelty_requested ? t("confirm.defaultNovelty") : ""].filter(Boolean).join(" ");
  $("default-plan").hidden = !$("default-plan").textContent;
  const clarifications = $("clarifications"); clarifications.replaceChildren(); clarifications.hidden = !intent.clarifications.length;
  if (intent.clarifications.length) {
    clarifications.append(node("strong", "", t("confirm.clarifyTitle")), node("p", "", t("confirm.clarifyHelp")));
    for (const message of intent.clarifications) {const label = node("label"); const input = node("input"); input.type = "checkbox"; input.checked = false; input.value = message; label.append(input, node("span", "", localizedClarification(message))); clarifications.append(label);}
  }
  $('discover-button').disabled=!!draft.city_conflict;
  if(draft.city_conflict){
    const conflict=draft.city_conflict;clarifications.hidden=false;clarifications.replaceChildren(node('strong','',t('confirm.conflictTitle')),node('p','',t('confirm.conflictHelp',{requested:cityLabel(conflict.requested),selected:cityLabel(conflict.selected)})));
    const change=node('button','secondary-button',t('confirm.changeCity',{city:cityLabel(conflict.requested)}));change.type='button';
    change.addEventListener('click',()=>{if(state.busy)return;setCity(conflict.requested);$('manual-entry').open=true;$('query-form').hidden=false;$('query-form').requestSubmit();});
    const keep=node('button','text-button',t('confirm.keepCity',{city:cityLabel(conflict.selected)}));keep.type='button';keep.addEventListener('click',()=>returnToEditor('description'));
    clarifications.append(change,keep);
  }
  $("confirmed-area").textContent = `${cityLabel(draft.city)} · ${t("confirm.center")} ${draft.area.lat.toFixed(4)}, ${draft.area.lon.toFixed(4)} · ${draft.area.radius_m / 1000} km`;
  $("intent-details").open = !intent.interests.length;
  updateIntentSummary();
  $("confirmation").hidden = false; $("results").hidden = true;
  if(review)$("confirmation").scrollIntoView({behavior: "smooth", block: "start"});
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
  const places = intent.categories.map(categoryLabel);
  const parts = [t("sum.base", {names: names.length ? t("q.l") + names.join(t("sep")) + t("q.r") : t("sum.yourInterests"), action: places.length ? t("sum.explore") + places.join(t("sep")) : t("sum.find"), km: state.draft.area.radius_m / 1000, city: cityLabel(state.draft.city)})];
  if (intent.exclude_categories.length) parts.push(t("sum.avoid", {list: intent.exclude_categories.map(excludeLabel).join(t("sep"))}));
  const limits = [];
  if (intent.available_minutes !== null) limits.push(t("sum.minutes", {n: intent.available_minutes}));
  if (intent.max_budget) limits.push(t("sum.budget", {amount: intent.max_budget.amount, currency: intent.max_budget.currency}));
  if (intent.open_now) limits.push(t("confirm.openNow"));
  if (intent.novelty_requested) limits.push(t("confirm.novelty"));
  if (intent.strict_city) limits.push(t("confirm.strictCity"));
  if (limits.length) parts.push(limits.join(" · ") + "。");
  $("intent-summary").textContent = parts.join(" ") + " " + t("sum.tail");
}
function returnToEditor(target='library') {
  document.body.classList.remove('showing-results');$('results').hidden=true;$('query-form').hidden=false;
  $('confirmation').hidden=target!=='conditions';
  if(target==='conditions'&&state.draft){
    renderIntent({...state.draft,intent:structuredClone(state.confirmedIntent||state.draft.intent),selections:{}},false);
    $('manual-entry').open=true;$('intent-details').open=true;
    $('confirmation').scrollIntoView({behavior:'smooth',block:'start'});$('discover-button').focus({preventScroll:true});
  } else if(target==='description'){
    $('manual-entry').open=true;$('query').scrollIntoView({behavior:'smooth',block:'center'});$('query').focus({preventScroll:true});
  } else {
    $('manual-entry').open=false;
    if(target==='range'){$('library-options').open=true;$('library-radius').focus();}
    else if(target==='venues'){$('library-options').open=true;$('venue-custom').click();$('venue-custom').focus();}
    else {$('library-panel').scrollIntoView({behavior:'smooth',block:'start'});$('library-query').focus({preventScroll:true});}
  }
}
function editRequest(){returnToEditor('conditions');}
function operationalFailures(result){
  const counts=result.diagnostics?.rejection_counts||{};
  return [['budget_unverified','unv.budget'],['open_now_unverified','unv.openNow'],['visit_and_travel_time_unverified','unv.travel']].filter(([key])=>counts[key]>0);
}
function exploratoryIntent(intent,failures){
  const revised=structuredClone(intent),keys=new Set(failures.map(x=>x[0]));
  if(keys.has('budget_unverified'))revised.max_budget=null;
  if(keys.has('open_now_unverified'))revised.open_now=false;
  if(keys.has('visit_and_travel_time_unverified'))revised.available_minutes=null;
  return revised;
}
function message(title, description) {
  const container = $("result-message"); container.replaceChildren(node("h3", "", title), node("p", "", description));
  const button = node("button", "text-button", t("msg.edit")); button.type = "button"; button.addEventListener("click", editRequest); container.append(button); container.hidden = false;
}
function renderChoices(question) {
  const container = $("choices"); container.replaceChildren(); container.hidden = false;
  container.append(node("h3", "", t("choice.title", {query: question.query})), node("p", "", t("choice.help")));
  const form = node("form");
  for (const candidate of question.choices || []) {
    const label = node("label", "choice-option"); const input = node("input"); input.type = "radio"; input.name = "choice"; input.value = candidate.id; input.required = true; input.checked = candidate === question.choices[0];
    const description = node("div"); description.append(node("span", "", candidate.name));
    const type = candidate.type?.replace("urn:entity:", "");
    description.append(node("small", "", `${typeLabel(type) || t("type.tag")}${candidate.release_year ? ` · ${candidate.release_year}` : ""}`));
    label.append(input, description); form.append(label);
  }
  if (!question.choices?.length) {container.append(node("p", "", t("choice.none"))); return;}
  const button = node("button", "primary-button", t("choice.submit")); button.type = "submit"; form.append(button);
  form.addEventListener("submit", async (event) => {event.preventDefault(); const selected = form.querySelector("input:checked"); if (!selected || state.busy) return; button.disabled = true; try {await discover({draft_id: state.draft.draft_id, again: true, selections: {[question.field]: selected.value}});} finally {button.disabled = false;}});
  container.append(form);
}
function renderCard(card, index) {
  const article = node("article", "experience-card");
  const top = node("div", "card-top");
  top.append(node("span", "card-number", `0${index+1}`), node("span", "card-category", categoryLabel(card.category)), node("span", "card-symbol", card.category === "coffee" ? "◉" : card.category === "live_music" ? "♫" : "▤"));
  const body = node("div", "card-body");
  const km = (card.straight_line_distance_m/1000).toFixed(1);
  body.append(node("h3", "", card.name), node("p", "card-distance", t("card.distance", {km})), node("p", "card-address", card.address));
  if(card.description)body.append(node('p','place-intro',card.description),node('small','field-help',t('card.introSource')));
  const evidence = node("div", "card-evidence"); evidence.append(node("span", "evidence-tag", t("card.tagReal")));
  const why = node('details','recommendation-reason');
  why.append(node('summary','',t('card.whySummary')));
  const contributors = card.explanation?.contributors || [];
  why.append(node('p','',contributors.length ? t("card.whyWith", {names: contributors.map(x=>x.name).join(t("sep"))}) : t('card.whyWithout')));
  if(contributors.length){
    const details=node('details');details.append(node('summary','',t('card.contributors')));
    contributors.forEach(x=>details.append(node('p','',t('card.contributor',{name:x.name,score:x.score.toFixed(2)}))));
    details.append(node('p','field-help',t('card.contributorNote')));why.append(details);
  }
  why.append(node('p','',t("card.whyFit", {category: categoryLabel(card.category), km})));
  body.append(why);
  if (card.verification.identity === "website_name_corroborated") evidence.append(node("span", "evidence-tag", t("card.tagCorroborated")));
  else evidence.append(node("span", "evidence-tag unverified", t("card.tagUnverified")));
  if (card.novelty === "not_in_provided_seen_list") evidence.append(node("span", "evidence-tag", t("card.tagExcluded")));
  body.append(evidence, node("p", "card-note", t("card.note")));
  if (card.verification.website) {
    try {const url = new URL(card.verification.website); if (url.protocol === "https:" && !url.username && !url.password) {const link = node("a", "card-link", t("card.website")); link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer"; body.append(link);}} catch (_) { /* No unvalidated hyperlink. */ }
  }
  article.id = `place-card-${index}`;
  const navigation=node('a','map-navigation',t('card.navigate'));
  navigation.href='https://www.google.com/maps/dir/?api=1&destination='+encodeURIComponent(card.location.lat+','+card.location.lon);navigation.target='_blank';navigation.rel='noopener noreferrer';body.append(navigation);
  const locate = node("button", "secondary-button", t("card.locate")); locate.type="button"; locate.addEventListener("click", () => {setResultView("map");CityPlayMap.focus(index);}); body.append(locate);
  const feedback=node('details','card-feedback');feedback.append(node('summary','',t('card.feedbackSummary')));
  for(const [reason,key] of [['not_now','card.notNow'],['too_far','card.tooFar'],['experienced_dislike','card.dislike']]){
    const b=node('button','text-button',t(key));b.type='button';b.addEventListener('click',async()=>{
      if(state.busy)return;
      await discover({draft_id:state.draft.draft_id,again:true,feedback:{entity_id:card.entity_id,reason}});
    });feedback.append(b);
  }
  feedback.append(node('small','field-help',t('card.feedbackNote')));
  body.append(feedback);article.append(top, body); return article;
}
function renderResult(result, options = {}) {
  state.result = result;document.body.classList.add("showing-results");
  const directions=$('taste-directions');directions.replaceChildren();
  const base=state.explorationBase;
  directions.hidden=!!state.parallel || !base || result.status==='needs_input';
  if(base){
    directions.append(node('strong','',t('directions.title')));
    directions.append(node('p','field-help',t('directions.help')));
    const optionsList=[[t('directions.combined'),base.interests],...(base.interests.length>1?base.interests.map(x=>[x.query,[x]]):[])];
    for(const [label,interests] of optionsList){const b=node('button','secondary-button',label);b.type='button';b.disabled=JSON.stringify(interests)===JSON.stringify(state.confirmedIntent?.interests);b.addEventListener('click',()=>{if(state.busy)return;if(state.dirty){notice(t('notice.confirmFirst'));editRequest();return;}discover({draft_id:state.draft.draft_id,intent:{...structuredClone(base),interests:structuredClone(interests)}},true);});directions.append(b);}
  }
  $("comparison-result").replaceChildren();
  $("comparison-panel").hidden = result.status !== "partial";
  const evidence=$("agent-evidence");evidence.replaceChildren();evidence.hidden=result.status!=="partial";
  if (!evidence.hidden) {
    evidence.append(node("strong", "", t("agent.signals")),node("p","",(result.taste_inputs||[]).map(x=>`${x.name}（${typeLabel(x.type?.replace("urn:entity:","")) || t("type.tag")}）`).join(t("sep"))),node("p","field-help",t("agent.signalsHelp")));
  }
  CityPlayMap.render(result.cards || [], state.draft?.area);
  document.querySelector(".result-view-controls").hidden=!(result.cards||[]).length;
  $("results").hidden = false; $("cards").replaceChildren(); $("choices").hidden = true; $("result-message").hidden = true; $("decision-details").hidden = true;
  $("again-button").hidden = result.status !== "partial";
  $("results-subtitle").textContent = "";
  if (result.status === "error") {message(t("msg.retryTitle"), errorMessage(result.error?.code, t("msg.retryBody")));}
  else if (result.status === "needs_input") {
    $("results-title").textContent = t("results.titlePlan");
    const question = result.questions.find((item) => typeof item === "object");
    if (question) renderChoices(question);
    else {
      const intent = state.confirmedIntent || readIntent();
      let description = t("msg.planDefault");
      if (intent.novelty_requested) description = t("msg.novelty");
      else if (intent.strict_city) description = t("msg.strict");
            const unresolved = (result.questions || []).filter(x => typeof x === "string");
      const reasons = unresolved.map(x => localizedClarification(x));
      message(t("msg.planTitle"), reasons.join(" ") || description);
      if (intent.interests.length) {
        const button = node("button", "primary-button", t("msg.proceed")); button.type="button";
        button.addEventListener("click", () => {const revised=structuredClone(intent);revised.clarifications=[];revised.strict_city=false;revised.novelty_requested=false;discover({draft_id:state.draft.draft_id,intent:revised});});
        $("result-message").append(node("p", "", t("msg.proceedNote")),button);
      }
    }
  } else if (result.status === "empty") {
    $("results-title").textContent = t("results.titleEmpty");
    const intent=state.confirmedIntent || readIntent();
    const container=$("result-message");container.replaceChildren();container.hidden=false;
    const noTaste=!intent.interests.length;
    const failures=operationalFailures(result);
    if(failures.length){
      container.append(node('h3','',t('empty.unverifiedTitle')),node('p','',t('empty.unverifiedBody',{list:failures.map(x=>t(x[1])).join(t('sep'))})));
      const keep=node('button','secondary-button',t('empty.keep'));keep.type='button';keep.addEventListener('click',()=>returnToEditor('conditions'));
      const relax=node('button','text-button',t('empty.relax'));relax.type='button';
      relax.addEventListener('click',()=>{if(!state.busy)discover({draft_id:state.draft.draft_id,intent:exploratoryIntent(intent,failures)});});
      container.append(keep,relax,node('p','field-help',t('empty.relaxNote')));
    } else {

    container.append(node('p','',noTaste ? t('empty.noTaste') : t('empty.hasTaste')));
    if(intent.max_budget || intent.available_minutes || intent.open_now)container.append(node('p','field-help',t('empty.constraints')));
    const change=node('button','secondary-button',noTaste?t('empty.changeTaste'):t('empty.changeVenue'));change.type='button';
    change.addEventListener('click',()=>{if(!state.busy)returnToEditor(noTaste?'library':'venues');});container.append(change);
    if(!noTaste){const range=node('button','text-button',t('empty.adjustRange'));range.type='button';range.addEventListener('click',()=>{if(!state.busy)returnToEditor('range');});container.append(range);}

    }
  } else {
    $("results-title").textContent = t("results.titlePartial");
    result.cards.forEach((card, index) => $("cards").append(renderCard(card, index)));
    const source = result.cache_origin==="sqlite"?t("src.sqlite"):{live_qloo: t("src.live"), cached_qloo: t("src.cached"), mixed_qloo: t("src.mixed")}[result.source] || t("src.fallback");
    $("results-subtitle").textContent = t("results.subtitle", {count: result.cards.length});
    $("decision-details").hidden = false;
    const detail = $("decision-content"); detail.replaceChildren(); detail.append(node("p","", t("decision.source", {source})));
    for (const [titleKey, descriptionKey] of [["decision.why1t", "decision.why1d"], ["decision.why2t", "decision.why2d"], ["decision.why3t", "decision.why3d"]]) {const section = node("div"); section.append(node("strong", "", t(titleKey)), node("span", "", t(descriptionKey))); detail.append(section);}
  }
  if (options.scroll !== false) $("results").scrollIntoView({behavior: "smooth", block: "start"});
}
function proposeDiscoveryStep(result, confirmedIntent, draftId) {
  const question = result.questions?.find(x => x && typeof x === "object");
  if (!question) return null;
  const position = /^interests\.(\d+)$/.exec(question.field);
  const interest = position && confirmedIntent?.interests[Number(position[1])];
  const expectedType = interest?.kind === "entity" && interest.entity_type ? "urn:entity:" + interest.entity_type : null;
  const candidates = (question.choices || []).filter(x => typeof x.id === "string" && x.id && typeof x.name === "string" && (!expectedType || x.type === expectedType));
  const identityName = value => String(value).normalize('NFKC').toLocaleLowerCase().replace(/[\s·•・《》「》“”"'’]/gu,'');
  const matching = candidates.filter(x => identityName(x.name) === identityName(question.query));
  const choice = matching.length === 1 ? matching[0] : null;
  if (choice) return {payload:{draft_id:draftId,again:true,selections:{[question.field]:choice.id}}};
  const match = /^interests\.(\d+)$/.exec(question.field);
  if (!match || !confirmedIntent) return null;
  const intent = structuredClone(confirmedIntent);
  const index = Number(match[1]);
  if (index >= intent.interests.length) return null;
  intent.interests.splice(index, 1);
  return {intent,payload:{draft_id:draftId,intent},terminal:!intent.interests.length};
}

async function discover(payload, keepBase=false) {
  if (state.busy) return;
  if (payload.again && state.dirty) {notice(t("notice.confirmAgain")); editRequest(); return;}
  if (payload.intent) {state.confirmedIntent = structuredClone(payload.intent); state.dirty = false;if(!keepBase)state.explorationBase=structuredClone(payload.intent);}
  setBusy(true);
  try {
    let result = await job("/api/discover", payload);
    for (let attempt = 0; attempt < 4 && result.status === "needs_input"; attempt++) {
      const step = proposeDiscoveryStep(result, state.confirmedIntent, state.draft.draft_id);
      if (!step) break;
      if (step.terminal) {result={...result,status:"empty",questions:[],cards:[]};break;}
      if (step.intent) state.confirmedIntent=step.intent;
      result = await job("/api/discover", step.payload);
    }
    renderResult(result);
    if(payload.feedback)notice(result.status==='error' ? t('notice.feedbackRetry') : (payload.feedback.reason==='too_far'?t('notice.feedbackNear'):t('notice.feedbackSkip')));
    // Candidate-resolution diagnostics stay out of the user-facing recommendation copy.
  } catch (error) {showError(error);} finally {setBusy(false);}
}

function renderParallel(){
  const panel=$('parallel-panel');panel.hidden=!state.parallel;if(!state.parallel)return;
  $('taste-directions').hidden=true;
  const list=$('parallel-versions');list.replaceChildren();
  for(const version of state.parallel.versions){
    const card=node('article','parallel-version');
    const title=versionText(version,'title',version.title);
    const b=node('button','secondary-button',t('parallel.explore',{title}));b.type='button';
    b.setAttribute('aria-pressed',String(state.parallel.active===version.id));
    b.addEventListener('click',()=>activateParallel(version.id));
    card.append(node('h3','',title),node('p','',versionText(version,'subtitle',version.subtitle)));
    const previews=node('ul','version-preview');
    const familiarIds=new Set((state.parallel.versions[0]?.result.cards||[]).map(x=>x.entity_id));
    const previewCards=[...(version.result.cards||[])].sort((a,b)=>version.id==='familiar'?0:Number(familiarIds.has(a.entity_id))-Number(familiarIds.has(b.entity_id)));
    for(const place of previewCards.slice(0,2))previews.append(node('li','',place.name));
    const bridges=(version.path||[]).map(x=>x.from.join(t('sep'))+' → '+x.to);
    const types=[...new Set((version.result.cards||[]).map(x=>categoryLabel(x.category)))];
    card.append(node('p','version-evidence',bridges.length?t('parallel.bridgePrefix')+bridges.join(t('sep')):t('parallel.bridgePrefix')+(version.result.taste_inputs||[]).map(x=>x.name).join(t('sep'))));
    if(types.length)card.append(node('p','',t('parallel.previewTypes',{types:types.join(' · ')})));
    card.append(previews,b,node('small','field-help',t('parallel.versionCount',{count:version.result.cards?.length||0,status:version.result.status==='error'?t('vs.error'):version.result.status==='needs_input'?t('vs.needs'):t('vs.actual')})));
    if(version.id!=='familiar'){
      const familiar=new Set((state.parallel.versions[0]?.result.cards||[]).map(x=>x.entity_id));
      const shared=(version.result.cards||[]).filter(x=>familiar.has(x.entity_id)).length;
      card.append(node('p','field-help',t('parallel.shared',{count:shared})));
    }
    list.append(card);
  }
  if(!state.parallel.versions.some(x=>x.id==='alternative')){
    const card=node('article','parallel-version');card.append(node('strong','',t('parallel.altCardTitle')),node('p','',t('parallel.altCardHelp')),node('small','field-help',t('parallel.altCardNote')));list.append(card);
  }
  const active=state.parallel.versions.find(x=>x.id===state.parallel.active);
  const path=$('parallel-path');path.replaceChildren();
  if(active){path.append(node('strong','',t('parallel.pathTitle',{title:versionText(active,'title',active.title)})));
    const links=active.path||[];
    if(links.length)for(const link of links){path.append(node('p','',t('parallel.pathStep',{from:link.from.join(t('sep')),to:link.to})));path.append(node('small','field-help',t('parallel.pathBridgeNote')));}
    else path.append(node('p','',active.id==='familiar'?t('parallel.pathFamiliar'):t('parallel.pathAlternative')));
    path.append(node('p','field-help',versionText(active,'boundary',active.boundary)));
  }
}
async function activateParallel(version){
  if(state.busy)return;if(state.dirty){notice(t('notice.confirmFirst'));return;}
  setBusy(true);
  try{const selected=await request('/api/parallel/select',{draft_id:state.draft.draft_id,version});
    state.parallel.active=version;state.confirmedIntent=structuredClone(selected.intent);
    renderResult(selected.result);renderParallel();
  }catch(e){showError(e);}finally{setBusy(false);}
  if(state.result?.status==='needs_input')await discover({draft_id:state.draft.draft_id,again:true});
}
async function buildParallel(){
  if(state.busy||!state.draft)return;
  if(state.dirty){notice(t('notice.confirmFirst'));return;}
  const query=$('alternative-query').value.trim();
  const payload={draft_id:state.draft.draft_id};
  if(query)payload.alternative={kind:'entity',query,entity_type:$('alternative-type').value};
  setBusy(true,'parallel');$('parallel-status').textContent=t('parallel.statusBuilding');
  try{state.parallel=await job('/api/parallel',payload);state.parallel.active='familiar';renderParallel();
    $('parallel-status').textContent=t('parallel.statusDone');
  }catch(e){showError(e);$('parallel-status').textContent=t('parallel.statusFailed');}
  finally{setBusy(false);}
  if(state.parallel)await activateParallel('familiar');
}
$('parallel-build').addEventListener('click',buildParallel);
async function prepareTaste(){
  if(state.busy||!state.csrf)return;
  if(!$('latitude').reportValidity()||!$('longitude').reportValidity())return;
  const interests=['artist','movie','book'].map(entity_type=>({kind:'entity',query:$('seed-'+entity_type).value.trim(),entity_type})).filter(x=>x.query);
  if(!interests.length){notice(t('notice.seedRequired'));return;}
  resetDraft();setBusy(true,'parse');
  try{renderIntent(await request('/api/taste/prepare',{city:state.city,area:area(),interests,categories:selectedVenueCategories('seed')}),false);}
  catch(e){showError(e);}finally{setBusy(false);}
  if(state.draft)await launchParallel();
}



$("query-form").addEventListener("submit", async (event) => {
  event.preventDefault(); if (state.busy || !state.csrf) return;
  if(state.inputMode!=="natural"){await prepareTaste();return;}
  if(!$("query").value.trim()){notice(t("notice.queryRequired"));return;}
  if(!modelConfig.key && !state.modelReady){notice(t("model.requiredNotice"));openModelConfig();return;}
  resetDraft(); setBusy(true, "parse");
  try {const draft = await job("/api/parse", {query: $("query").value.trim(), city: state.city, area: area()}); renderIntent(draft,!!draft.intent.clarifications.length);} catch (error) {showError(error);} finally {setBusy(false);}
  if(state.draft){const i=state.draft.intent;if(!i.clarifications.length&&!i.strict_city&&!i.novelty_requested&&!i.open_now&&!i.max_budget&&!i.available_minutes)await launchParallel();else $("confirmation").scrollIntoView({behavior:"smooth",block:"start"});}
});
$("confirm-form").addEventListener("invalid", () => {$("intent-details").open = true;}, true);
async function launchParallel(){
  if(!state.draft||state.busy)return;
  state.parallel=null;$('parallel-panel').hidden=true;
  $('query-form').hidden=true;$('confirmation').hidden=true;
  await discover({draft_id:state.draft.draft_id,intent:readIntent(),selections:state.draft.selections||{}});
  if(state.result?.status==='partial'){notice(t('notice.firstReady'));await buildParallel();}
}
$("confirm-form").addEventListener("submit",async event=>{event.preventDefault();await launchParallel();});

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
  const examples = {books: "example.books", coffee: "example.coffee", movie: "example.movie"};
  setInputMode("natural"); $("query").value = t(examples[button.dataset.example]); $("query").focus();
}));
function modelStatus(){
  $("model-config-open").classList.toggle("ready", !!(modelConfig.key || state.modelReady));
  $("model-config-status").textContent = modelConfig.key ? t("model.statusOwn") : state.modelReady ? t("model.statusServer") : t("model.statusNone");
}
function openModelConfig(open = true){
  const panel = $("model-config");
  panel.hidden = !open;
  $("model-config-open").setAttribute("aria-expanded", String(open));
  if (open) {modelStatus(); $("model-key-input").focus();}
}
$("model-config-open").addEventListener("click", () => openModelConfig($("model-config").hidden));
$("model-config-close").addEventListener("click", () => openModelConfig(false));
$("model-name-select").addEventListener("change", () => {
  const custom = $("model-name-select").value === "__custom__";
  $("model-custom-input").hidden = !custom;
  if (custom) $("model-custom-input").focus();
});
$("model-config-save").addEventListener("click", () => {
  const value = $("model-key-input").value.trim();
  if (!value) {$("model-config-status").textContent = t("model.empty"); return;}
  const selected = $("model-name-select").value;
  const name = selected === "__custom__" ? $("model-custom-input").value.trim() : selected;
  if (selected === "__custom__" && !name) {$("model-config-status").textContent = t("model.customEmpty"); return;}
  modelConfig.key = value; modelConfig.name = name;
  $("model-key-input").value = "";
  openModelConfig(false); modelStatus(); notice(t("model.saved"));
});
$("model-config-clear").addEventListener("click", () => {
  modelConfig.key = ""; $("model-key-input").value = "";
  modelStatus(); notice(t("model.cleared"));
});
request("/api/session").then((session) => {
  state.csrf = session.csrf; state.presets = session.presets; state.qlooReady = session.configured.qloo; state.modelReady = session.configured.model; document.dispatchEvent(new Event("cityplay-ready"));
  $("service-status-text").textContent = session.configured.qloo ? t("status.ready") : t("status.unconfigured");
  modelStatus();
  if (!session.configured.qloo) notice(t("notice.configureQloo"));
}).catch(() => {$("service-status-text").textContent = t("status.unreachable"); notice(t("notice.serviceUnreachable"));});

$("compare-button").addEventListener("click", async () => {
  if (state.busy || !state.draft || !state.result) return;
  if (state.dirty) {notice(t("compare.dirty"));return;}
  const original=state.result;
  const output=$("comparison-result");output.replaceChildren(node("p","",t("compare.loading")));setBusy(true);
  try {
    const baseline=await job("/api/compare",{draft_id:state.draft.draft_id});output.replaceChildren();
    if (baseline.status==="error") {output.append(node("p","",errorMessage(baseline.error?.code, t("compare.error"))));return;}
    if (baseline.status==="needs_input") {output.append(node("p","",t("compare.needsInput")));return;}
    const common=baseline.cards.filter(x=>original.cards.some(y=>x.entity_id===y.entity_id)).length;
    output.append(node("p","",t("compare.result",{taste:original.cards.length,base:baseline.cards.length,common})));
    const list=node("ol");for(const card of baseline.cards)list.append(node("li","",`${card.name} · ${card.address}`));output.append(list);
    if(!baseline.cards.length)output.append(node("p","",t("compare.empty")));
  } catch(error){output.replaceChildren(node("p","",errorMessage(error.code, t("compare.retry"))));}finally{setBusy(false);}
});

function setInputMode(mode){
  state.inputMode=mode;
  $('structured-input').hidden=mode!=='structured';$('natural-input').hidden=mode!=='natural';
  document.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));
}
document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>setInputMode(b.dataset.mode)));
function setResultView(view){
  $('result-layout').dataset.view=view;
  document.querySelectorAll('[data-view]').forEach(b=>{if(b.tagName==='BUTTON')b.setAttribute('aria-pressed',String(b.dataset.view===view));});
  if(view==='map')CityPlayMap.resize();
}
document.querySelectorAll('.result-view-controls button').forEach(b=>b.addEventListener('click',()=>setResultView(b.dataset.view)));
$('edit-exploration').addEventListener('click',()=>{if(!state.busy)returnToEditor();});
// Re-render dynamic sections when the language changes; in-progress edits are kept.
document.addEventListener('cityplay-lang-changed',()=>{
  applyAreaLabels();
  if(state.qlooReady!==null)$('service-status-text').textContent=state.qlooReady?t('status.ready'):t('status.unconfigured');
  if(document.getElementById('model-config-status'))modelStatus();
  if(state.busy)return;
  if(state.draft&&!state.dirty)renderIntent(structuredClone(state.draft),false);
  if(state.parallel)renderParallel();
  if(state.result)renderResult(state.result,{scroll:false});
});
