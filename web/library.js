"use strict";
function mergeCulturalResults(local,online){
  const cards=new Map();
  for(const item of local)cards.set(item.id,{...item,display_source:t('library.srcLocal')});
  for(const item of online)cards.set(item.id,{...item,display_source:t('library.srcOnline')});
  return [...cards.values()];
}
function culturalMatch(card,query){
  const normalize=x=>String(x).normalize('NFKC').toLowerCase().replace(/[\s·•・《》「》“”"'’]/gu,'');
  const target=normalize(query);if(!target)return false;
  return [card.name,...(card.aliases||[]).map(x=>x.value)].some(x=>typeof x==='string'&&normalize(x)===target);
}
function rankCulturalResults(cards,query){return [...cards].sort((a,b)=>Number(culturalMatch(b,query))-Number(culturalMatch(a,query)));}
function restoreCulturalFocus(container,key){
  if(!key)return;
  const button=[...container.querySelectorAll('button')].find(x=>x.dataset.focusKey===key);
  (button||container.querySelector('button'))?.focus({preventScroll:true});
}
function collectVenueExclusions(custom,checkboxes){return [...new Set([...custom,...[...checkboxes].map(x=>x.value)])];}
function parseVenueExclusions(value,labels){
  // Bilingual aliases so "no cafes" and "不要咖啡馆" resolve to the same category.
  const aliases={coffee:['咖啡馆','咖啡店','cafe','cafes','café','cafés','coffee shop','coffee shops'],bookstore:['书屋','bookshop','bookshops','book store','bookstores'],live_music:['音乐现场','live music','live music venue','concert venue'],restaurant:['餐馆','饭店','restaurant','restaurants','diner','diners'],bakery:['面包店','甜品店','bakery','bakeries'],cinema:['影院','cinema','cinemas','movie theater','movie theatres'],theater:['剧场','theater','theatre','theaters','theatres'],clothing:['服装店','clothing store','clothing stores','clothing shop'],hotel:['旅馆','hotel','hotels'],mall:['购物中心','mall','malls','shopping mall','shopping malls'],recording_studio:['录音棚','recording studio','recording studios'],tourist_attraction:['景点','tourist attraction','tourist attractions','attraction'],museum:['博物馆','museum','museums'],park:['公园','park','parks'],gallery:['画廊','art gallery','art galleries','gallery']};
  const lookup=new Map();
  for(const [id,label] of Object.entries(labels))for(const name of [id,label,...(aliases[id]||[])])lookup.set(name.toLowerCase(),id);
  const matched=[],unknown=[];
  for(let token of value.split(/[、，,；;\n]|以及|还有|和|与|\band\b/)){
    token=token.trim().replace(/^(?:这次)?(?:我)?(?:不想去|不要去|避开|不去|不要|避免|排除|avoid\s+|no\s+)/i,'').trim().replace(/[。.!！]+$/,'').trim();
    if(!token)continue;
    const id=lookup.get(token.toLowerCase());
    if(id){if(!matched.includes(id))matched.push(id);}else unknown.push(token);
  }
  return {matched,unknown};
}
(() => {
  const l={domain:'all',query:'',offset:0,cards:[],choices:[],total:0,busy:false,plan:{},searchResults:null};
  const message=value=>$('library-status').textContent=value;
  function render(){
    document.querySelectorAll('#library-search button,#library-domains button,.library-plan select,#venue-discovery button,#venue-discovery input,.library-exclusions input,.library-exclusions button,#library-refresh,#library-next,#library-query').forEach(x=>x.disabled=l.busy||state.busy);
    const list=$('library-cards'),focusKey=document.activeElement?.dataset?.focusKey;
    list.replaceChildren();
    const others=node('details','other-cultural-results'),related=node('div','culture-grid');let matched=0,otherCount=0;

    for(const card of l.cards){
      const article=node('article','culture-card');const current=l.choices.find(x=>x.id===card.id);
      article.dataset.selected=current?.choice||'';
      const zh=(card.aliases||[]).find(x=>x.language.toLowerCase().startsWith('zh'));
      article.append(node('small','field-help',typeLabel(card.entity_type)+(card.year?' · '+card.year:'')+(card.display_source?' · '+card.display_source:'')),node('h3','',zh?.value||card.name));
      if(zh&&zh.value!==card.name)article.append(node('p','field-help',card.name));
      if(card.detail&&card.detail!==card.name&&card.detail!==String(card.year||''))article.append(node('p','field-help',card.detail));
      const controls=node('div','culture-choices');
      for(const [choice,key] of [['like','plan.like'],['curious','plan.curious'],['skip','library.skip']]){
        const b=node('button','text-button',t(key));b.type='button';b.dataset.focusKey=card.id+':'+choice;b.disabled=l.busy;b.setAttribute('aria-pressed',String(current?.choice===choice));
        b.addEventListener('click',async()=>{
          if(l.busy||state.busy)return;
          if(choice==='skip'){l.cards=l.cards.filter(x=>x.id!==card.id);render();return;}
          l.busy=true;
          try{const r=await request('/api/library/choice',{id:card.id,choice:current?.choice===choice?'clear':choice});l.choices=r.choices;message(t('library.saved'));}
          catch(e){message(errorMessage(e.code,t('library.saveFailed')));}
          finally{l.busy=false;render();}
        });controls.append(b);
      }
      article.append(controls);
      if(l.query&&!culturalMatch(card,l.query)){related.append(article);otherCount++;}else{list.append(article);matched++;}
    }
    if(l.query&&otherCount){
      if(!matched)list.prepend(node('p','cultural-group-title',t('library.groupTitle')));
      others.append(node('summary','',t('library.others',{count:otherCount})),related);others.open=l.offset>0;list.append(others);
    }
    if(!l.query&&!l.cards.length&&!l.busy){
      const prompts=node('div','starter-prompts');prompts.append(node('p','field-help',t('library.starterHelp')));
      for(const name of ['Miles Davis','The Matrix','The Little Prince']){const b=node('button','secondary-button',name+' ↗');b.type='button';b.addEventListener('click',()=>{$('library-query').value=name;searchOnline();});prompts.append(b);}list.append(prompts);
    }
    if(!l.cards.length&&(l.query||l.busy))list.append(node('p','field-help',l.busy?t('library.searching'):l.total?t('library.pageDone'):l.query?t('library.noMatch'):t('library.empty')));
    const selected=$('library-selected');selected.replaceChildren();
    if(l.choices.length){
      const saved=node('details','saved-tastes'),likes=l.choices.filter(x=>x.choice==='like').length;
      saved.append(node('summary','',t('library.myLibrary',{likes,curious:l.choices.length-likes})));
      const all=node('div','saved-taste-options');
      for(const card of l.choices){const b=node('button','text-button',`${t(card.choice==='like'?'plan.like':'plan.curious')}: ${card.name} ×`);b.type='button';b.disabled=l.busy||state.busy;b.addEventListener('click',async()=>{
        if(state.busy||l.busy)return;try{l.choices=(await request('/api/library/choice',{id:card.id,choice:'clear'})).choices;render();}catch(e){message(errorMessage(e.code,t('library.removedFailed')));}
      });all.append(b);}
      saved.append(all);selected.append(saved);
      const run=node('section','run-taste-plan');selected.append(run);
      l.plan.busy=l.busy||state.busy;renderTastePlan(run,l.choices,l.plan,()=>{$('library-go').dataset.hasPlan=String(!!l.plan.items.length);$('library-go').disabled=!l.plan.items.length||l.busy||state.busy;});
    }else l.plan={items:[]};
    $('library-go').dataset.hasPlan=String(!!l.plan.items?.length);
    $('library-go').disabled=!l.plan.items?.length||l.busy||state.busy;
    $('library-clear').hidden=!l.choices.length;
    $('library-refresh').textContent=l.query?t('library.rerunSearch'):t('library.discoverMore');
    $('library-next').dataset.canPage=String(l.total>6);
    $('library-next').disabled=l.busy||state.busy||l.total<=6;
    $('library-next').textContent=l.query&&l.total>6?t('library.moreResults',{page:Math.floor(l.offset/6)+1,total:Math.ceil(l.total/6)}):t('library.nextSet');
    if(!l.busy&&!state.busy)restoreCulturalFocus(list,focusKey);
    document.querySelectorAll('#library-domains button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.domain===l.domain)));
  }
  function searchPage(){
    l.searchResults=rankCulturalResults(l.searchResults,l.query);l.total=l.searchResults.length;l.cards=l.searchResults.slice(l.offset,l.offset+6);render();
  }
  function qlooAvailable(){return !!(modelConfig.qlooKey||state.qlooReady);}
  async function discoverMore({auto=false}={}){
    if(l.busy||state.busy||!state.csrf)return false;
    if($('library-query').value.trim()){await searchOnline();return true;}
    if(!qlooAvailable()){
      if(!auto){notice(t('qloo.requiredNotice'));openModelConfig();}
      return false;
    }
    l.query='';l.searchResults=null;l.busy=true;message(t('library.findingMore'));render();
    try{
      await job('/api/taste/cards',{domain:l.domain,page:(l.editorPage=l.total?1-(l.editorPage||0):0),query:''});
      l.offset=0;await browse({skipAuto:true});
      return true;
    }catch(e){
      message(errorMessage(e.code,t('library.moreFailed')));
      return false;
    }finally{l.busy=false;render();}
  }
  async function browse({skipAuto=false}={}){
    const query=l.query,domain=l.domain,offset=l.offset;
    try{
      const r=await request('/api/library/browse',{domain,query,offset});
      if(query!==l.query||domain!==l.domain||offset!==l.offset)return;
      l.choices=r.choices;
      if(l.query&&l.searchResults!==null){render();return;}
      l.cards=r.cards;l.total=r.total;render();
      message(r.total?t('library.browseCount',{count:r.total}):t('library.browseEmpty'));
      // Local discovery feed is empty: pull editorial starters once Qloo is ready.
      if(!skipAuto&&!l.query&&!l.cards.length&&qlooAvailable())await discoverMore({auto:true});
    }catch(e){message(errorMessage(e.code,t('library.browseFailed')));}
  }
  async function searchOnline(){
    if(l.busy||state.busy||!state.csrf)return;
    l.query=$('library-query').value.trim();l.offset=0;
    if(!l.query){l.searchResults=null;await browse();return;}
    l.busy=true;l.searchResults=[];searchPage();message(t('library.searchingOnline'));
    let local=[];
    try{
      try{
        const saved=await request('/api/library/browse',{domain:l.domain,query:l.query,offset:0});
        local=saved.cards;l.choices=saved.choices;
        l.searchResults=mergeCulturalResults(local,[]);searchPage();
        message(local.length?t('library.localFirst',{count:local.length}):t('library.queryingQloo'));
      }catch(e){if(e.code==='SENSITIVE_INPUT_REJECTED')throw e;}
      const online=await job('/api/taste/cards',{domain:l.domain,page:0,query:l.query});
      l.searchResults=mergeCulturalResults(local,online.cards);searchPage();
      message(online.partial?t('library.searchPartial',{count:l.total}):
        t('library.searchDone',{count:online.cards.length,total:l.total}));
    }catch(e){
      message(e.code==='SENSITIVE_INPUT_REJECTED'?t('library.sensitive'):
        t('library.onlineFailedPrefix')+errorMessage(e.code,t('err.GENERIC'))+(local.length?t('library.keptLocal',{count:local.length}):t('library.retryHint')));
    }finally{l.busy=false;render();}
  }
  $('library-search').addEventListener('submit',e=>{e.preventDefault();searchOnline();});
  document.querySelectorAll('#library-domains button').forEach(b=>b.addEventListener('click',()=>{
    if(l.busy||state.busy)return;l.domain=b.dataset.domain;l.offset=0;
    if($('library-query').value.trim())searchOnline();else{l.query='';l.searchResults=null;browse();}
  }));
  $('library-next').addEventListener('click',()=>{
    if(l.busy||state.busy)return;l.offset=l.offset+6<l.total?l.offset+6:0;
    if(l.searchResults!==null)searchPage();else browse();
  });
  $('library-refresh').addEventListener('click',()=>{discoverMore();});
  $('library-clear').addEventListener('click',async()=>{if(l.busy||state.busy)return;try{await request('/api/library/clear',{});l.choices=[];render();message(t('library.cleared'));}catch(e){message(errorMessage(e.code,t('library.clearFailed')));}});
  $('library-city').addEventListener('change',()=>setCity($('library-city').value));
  function renderVenueChoices(){
    checks($('venue-choices'),Object.keys(categories),selectedVenueCategories(),'venue-directions');
  }
  renderVenueChoices();
  function venueMode(custom){
    if(l.busy||state.busy)return;
    $('venue-auto').setAttribute('aria-pressed',String(!custom));$('venue-custom').setAttribute('aria-pressed',String(custom));$('venue-choices').hidden=!custom;
    state.venueDirty=true;$('seed-category').value=selectedVenueCategories()[0]||'';
    $('venue-help').textContent=t(custom?'venue.helpCustom':'venue.helpAuto');
  }
  $('venue-auto').addEventListener('click',()=>venueMode(false));
  $('venue-custom').addEventListener('click',()=>venueMode(true));
  $('venue-choices').addEventListener('change',e=>{
    if(selectedVenueCategories().length>3){e.target.checked=false;$('venue-help').textContent=t('venue.tooMany');}
    else $('venue-help').textContent=t('venue.helpCustom');
    state.venueDirty=true;$('seed-category').value=selectedVenueCategories()[0]||'';
  });
  $('library-radius').addEventListener('change',()=>{$('radius').value=$('library-radius').value;resetDraft();});
  const customExclusions=new Set();
  function renderExclusions(){
    const container=$('exclusion-tags');container.replaceChildren();
    for(const id of customExclusions){
      const b=node('button','text-button',excludeLabel(id)+' ×');b.type='button';b.setAttribute('aria-label',t('a11y.removeExclusion',{name:excludeLabel(id)}));
      b.addEventListener('click',()=>{customExclusions.delete(id);l.exclusionDirty=true;renderExclusions();$('exclusion-query').focus();});container.append(b);
    }
  }
  function addExclusions(){
    const value=$('exclusion-query').value.trim();if(!value)return true;
    const result=parseVenueExclusions(value,excludeCategories);
    for(const id of result.matched){
      const checkbox=document.querySelector('.library-exclusions input[type="checkbox"][value="'+id+'"]');
      if(checkbox)checkbox.checked=true;else customExclusions.add(id);
    }
    if(result.matched.length)l.exclusionDirty=true;
    renderExclusions();$('exclusion-query').value=result.unknown.join(t('sep'));
    $('exclusion-status').textContent=result.unknown.length?t('exclusion.notApplied',{list:result.unknown.join(t('sep')),supported:Object.keys(excludeCategories).map(excludeLabel).join(t('sep'))}):result.matched.length?t('exclusion.applied'):t('exclusion.enterCategory');
    return !result.unknown.length&&result.matched.length>0;
  }
  $('exclusion-add').addEventListener('click',()=>{if(!l.busy&&!state.busy)addExclusions();});
  $('exclusion-query').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();if(!e.isComposing&&!l.busy&&!state.busy)addExclusions();}});
  $('exclusion-query').addEventListener('input',()=>{$('exclusion-status').textContent='';});
  document.querySelector('.library-exclusions').addEventListener('change',e=>{if(e.target.type==='checkbox')l.exclusionDirty=true;});
  $('library-go').addEventListener('click',async()=>{
    if(state.busy||l.busy||!l.plan.items?.length)return;
    if(!addExclusions()){$('library-options').open=true;document.querySelector('.library-exclusions').open=true;$('exclusion-query').focus();return;}
    l.busy=true;render();
    try{
      if(state.inputMode==='natural'&&$('query').value.trim()&&!state.draft)renderIntent(await job('/api/parse',{query:$('query').value.trim(),city:state.city,area:area()}),false);
      const payload={city:state.city,area:area(),categories:selectedVenueCategories(),items:l.plan.items.map(x=>({id:x.id,choice:x.choice}))};
      if(state.draft)payload.draft_id=state.draft.draft_id;
      if(l.exclusionDirty)payload.exclude_categories=collectVenueExclusions(customExclusions,document.querySelectorAll('.library-exclusions input[type="checkbox"]:checked'));
      const d=await request('/api/taste/cards/confirm',payload);renderIntent(d,false);
      $('alternative-query').value=d.curiosity?.name||'';if(d.curiosity)$('alternative-type').value=d.curiosity.entity_type;
      const i=d.intent;
      if(i.clarifications.length||i.strict_city||i.novelty_requested||i.open_now||i.max_budget||i.available_minutes){$('manual-entry').open=true;$('confirmation').hidden=false;$('confirmation').scrollIntoView({behavior:'smooth',block:'start'});}
      else await launchParallel();
    }catch(e){message(errorMessage(e.code,t('library.goFailed')));}
    finally{l.busy=false;render();}
  });
  // Starts after the existing session initialization; empty local feeds may then call Qloo once.
  if(state.csrf)browse();else document.addEventListener('cityplay-ready',()=>browse(),{once:true});
  document.addEventListener('cityplay-library-updated',()=>browse());
  document.addEventListener('cityplay-keys-ready',()=>{
    if(l.query||l.cards.length||l.busy||state.busy)return;
    discoverMore({auto:true});
  });
  document.addEventListener('cityplay-lang-changed',()=>{renderVenueChoices();$('venue-help').textContent=t($('venue-custom').getAttribute('aria-pressed')==='true'?'venue.helpCustom':'venue.helpAuto');render();});
})();
