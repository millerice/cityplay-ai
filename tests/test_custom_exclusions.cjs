const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/library.js','utf8');
const app=fs.readFileSync('web/app.js','utf8');
const ctx={};vm.createContext(ctx);
vm.runInContext(app.slice(app.indexOf('const categories ='),app.indexOf('function selectedVenueCategories')),ctx);
vm.runInContext(app.slice(app.indexOf('const excludeCategories ='),app.indexOf('const entityTypes =')),ctx);
vm.runInContext(source.slice(source.indexOf('function collectVenueExclusions'),source.indexOf('(() =>')),ctx);
function parse(value){return JSON.parse(vm.runInContext('JSON.stringify(parseVenueExclusions('+JSON.stringify(value)+',excludeCategories))',ctx));}
assert.deepEqual(parse('不要咖啡馆和博物馆'),{matched:['coffee','museum'],unknown:[]});
assert.deepEqual(parse('酒店、购物中心，咖啡店、咖啡馆'),{matched:['hotel','mall','coffee'],unknown:[]});
assert.deepEqual(parse('avoid hotel, no museum'),{matched:['hotel','museum'],unknown:[]});
assert.deepEqual(parse('不吵、不排队、酒吧'),{matched:[],unknown:['不吵','不排队','酒吧']});
assert.deepEqual(parse('不要咖啡馆和拥挤'),{matched:['coffee'],unknown:['拥挤']});
assert.deepEqual(parse('不要博物馆，但公园可以'),{matched:['museum'],unknown:['但公园可以']});
console.log('Custom venue exclusions: aliases, deduplication, unsupported requests, and mixed clauses passed');

assert.equal(vm.runInContext("JSON.stringify(collectVenueExclusions(new Set(['coffee','museum']),[{value:'hotel'},{value:'coffee'}]))",ctx),'["coffee","museum","hotel"]');
