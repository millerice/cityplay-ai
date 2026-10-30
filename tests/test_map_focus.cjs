// Synthetic coordinates; no API credentials, network or Qloo fixtures.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const frames=new Map(),events=[];let frameId=0,zoom,view=null;
const container={clientWidth:500,clientHeight:400};
const map={getZoom:()=>zoom,getContainer:()=>container,stop:()=>events.push('stop'),invalidateSize:opts=>{assert.equal(opts.pan,false);events.push('size');},fitBounds:(points,opts)=>{zoom=15;view='overview';events.push('fit');assert.equal(opts.animate,false);},setView:(point,z,opts)=>{view=point;zoom=z;events.push('focus');assert.equal(opts.animate,false);}};
const created=[];const element=()=>{const el={append(){},addEventListener(){},scrollIntoView(){},hidden:false};created.push(el);return el;};
const elements={'map-panel':element(),'map-status':element()};
const context={window:{L:true},document:{getElementById:id=>elements[id],createElement:element},requestAnimationFrame:fn=>{frames.set(++frameId,fn);return frameId;},cancelAnimationFrame:id=>frames.delete(id),L:{map:()=>map,tileLayer:()=>({addTo:()=>({on(){}})}),layerGroup:()=>({addTo(){return this},clearLayers(){}}),divIcon:x=>x,latLngBounds:x=>x,marker:point=>({addTo(){return this},bindPopup(){},getLatLng:()=>point,openPopup:()=>events.push('popup '+point[0])})}};
vm.createContext(context);vm.runInContext(fs.readFileSync('web/i18n.js','utf8'),context);vm.runInContext(fs.readFileSync('web/map.js','utf8')+'\nglobalThis.subject=CityPlayMap;',context);
const subject=context.subject,flush=()=>{const batch=[...frames.values()];frames.clear();batch.forEach(fn=>fn());};
const cards=[{name:'Synthetic A',address:'TEST',description:'Actual synthetic intro <b>literal text</b>',location:{lat:1,lon:2}},{name:'Synthetic B',address:'TEST',location:{lat:3,lon:4}}];
subject.render(cards);flush();assert.equal(view,'overview');
assert.ok(created.some(el=>el.textContent==='Actual synthetic intro <b>literal text</b>'));
assert.equal(created.some(el=>String(el.textContent).includes('纬度')),false);
function click(index){subject.resize();subject.focus(index);flush();assert.deepEqual(Array.from(view),index?[3,4]:[1,2]);assert.equal(zoom,16);}
click(0);events.length=0;click(1);assert.equal(events.includes('fit'),false);click(0);click(1);
subject.resize();flush();assert.deepEqual(Array.from(view),[3,4]);assert.equal(zoom,16);
// Even clicks queued in the same frame must leave the newest target selected.
subject.resize();subject.focus(0);subject.resize();subject.focus(1);flush();assert.deepEqual(Array.from(view),[3,4]);
// An initially hidden mobile map fits the new results once it becomes visible.
container.clientWidth=0;subject.render(cards);events.length=0;flush();assert.equal(events.includes('fit'),false);
container.clientWidth=390;subject.resize();flush();assert.equal(view,'overview');click(1);
// Replacing/clearing results must cancel a pending focus of an old marker.
subject.focus(0);subject.render([]);events.length=0;flush();assert.equal(events.some(x=>x.startsWith('popup')),false);
console.log('Map focus: consecutive targets, repeated resize, rapid clicks, hidden layout and cleared results passed');
