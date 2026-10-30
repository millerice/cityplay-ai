const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8'),context={};vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function defaultTastePlan('),source.indexOf('function renderTastePlan(')),context);
const items=[...Array.from({length:7},(_,i)=>({id:'like'+i,choice:'like'})),...Array.from({length:5},(_,i)=>({id:'curious'+i,choice:'curious'}))];
const original=JSON.stringify(items),plan=context.defaultTastePlan(items);
assert.equal(plan.map(x=>x.id).join(','),'like4,like5,like6,curious4');assert.equal(JSON.stringify(items),original);
assert.equal(context.defaultTastePlan(items.filter(x=>x.choice==='curious')).map(x=>x.id).join(','),'curious4');
assert.equal(context.defaultTastePlan([]).length,0);assert.equal(context.defaultTastePlan([items[0]]).length,1);
console.log('Taste planning: larger library preserved, recent explicit choices selected, curiosity stays distinct, one seed sufficient');
