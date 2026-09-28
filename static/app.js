const names = ['XAUUSD', 'BTCUSD', 'GBPUSD', 'EURUSD'];
const $ = id => document.getElementById(id);
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let selected = 'XAUUSD', quotes = {}, marketBusy = false, chartVersion = 0, contextVersion = 0;
let marketOk = false, marketReceived = 0, chartReady = false, analysisBusy = false, chartData = null;
const periods = {M1:60, M5:300, M15:900, H1:3600, H4:14400};
const price = value => Number(value).toLocaleString(undefined, {maximumFractionDigits:5});
const age = q => Math.max(0, q.age_seconds + (Date.now() - marketReceived) / 1000);
async function get(url, options) {
  const response = await fetch(url, {...options, signal:AbortSignal.timeout(options ? 120000 : 15000)});
  const body = await response.json();
  if (!response.ok) throw Error(body.detail || 'Request failed');
  return body;
}
function chartFresh() {
  return chartData && Date.now()/1000 - chartData.candles.at(-1).time <= periods[chartData.timeframe] + 120;
}
function updateStatus() {
  const good = names.filter(n => quotes[n] && !quotes[n].error && age(quotes[n]) <= 120);
  $('status').textContent = !marketOk ? 'MT5 unavailable · data unverified' : good.length === names.length ? 'MT5 · all quotes current' : `MT5 · ${good.length}/4 quotes current`;
  $('status').style.color = marketOk && good.length === names.length ? '#a8ded0' : '#ffd28b';
  names.forEach(n => {
    const q = quotes[n], el = document.querySelector(`[data-age="${n}"]`);
    if (el && q && !q.error) {
      el.textContent = `${!marketOk ? 'UNVERIFIED · ' : age(q) > 120 ? 'STALE · ' : ''}${Math.floor(age(q))}s since last tick · ${q.symbol}`;
      el.style.color = !marketOk || age(q) > 120 ? '#ffd28b' : '';
    }
  });
  const q = quotes[selected];
  $('analyze').disabled = analysisBusy || !marketOk || !q || q.error || age(q) > 120 || !chartReady || !chartFresh();
  if (chartReady && !chartFresh()) $('chartInfo').textContent = 'STALE candle history · analysis paused. Refresh history in MT5.';
}
async function refresh() {
  if (marketBusy) return;
  marketBusy = true;
  try {
    const data = await get('/api/market');
    quotes = Object.fromEntries(data.symbols.map(q => [q.base, q]));
    marketReceived = Date.now(); marketOk = true;
    $('cards').innerHTML = names.map(n => {
      const q = quotes[n] || {error:'No quote returned'};
      return `<button class="card ${selected === n ? 'active' : ''}" data-symbol="${n}" aria-pressed="${selected === n}"><strong>${n}</strong><div class="price">${q.error ? '—' : price(q.bid)}</div><div class="meta">${q.error ? esc(q.error) : `Ask ${price(q.ask)} · Spread ${Number(q.spread).toPrecision(3)}`}</div><div class="meta" data-age="${n}"></div></button>`;
    }).join('');
    document.querySelectorAll('.card').forEach(button => button.onclick = () => {
      if (selected === button.dataset.symbol) return;
      selected = button.dataset.symbol;
      document.querySelectorAll('.card').forEach(b => {b.classList.toggle('active', b === button); b.setAttribute('aria-pressed', String(b === button));});
      changeContext();
    });
  } catch (error) {
    marketOk = false;
    if (!Object.keys(quotes).length) $('cards').innerHTML = `<p>${esc(error.message)}</p>`;
  } finally {marketBusy = false; updateStatus();}
}
function changeContext() {
  contextVersion++;
  $('analysis').textContent = 'Select Analyze to review this symbol and timeframe.';
  loadChart(true);
}
function drawChart(data) {
  const candles = data.candles, low = Math.min(...candles.map(c => c.low)), high = Math.max(...candles.map(c => c.high));
  const pad = (high - low || 1) * .06, min = low - pad, max = high + pad;
  const y = v => 245 - (v - min) / (max - min) * 225;
  const step = 580 / candles.length, x = i => 12 + step * (i + .5);
  let svg = '';
  for (let i = 0; i <= 4; i++) {
    const value = min + (max - min) * i / 4, py = y(value);
    svg += `<line x1="10" x2="598" y1="${py}" y2="${py}" stroke="#29404b"/><text x="604" y="${py+4}" fill="#99aaa9" font-size="11">${price(value)}</text>`;
  }
  candles.forEach((c, i) => {
    const color = c.close >= c.open ? '#75e6c9' : '#ff929d';
    svg += `<g><title>${esc(new Date(c.time*1000).toLocaleString())} | O ${c.open} H ${c.high} L ${c.low} C ${c.close}${i === candles.length-1 ? ' | Forming' : ''}</title><line x1="${x(i)}" x2="${x(i)}" y1="${y(c.high)}" y2="${y(c.low)}" stroke="${color}"/><rect x="${x(i)-step*.32}" y="${Math.min(y(c.open),y(c.close))}" width="${step*.64}" height="${Math.max(1,Math.abs(y(c.open)-y(c.close)))}" fill="${color}"/></g>`;
  });
  [0, Math.floor((candles.length-1)/2), candles.length-1].forEach((i, j) => {
    svg += `<text x="${x(i)}" y="270" text-anchor="${j === 0 ? 'start' : j === 2 ? 'end' : 'middle'}" fill="#99aaa9" font-size="11">${esc(new Date(candles[i].time*1000).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}))}</text>`;
  });
  $('chart').innerHTML = svg;
  $('chartInfo').textContent = `${data.symbol} · ${candles.length} candles · latest ${new Date(candles.at(-1).time*1000).toLocaleString()} · last candle forming. Hover for OHLC.`;
}
async function loadChart(clear = false) {
  const version = ++chartVersion, name = selected, tf = $('tf').value;
  chartReady = false;
  if (clear) {chartData = null; $('chart').innerHTML = '';}
  $('chartTitle').textContent = `${name} · ${tf}`;
  $('chartInfo').textContent = 'Refreshing candles · checking freshness…';
  updateStatus();
  try {
    const data = await get(`/api/candles/${name}?timeframe=${tf}`);
    if (version !== chartVersion) return;
    chartData = data; chartReady = true; drawChart(data);
  } catch(error) {
    if (version !== chartVersion) return;
    chartData = null; $('chart').innerHTML = ''; $('chartInfo').textContent = error.message;
  } finally {if (version === chartVersion) updateStatus();}
}
$('tf').onchange = changeContext;
$('analyze').onclick = async () => {
  const version = contextVersion, symbol = selected, timeframe = $('tf').value;
  analysisBusy = true; updateStatus(); $('analysis').textContent = 'Reviewing current broker data…';
  try {
    const data = await get('/api/analyze', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({symbol,timeframe,question:$('question').value})});
    if (version !== contextVersion) return;
    $('analysis').textContent = `${data.symbol} · ${data.timeframe || timeframe} · snapshot ${new Date(data.quote_time).toLocaleString()} (does not update live)\n\n${data.analysis}`;
  } catch(error) {if (version === contextVersion) $('analysis').textContent = error.message;}
  finally {analysisBusy = false; updateStatus();}
};
refresh(); loadChart(true);
setInterval(refresh, 5000); setInterval(() => loadChart(), 30000); setInterval(updateStatus, 1000);
