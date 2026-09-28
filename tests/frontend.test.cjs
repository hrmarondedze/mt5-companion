const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function setup() {
  const elements = {}, pending = [];
  const element = id => elements[id] ||= {value:id === 'tf' ? 'M5' : '',textContent:'',innerHTML:'',style:{},disabled:false};
  const context = vm.createContext({document:{getElementById:element,querySelector:()=>null,querySelectorAll:()=>[]},Date,AbortSignal,setInterval:()=>{},fetch:(url,options)=>new Promise(resolve=>pending.push({url,options,resolve}))});
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8'),context);
  return {elements,pending,run:code=>vm.runInContext(code,context)};
}
const settle = () => new Promise(resolve=>setImmediate(resolve));
const data = symbol => ({symbol,timeframe:'M5',candles:[{time:Date.now()/1000,open:100,high:110,low:90,close:105}]});
function respond(req,body,ok=true) {req.resolve({ok,json:async()=>body});}
test('old chart response cannot overwrite a new selection', async()=>{
  const s=setup();
  const old=s.pending.find(p=>p.url.includes('candles'));
  s.run("selected='BTCUSD'; changeContext()");
  const latest=s.pending.at(-1);
  respond(latest,data('BTCUSD')); await settle();
  respond(old,data('XAUUSD')); await settle();
  assert.match(s.elements.chartInfo.textContent,/BTCUSD/);
  assert.match(s.elements.chart.innerHTML,/<rect/);
});
test('obsolete chart error cannot clear the current chart', async()=>{
  const s=setup(),old=s.pending.find(p=>p.url.includes('candles'));
  s.run("selected='BTCUSD'; changeContext()");
  respond(s.pending.at(-1),data('BTCUSD')); await settle();
  respond(old,{detail:'Missing history'},false); await settle();
  assert.match(s.elements.chartInfo.textContent,/BTCUSD/);
  assert.ok(s.elements.chart.innerHTML);
});
test('context changes clear old chart and analysis immediately',()=>{
  const s=setup(); s.elements.chart.innerHTML='old chart'; s.run("$('analysis').textContent='old analysis'");
  s.run("selected='BTCUSD'; changeContext()");
  assert.equal(s.elements.chart.innerHTML,'');
  assert.doesNotMatch(s.elements.analysis.textContent,/old analysis/);
  assert.equal(s.elements.analyze.disabled,true);
});
test('stale quotes disable analysis and expose status',()=>{
  const s=setup();
  s.run("marketOk=true; marketReceived=Date.now(); quotes={XAUUSD:{age_seconds:121}}; updateStatus()");
  assert.equal(s.elements.analyze.disabled,true);
  assert.match(s.elements.status.textContent,/0\/4 quotes current/);
});
test('late analysis response is discarded after selection changes',async()=>{
  const s=setup();
  const analysis=s.elements.analyze.onclick();
  const req=s.pending.at(-1);
  s.run("selected='BTCUSD'; changeContext()");
  respond(req,{symbol:'XAUUSD',timeframe:'M5',quote_time:new Date().toISOString(),analysis:'obsolete'});
  await analysis;
  assert.doesNotMatch(s.elements.analysis.textContent,/obsolete/);
});
