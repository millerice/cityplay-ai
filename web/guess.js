"use strict";
(() => {
  const dialog=$('guess-dialog'),content=$('guess-content'),actions=$('guess-actions');
  const g={domain:'all',page:0,cards:[],selected:new Map(),busy:false,step:'start',existing:[],existingChoices:new Map(),cache:new Map(),plan:{}};
  const normalize=x=>x.normalize('NFKC').toLowerCase().replace(/[\s·•・《》「》“”"'’]/gu,'');
  function error(value=''){$('guess-error').textContent=value;}
  function action(label,callback,primary=false){const b=node('button',primary?'primary-button':'secondary-button',label);b.type='button';b.disabled=g.busy;b.addEventListener('click',callback);actions.append(b);return b;}
  function initial(){
    g.step='start';error();content.replaceChildren(node('h3','',t('guess.startTitle')),node('p','field-help',t('guess.startHelp')));
    const domains=node('div','guess-options');
    for(const [key,label] of [['music','domain.music'],['movie','domain.movie'],['book','domain.book'],['all','guess.domain.any']]){const b=node('button','guess-option',t(label));b.type='button';b.addEventListener('click',()=>{g.domain=key;g.page=0;load();});domains.append(b);}
    content.append(domains);actions.replaceChildren();action(t('guess.exitFill'),()=>dialog.close());
  }
  function showCards(){
    const focusKey=g.focusKey||document.activeElement?.dataset?.focusKey;
    g.step='cards';content.replaceChildren();actions.replaceChildren();
    const toolbar=node('div','card-domains');
    for(const [key,label] of [['all','domain.all'],['music','domain.music'],['movie','domain.movie'],['book','domain.book']]){const b=node('button','text-button',t(label));b.type='button';b.disabled=g.busy;b.setAttribute('aria-pressed',String(g.domain===key));b.addEventListener('click',()=>{g.domain=key;g.page=0;load();});toolbar.append(b);}
    content.append(toolbar,node('p','field-help',t('guess.cardsHelp')));
    const search=node('form','culture-search');const input=node('input');input.id='culture-search';input.maxLength=100;input.value=g.query||'';input.placeholder=t('guess.searchPlaceholder');input.setAttribute('aria-label',t('library.searchAria'));
    const button=node('button','secondary-button',t('guess.search'));button.type='submit';button.disabled=g.busy;search.append(input,button);search.addEventListener('submit',e=>{e.preventDefault();if(input.value.trim())load(input.value.trim());});content.append(search);
    const grid=node('div','culture-grid'),related=node('div','culture-grid');let otherCount=0;
    for(const card of g.cards){
      const article=node('article','culture-card');article.dataset.selected=g.selected.get(card.id)?.choice||'';
      article.append(node('small','field-help',typeLabel(card.entity_type)+(card.year?' · '+card.year:'')),node('h3','',card.name));if(card.detail&&normalize(card.detail)!==normalize(card.name)&&card.detail!==String(card.year||''))article.append(node('p','field-help',card.detail));
      const buttons=node('div','culture-choices');
      for(const [choice,key] of [['like','plan.like'],['curious','plan.curious'],['skip','guess.skip']]){
        const b=node('button','text-button',t(key));b.type='button';b.dataset.focusKey=card.id+':'+choice;b.disabled=g.busy;b.setAttribute('aria-pressed',String(g.selected.get(card.id)?.choice===choice));
        b.addEventListener('click',async()=>{
          if(g.busy||state.busy)return;
          g.focusKey=card.id+':'+choice;error();const current=g.selected.get(card.id);
          if(choice==='skip'){g.cards=g.cards.filter(x=>x.id!==card.id);showCards();return;}
          g.busy=true;showCards();
          try{const result=await request('/api/library/choice',{id:card.id,choice:current?.choice===choice?'clear':choice});g.selected=new Map(result.choices.map(x=>[x.id,x]));document.dispatchEvent(new Event('cityplay-library-updated'));}
          catch(e){error(errorMessage(e.code,t('library.saveFailed')));}
          finally{g.busy=false;showCards();}
        });buttons.append(b);
      }
      article.append(buttons);if(g.query&&!culturalMatch(card,g.query)){related.append(article);otherCount++;}else grid.append(article);
    }
    if(g.query&&!g.cards.some(x=>culturalMatch(x,g.query)))content.append(node('p','field-help',t('guess.noExact')));
    content.append(grid);
    if(otherCount){const others=node('details','other-cultural-results');others.append(node('summary','',t('library.others',{count:otherCount})),related);content.append(others);}

    if(!g.cards.length)content.append(node('p','field-help',t('guess.noCards')));
    if(g.selected.size){const chosen=node('details','chosen-tastes saved-tastes');chosen.append(node('summary','',t('library.myLibrarySimple',{count:g.selected.size})));
      for(const [id,item] of g.selected){const b=node('button','text-button',`${t(item.choice==='like'?'plan.like':'plan.curious')}: ${item.name} ×`);b.type='button';b.disabled=g.busy;b.addEventListener('click',async()=>{if(g.busy)return;g.busy=true;try{const r=await request('/api/library/choice',{id,choice:'clear'});g.selected=new Map(r.choices.map(x=>[x.id,x]));document.dispatchEvent(new Event('cityplay-library-updated'));}catch(e){error(errorMessage(e.code,t('library.removedFailed')));}finally{g.busy=false;showCards();}});chosen.append(b);}content.append(chosen);}
    action(t('library.nextSet'),()=>{g.page=1-g.page;load();});
    const next=action(t('guess.review'),preview,true);next.disabled=!g.selected.size||g.busy;
    if(!g.busy){restoreCulturalFocus(content,focusKey);g.focusKey=null;}
  }
  async function load(query=''){
    if(g.busy)return;g.query=query;g.busy=true;error();content.replaceChildren(node('p','guess-loading',t('guess.loading')));actions.replaceChildren();
    try{
      const payload={domain:g.domain,page:g.page,query,existing:g.existing};
      const key=JSON.stringify(payload),cached=g.cache.get(key);
      let result;
      if(cached&&Date.now()-cached.at<300000)result=cached.result;
      else{
        const local=!g.existing.length?await request('/api/library/browse',{domain:g.domain,query,offset:g.page*6}):null;
        result=local?.cards.length?local:await job('/api/taste/cards',payload);
        if(!g.hydrated){g.hydrated=true;if(!g.selected.size)for(const item of (local?.choices||[]))g.selected.set(item.id,item);}
      }
      g.cache.set(key,{at:Date.now(),result});g.cards=result.cards;
      for(const existing of g.existing){const matches=g.cards.filter(x=>x.entity_type===existing.entity_type&&normalize(x.name)===normalize(existing.query));const choice=g.existingChoices.get(existing.entity_type+':'+normalize(existing.query));if(choice&&matches.length===1&&!matches[0].ambiguous&&!g.selected.has(matches[0].id))g.selected.set(matches[0].id,{...matches[0],choice});}
      g.existing=[];g.busy=false;showCards();
      if(result.partial)error(t('guess.partial'));
    }catch(e){g.busy=false;showCards();error(errorMessage(e.code,t('guess.loadFailed')));}
  }
  function preview(){
    g.step='preview';error();content.replaceChildren(node('h3','',t('guess.previewTitle')),node('p','field-help',t('guess.previewHelp',{count:g.selected.size})));actions.replaceChildren();
    const run=node('section','run-taste-plan');content.append(run);
    renderTastePlan(run,[...g.selected.values()],g.plan,()=>{const next=actions.querySelector('.primary-button');if(next)next.disabled=!g.plan.items.length;});
    const venues=(state.venueDirty?selectedVenueCategories():state.draft?.intent.categories||selectedVenueCategories()).map(categoryLabel).join(t('sep'))||t('guess.previewMix');
    content.append(node('p','field-help',t('guess.previewRange',{city:cityLabel(state.city),venues,km:area().radius_m/1000})),node('p','field-help',t('guess.previewCurious')));
    action(t('guess.back'),showCards);const next=action(t('guess.apply'),apply,true);next.disabled=!g.plan.items?.length;
  }
  async function apply(){
    if(g.busy||state.busy||!g.plan.items?.length)return;g.busy=true;error();actions.querySelectorAll('button').forEach(b=>b.disabled=true);
    try{
      // Preserve unparsed natural-language constraints by parsing once, never rewriting the prose.
      if(state.inputMode==='natural'&&$('query').value.trim()&&!state.draft){
        renderIntent(await job('/api/parse',{query:$('query').value.trim(),city:state.city,area:area()}),false);
      }
      const payload={city:state.city,area:area(),categories:state.venueDirty?selectedVenueCategories():state.draft?.intent.categories||selectedVenueCategories(),items:g.plan.items.map(item=>({id:item.id,choice:item.choice}))};
      if(state.draft)payload.draft_id=state.draft.draft_id;
      const draft=await request('/api/taste/cards/confirm',payload);
      renderIntent(draft,false);$('alternative-query').value=draft.curiosity?.name||'';if(draft.curiosity)$('alternative-type').value=draft.curiosity.entity_type;
      dialog.close();g.busy=false;
      const i=draft.intent;
      if(i.clarifications.length||i.strict_city||i.novelty_requested||i.open_now||i.max_budget||i.available_minutes){$('confirmation').hidden=false;$('confirmation').scrollIntoView({behavior:'smooth',block:'start'});}
      else await launchParallel();
      document.dispatchEvent(new Event('cityplay-library-updated'));
    }catch(e){error(errorMessage(e.code,t('guess.applyFailed')));}
    finally{g.busy=false;actions.querySelectorAll('button').forEach(b=>b.disabled=false);}
  }
  $('guess-open').addEventListener('click',async()=>{
    if(state.busy||g.busy||!state.csrf)return;
    dialog.showModal();g.busy=true;
    try{const local=await request('/api/library/browse',{domain:g.domain,query:'',offset:0});g.selected=new Map(local.choices.map(x=>[x.id,x]));g.hydrated=true;}
    catch(e){error(errorMessage(e.code,t('guess.restoreFailed')));g.busy=false;return;}
    g.busy=false;
    if(g.step!=='start'){g.step==='preview'?preview():showCards();return;}
    g.existing=['artist','movie','book'].map(entity_type=>({query:$('seed-'+entity_type).value.trim(),entity_type})).filter(x=>x.query);
    g.existingChoices=new Map(g.existing.map(x=>[x.entity_type+':'+normalize(x.query),'like']));
    const prior=state.explorationBase?.interests||state.draft?.intent.interests||[];
    for(const x of prior)if(x.kind==='entity'&&typeLabel(x.entity_type)!==x.entity_type&&!g.existing.some(v=>normalize(v.query)===normalize(x.query))&&g.existing.length<3)g.existing.push({query:x.query,entity_type:x.entity_type});
    if(g.existing.length)load();else initial();
  });
  $('guess-close').addEventListener('click',()=>dialog.close());
  document.addEventListener('cityplay-lang-changed',()=>{if(dialog.open&&!g.busy){g.step==='preview'?preview():g.step==='cards'?showCards():initial();}});
})();
