"use strict";
(() => {
  const questions = [
    ['evening', '忙完一天，什么最能给你充电？', ['听音乐', '看电影', '阅读', '散步', '玩游戏', '什么都不做']],
    ['weekend', '突然多出半天假，你想去哪儿？', ['逛书店', '喝咖啡', '看展览', '公园散步', '听现场音乐', '找好吃的']],
    ['recent', '最近哪件小事，让你觉得“真有意思”？', ['一首歌', '一部电影', '一本书', '一道美食', '一次旅行', '暂时想不到']],
    ['investment', '哪种体验，值得你多花一点时间？', ['音乐演出', '美食探索', '运动', '手工创作', '旅行', '慢慢放松']],
    ['company', '这次出门，哪种节奏更舒服？', ['自己自在逛', '和一个熟人', '约几个朋友', '认识新朋友', '看当天心情']],
    ['wish', '有没有心动、却还没试过的事？', ['陶艺', '舞蹈', '露营', '漂流', '摄影', '还没有想法']],
  ];
  const labels = {existing_interests:'我的已有兴趣',potential_interests:'可能喜欢的新体验 · 待体验',experience_motivations:'可能的体验动机',dislikes:'可能不喜欢的活动'};
  const g = {step:0,answers:{},draft:null,busy:false,rows:[],generation:0};
  const dialog = $('guess-dialog'), content=$('guess-content'), actions=$('guess-actions');
  function error(message='') {$('guess-error').textContent=message;}
  function button(label, handler, primary=false) {const b=node('button',primary?'primary-button':'secondary-button',label);b.type='button';b.addEventListener('click',handler);actions.append(b);return b;}
  function saveAnswer() {
    const selected=[...content.querySelectorAll('[aria-pressed="true"]')].map(x=>x.textContent);
    const custom=$('guess-custom')?.value.trim();if(custom)selected.push(custom);
    const id=questions[g.step][0];if(selected.length)g.answers[id]=selected.join('；');else delete g.answers[id];
  }
  function renderQuestion() {
    error();g.draft=null;content.replaceChildren();actions.replaceChildren();
    const [id,title,options]=questions[g.step];
    content.append(node('p','guess-progress',`${g.step+1} / ${questions.length} · ${cities[state.city]} · 可多选，也可跳过`),node('h3','',title));
    const cards=node('div','guess-options');const previous=(g.answers[id]||'').split('；');
    for(const option of options){const b=node('button','guess-option',option);b.type='button';b.setAttribute('aria-pressed',String(previous.includes(option)));b.addEventListener('click',()=>b.setAttribute('aria-pressed',String(b.getAttribute('aria-pressed')!=='true')));cards.append(b);}
    const label=node('label','guess-custom-label','或者，用自己的话说说（可选）');const input=node('input');input.id='guess-custom';input.type='text';input.maxLength=220;input.placeholder='比如：喜欢 Jazz，不喜欢拥挤的地方';input.value=previous.filter(x=>!options.includes(x)).join('；');label.append(input);
    content.append(cards,label,node('p','field-help','不用填写姓名、联系方式或收入。答案仅用于本次模型推断。'));
    if(g.step)button('上一题',()=>{saveAnswer();g.step--;renderQuestion();});
    button('跳过',()=>{delete g.answers[id];advance();});
    button(g.step===questions.length-1?'看看我的兴趣草稿':'下一题 →',()=>{saveAnswer();advance();},true);
  }
  function advance(){if(g.step<questions.length-1){g.step++;renderQuestion();}else generate();}
  async function generate(){
    if(g.busy)return;if(!Object.keys(g.answers).length){error('还没有答案。可以选一张卡片，也可以退出继续手动填写。');return;}
    if(g.draft){g.draft.profile.profile_name=$('profile-name').value;g.draft.profile.summary=$('profile-summary').value;}
    g.busy=true;error();const generation=++g.generation;
    const savedContent=[...content.childNodes],savedActions=[...actions.childNodes];
    content.replaceChildren(node('p','guess-loading','正在找出答案里的小线索…'),node('p','field-help','这只是草稿，你可以只留下认同的部分。'));actions.replaceChildren();
    try{
      const started=await request('/api/guess',{answers:g.answers});let result;
      for(;;){await new Promise(r=>setTimeout(r,800));const current=await request(`/api/jobs/${encodeURIComponent(started.job_id)}`);if(current.status==='failed')throw current.error;if(current.status==='completed'){result=current.result;break;}}
      if(generation===g.generation){g.draft=result;renderProfile();}
    }catch(e){if(generation===g.generation){content.replaceChildren(...savedContent);actions.replaceChildren(...savedActions);error(errors[e.code]||'画像暂时没有生成成功。答案还在，点击重试即可。');}}
    finally{g.busy=false;}
  }
  function renderProfile(){
    error();content.replaceChildren();actions.replaceChildren();g.rows=[];const p=g.draft.profile;
    content.append(node('p','guess-progress','兴趣草稿 · 勾选才会保存 · 名称和标签均可编辑'));
    const title=node('input');title.type='text';title.id='profile-name';title.maxLength=60;title.value=p.profile_name;title.setAttribute('aria-label','兴趣类型名称');
    const summary=node('input');summary.type='text';summary.id='profile-summary';summary.maxLength=200;summary.value=p.summary;summary.setAttribute('aria-label','兴趣简介');content.append(title,summary);
    for(const [group,label] of Object.entries(labels)){
      const section=node('section','profile-group');section.append(node('h3','',label));const list=node('div');section.append(list);
      for(const item of p[group])addRow(list,group,item);
      if(!p[group].length)list.append(node('p','field-help','目前没有足够依据，先留空。'));
      const add=node('button','text-button','＋ 补充一项');add.type='button';add.addEventListener('click',()=>addRow(list,group,{id:null,name:'',source:'user_input',confidence:null,reason:'用户主动补充',evidence:null}));section.append(add);content.append(section);
    }
    content.append(node('p','field-help','潜在兴趣保持“想尝试”的语义，避免项单独填入。体验动机仅保存为扩展字段。本地确认记录不含未选标签，关闭页面不会自动应用草稿。'));
    button('返回改答案',()=>{g.step=0;renderQuestion();});button('重新生成',generate);button('确认并填入爱好',apply,true);
  }
  function addRow(list,group,item){
    const row=node('div','profile-item');const head=node('div','profile-item-head');const selected=node('input');selected.type='checkbox';selected.checked=group==='existing_interests';selected.setAttribute('aria-label','确认 '+(item.name||'补充标签'));
    const input=node('input');input.type='text';input.value=item.name;input.maxLength=60;input.setAttribute('aria-label','标签名称');const remove=node('button','text-button','删除');remove.type='button';remove.addEventListener('click',()=>{row.remove();record.removed=true;});head.append(selected,input,remove);row.append(head);
    const source=item.source==='user_answer'?'回答中明确表达':item.source==='user_input'?'我主动补充':'AI 推测';const confidence={high:'高',medium:'中',low:'低'}[item.confidence];row.append(node('p','profile-attribution',source+(confidence?` · 依据置信度：${confidence}`:'')));
    const details=node('details','profile-evidence');details.append(node('summary','','为什么这样猜？'),node('p','',item.reason));if(item.evidence)details.append(node('blockquote','',item.evidence.quote));row.append(details);list.append(row);
    const record={row,selected,input,group,item,removed:false};g.rows.push(record);
  }
  async function apply(){
    if(g.busy)return;const items=g.rows.filter(r=>!r.removed&&r.selected.checked).map(r=>({id:r.item.id,group:r.group,name:r.input.value.trim()}));
    if(!items.length){error('选一项认同的内容即可，不必接受整个画像。');return;}
    g.busy=true;actions.querySelectorAll('button').forEach(b=>b.disabled=true);error();
    try{const result=await request('/api/profile/confirm',{draft_id:g.draft.draft_id,profile_name:$('profile-name').value,summary:$('profile-summary').value,items,existing_text:$('query').value});$('query').value=result.merged_text;resetDraft();dialog.close();g.draft=null;g.answers={};g.step=0;notice('已合并你确认的兴趣，原有文字已保留。还可以编辑，再点击“理解我的需求”。');$('query').focus();}
    catch(e){error(errors[e.code]||'确认未完成，请检查标签内容后重试。');}
    finally{g.busy=false;actions.querySelectorAll('button').forEach(b=>b.disabled=false);}
  }
  function close(){if(g.busy){dialog.close();return;}if(!g.draft&&$('guess-custom'))saveAnswer();dialog.close();}
  $('guess-open').addEventListener('click',()=>{if(state.busy||!state.csrf)return;if(!g.busy){if(g.draft)renderProfile();else renderQuestion();}dialog.showModal();});
  $('guess-close').addEventListener('click',close);dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
})();
