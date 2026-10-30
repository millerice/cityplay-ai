// setLang must translate an element's own text without destroying nested
// controls (label>select, button>span) — the cause of dead form controls.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const textNode=value=>({nodeType:3,nodeValue:value});
function element(tag,attrs={},children=[]){
  const el={nodeType:1,tagName:tag,children:[],_attrs:{...attrs},
    get firstChild(){return this.children[0]||null;},
    get childNodes(){return this.children;},
    setAttribute(k,v){this._attrs[k]=String(v);},getAttribute(k){return k in this._attrs?this._attrs[k]:null;},
    insertBefore(node,ref){const at=ref?this.children.indexOf(ref):0;this.children.splice(at<0?0:at,0,node);return node;},
    removeChild(node){const at=this.children.indexOf(node);if(at>=0)this.children.splice(at,1);return node;}};
  for(const child of children)el.children.push(child);
  return el;
}
const events=[];
const label=element('label',{'data-i18n':'library.city'},[textNode('City'),element('select',{id:'library-city'})]);
const button=element('button',{'data-i18n':'suggest.coffee'},[textNode('Like jazz — where for coffee? '),element('span',{},[textNode('↗')])]);
const bare=element('span',{'data-i18n':'topbar.checking'},[textNode(' \n ')]);
const document={documentElement:element('html'),
  querySelectorAll:selector=>selector==='[data-i18n]'?[label,button,bare]:[],
  getElementById:id=>id==='lang-toggle'?Object.assign(element('button',{id:'lang-toggle'}),{addEventListener(){}}):null,
  dispatchEvent:event=>events.push(event.type),createTextNode:textNode};
const ctx={document,localStorage:{getItem:()=>null,setItem(){}},Event:class{constructor(type){this.type=type;}}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/i18n.js','utf8'),ctx);
const I18N=vm.runInContext('I18N',ctx);
ctx.setLang('zh');
assert.equal(label.children[0].nodeValue,I18N.zh['library.city']);
assert.equal(label.children[1].tagName,'select'); // nested control survives
assert.equal(button.children[1].children[0].nodeValue,'↗'); // arrow span survives
assert.equal(button.children[0].nodeValue,I18N.zh['suggest.coffee']);
assert.ok(bare.children.some(n=>n.nodeType===3&&n.nodeValue===I18N.zh['topbar.checking'])); // empty-text element gains the translation
assert.ok(events.includes('cityplay-lang-changed'));
ctx.setLang('en');
assert.equal(label.children[0].nodeValue,I18N.en['library.city']);
assert.equal(label.children.length,2); // still exactly text + select after a round trip
assert.equal(bare.children.filter(n=>n.nodeType===3&&n.nodeValue.trim()).length,1); // no duplicate text runs
// Parallel version copy must use variant keys — never leak server Chinese fallbacks in EN.
assert.equal(ctx.versionText({id:'familiar',variant:'familiar',title:'熟悉的我'},'title','熟悉的我'),I18N.en['v.familiar.title']);
assert.equal(ctx.versionText({id:'adjacent',variant:'adjacent_bridge',title:'邻近的我'},'title','邻近的我'),I18N.en['v.adjacent_bridge.title']);
assert.equal(ctx.versionText({id:'alternative',variant:'alternative',title:'另一种我'},'title','另一种我'),I18N.en['v.alternative.title']);
ctx.setLang('zh');
assert.equal(ctx.versionText({variant:'familiar',title:'Familiar me'},'title','Familiar me'),I18N.zh['v.familiar.title']);
console.log('i18n DOM: nested controls survive language switches, text runs replaced in place passed');
