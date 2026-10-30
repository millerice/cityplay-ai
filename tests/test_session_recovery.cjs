// A restarted server drops in-memory sessions; POSTs must transparently re-bootstrap once.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
function makeContext(acceptFresh,modelConfig){
  const calls=[];let sessions=0;
  const ctx={state:{csrf:'stale-token',presets:{},qlooReady:null,modelReady:null},modelConfig:modelConfig||{key:'',name:'deepseek-v4-pro'},
    $:()=>({textContent:'',classList:{toggle(){}},setAttribute(){},focus(){}}),
    fetch:async(path,init)=>{
      calls.push({path,method:init&&init.method?init.method:'GET',token:init&&init.headers?init.headers['X-CSRF-Token']:undefined,modelKey:init&&init.headers?init.headers['X-Model-Key']:undefined});
      if(!(init&&init.method==='POST')){sessions++;return {status:200,ok:true,json:async()=>({csrf:'fresh-'+sessions,presets:{new_york:{label:'x'}},configured:{qloo:true,model:true}})};}
      if(acceptFresh&&/^fresh-/.test(init.headers['X-CSRF-Token']||''))return {status:200,ok:true,json:async()=>({ok:true,job_id:'j1'})};
      return {status:403,ok:false,json:async()=>({error:{code:'INVALID_SESSION_OR_CSRF',retryable:false}})};
    }};
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync('web/i18n.js','utf8'),ctx);
  vm.runInContext(source.slice(source.indexOf('async function refreshSession('),source.indexOf('async function job(')),ctx);
  return {ctx,calls};
}
(async()=>{
  const good=makeContext(true);
  const result=await good.ctx.request('/api/taste/prepare',{city:'new_york'});
  assert.deepEqual(result,{ok:true,job_id:'j1'});
  assert.equal(good.ctx.state.csrf,'fresh-1');assert.equal(good.ctx.state.qlooReady,true);
  assert.deepEqual(good.calls.map(c=>c.method),['POST','GET','POST']); // rejected POST, session bootstrap, replayed POST
  assert.equal(good.calls[0].token,'stale-token');assert.equal(good.calls[2].token,'fresh-1');
  // A browser-supplied model key rides along on POSTs and never on GETs.
  const withKey=makeContext(true,{key:'sk-browser-synthetic-key',name:'deepseek-v4-flash'});
  await withKey.ctx.request('/api/parse',{query:'x'});
  assert.equal(withKey.calls[0].modelKey,'sk-browser-synthetic-key');
  await withKey.ctx.request('/api/session');
  assert.equal(withKey.calls[1].modelKey,undefined);
  assert.equal(good.calls.every(c=>c.modelKey===undefined),true); // no key configured → no header
  // Recovery happens at most once: a still-rejected replay surfaces the error instead of looping.
  const bad=makeContext(false);
  await assert.rejects(bad.ctx.request('/api/parallel',{city:'new_york'}),{code:'INVALID_SESSION_OR_CSRF'});
  assert.equal(bad.calls.length,3);
  // GET requests never replay (there is nothing to authenticate).
  const getOnly=makeContext(false);
  getOnly.ctx.state.csrf=null;
  const session=await getOnly.ctx.request('/api/session');
  assert.equal(session.csrf,'fresh-1');assert.equal(getOnly.calls.length,1);
  console.log('Session recovery: transparent CSRF re-bootstrap, single retry, GET untouched passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
