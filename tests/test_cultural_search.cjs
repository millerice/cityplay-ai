const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/library.js','utf8');
const i18n=fs.readFileSync('web/i18n.js','utf8');
const dict={};vm.createContext(dict);vm.runInContext(i18n,dict);
function setup({query='alias',local=[{id:'local',name:'Cached object'}],online={cards:[{id:'other',name:'Canonical translated name'}]},failure=null,localFailure=null}={}){
  const calls=[],messages=[],views=[];
  const l={domain:'music',query:'',offset:0,choices:[{id:'saved',choice:'like'}],busy:false,searchResults:null};
  const ctx={l,state:{csrf:'synthetic',busy:false},$:()=>({value:query}),
    render(){},message:x=>messages.push(x),browse:async()=>calls.push('browse'),
    searchPage(){l.cards=l.searchResults.slice(0,6);l.total=l.searchResults.length;views.push(l.cards.map(x=>x.id));},
    request:async(path,payload)=>{calls.push({path,payload});if(localFailure)throw localFailure;return {cards:local,choices:l.choices};},
    job:async(path,payload)=>{calls.push({path,payload});if(failure)throw failure;return typeof online==='function'?await online():online;}};
  vm.createContext(ctx);
  vm.runInContext(i18n,ctx);
  vm.runInContext(source.slice(source.indexOf('function mergeCulturalResults'),source.indexOf('(() =>')),ctx);
  vm.runInContext(source.slice(source.indexOf('  async function searchOnline'),source.indexOf("  $('library-search').addEventListener")),ctx);
  return {ctx,l,calls,messages,views};
}
(async()=>{
  let release;const s=setup({online:()=>new Promise(resolve=>release=resolve)});
  const pending=s.ctx.searchOnline();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(s.l.busy,true);assert.equal(s.l.cards[0].display_source,dict.t('library.srcLocal'));
  await s.ctx.searchOnline();assert.equal(s.calls.length,2); // In-flight double click is ignored.
  release({cards:[{id:'local',name:'Updated canonical'},{id:'other',name:'No literal keyword match'}]});await pending;
  assert.equal(s.l.cards.length,2);assert.equal(s.l.cards[0].name,'Updated canonical');assert.equal(s.l.cards[1].display_source,dict.t('library.srcOnline'));
  assert.equal(s.calls[1].payload.query,'alias');assert.equal(s.calls[1].payload.domain,'music');assert.equal(s.l.busy,false);
  const failed=setup({failure:{code:'NETWORK_TIMEOUT_OR_UNAVAILABLE'}});await failed.ctx.searchOnline();
  assert.equal(failed.l.cards[0].id,'local');assert.ok(failed.messages.at(-1).includes(dict.t('library.keptLocal',{count:1})));assert.equal(failed.l.choices[0].id,'saved');
  const partial=setup({online:{cards:[],partial:true}});await partial.ctx.searchOnline();assert.ok(partial.messages.at(-1).includes(dict.t('library.searchPartial',{count:partial.l.total})));
  const empty=setup({query:'  '});await empty.ctx.searchOnline();assert.equal(empty.calls.join(','),'browse');
  const cacheFailure=setup({localFailure:{code:'CACHE_UNAVAILABLE'}});await cacheFailure.ctx.searchOnline();assert.equal(cacheFailure.l.cards[0].id,'other');
  const sensitive=setup({localFailure:{code:'SENSITIVE_INPUT_REJECTED'}});await sensitive.ctx.searchOnline();assert.equal(sensitive.calls.length,1);
  console.log('Cultural search: local first, online merge, source labels, duplicate clicks, partial/failure fallback, canonical names and empty search passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
