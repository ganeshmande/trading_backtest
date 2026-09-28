const $=id=>document.getElementById(id);
let interval='5m', refresh=5000, busy=false, timer;
let latestStocks=[];
const esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
const money=x=>Number.isFinite(Number(x))?'₹'+Number(x).toFixed(2):'—';
function membership(x){if(x==='INDEX')return '<b class="idx">INDEX</b>';if(x==='N50 & N100')return '<b class="n50">N50 & N100</b>';if(x==='N100')return '<b class="n100">N100</b>';return '<b class="other">OTHER</b>';}
function candles(cs, compact=false){
  if(!Array.isArray(cs)||!cs.length)return '<span class="muted">No closed candle data</span>';
  const clean=cs.map((c,i)=>{
    const o=Number(c.open), cl=Number(c.close), hi=Number(c.high), lo=Number(c.low);
    if(![o,cl,hi,lo].every(Number.isFinite)) return null;
    // Validate the OHLC geometry before drawing: wick must cover the full OHLC range.
    const high=Math.max(hi,o,cl), low=Math.min(lo,o,cl);
    return {...c,open:o,close:cl,high,low,index:i+1};
  }).filter(Boolean);
  if(!clean.length)return '<span class="muted">Invalid OHLC data</span>';
  const max=Math.max(...clean.map(c=>c.high)), min=Math.min(...clean.map(c=>c.low));
  const pad=Math.max((max-min)*0.08, Math.abs(max)*0.00025, 0.01);
  const topValue=max+pad, bottomValue=min-pad, valueRange=Math.max(topValue-bottomValue,1e-9);
  const width=compact?Math.max(250,clean.length*34+20):Math.max(320,clean.length*42+24), height=compact?92:118;
  const top=8,bottom=18,plot=height-top-bottom;
  const y=v=>top+((topValue-v)/valueRange)*plot;
  const step=(width-24)/Math.max(clean.length,1), bodyW=Math.min(14,Math.max(8,step*.42));
  const grid=[0.25,0.5,0.75].map(q=>{const gy=top+plot*q;return `<line class="chart-grid" x1="4" x2="${width-4}" y1="${gy.toFixed(2)}" y2="${gy.toFixed(2)}"/>`;}).join('');
  const marks=clean.map((c,i)=>{
    const x=12+step*i+step/2, yo=y(c.open), yc=y(c.close), yh=y(c.high), yl=y(c.low);
    const bodyTop=Math.min(yo,yc), bodyH=Math.max(Math.abs(yo-yc), c.type==='DOJI'?2.4:1.8);
    const cls=String(c.type||'').toLowerCase();
    const time=fmtTime(c.time||c.time_display||c.timestamp);
    return `<g class="ohlc-candle ${cls}" data-candle="${i+1}"><line class="wick" x1="${x.toFixed(2)}" x2="${x.toFixed(2)}" y1="${yh.toFixed(2)}" y2="${yl.toFixed(2)}"/><rect class="body" x="${(x-bodyW/2).toFixed(2)}" y="${bodyTop.toFixed(2)}" width="${bodyW.toFixed(2)}" height="${bodyH.toFixed(2)}" rx="1.2"/><line class="open-tick" x1="${(x-bodyW/2-3).toFixed(2)}" x2="${(x-bodyW/2).toFixed(0)}" y1="${yo.toFixed(2)}" y2="${yo.toFixed(2)}"/><line class="close-tick" x1="${(x+bodyW/2).toFixed(0)}" x2="${(x+bodyW/2+3).toFixed(2)}" y1="${yc.toFixed(2)}" y2="${yc.toFixed(2)}"/><title>C${i+1} ${c.type||'DOJI'} | O ${money(c.open)} | H ${money(c.high)} | L ${money(c.low)} | C ${money(c.close)} | ${time}</title></g>`;
  }).join('');
  const labels=clean.map((c,i)=>`<span class="c ${String(c.type||'').toLowerCase()}" title="${esc(fmtTime(c.time||c.time_display||''))} · O ${money(c.open)} H ${money(c.high)} L ${money(c.low)} C ${money(c.close)}"><i>${i+1}</i><strong>${esc(String(c.type||'DOJI')[0])}</strong></span>`).join('');
  return `<div class="candle-visual ${compact?'compact':''}"><svg class="ohlc-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${clean.length}-candle OHLC chart">${grid}<line class="chart-base" x1="4" x2="${width-4}" y1="${height-bottom}" y2="${height-bottom}"/>${marks}</svg><div class="candles">${labels}</div></div>`;
}
function signal(s){return s?`<b class="signal ${s.includes('GREEN → RED')?'sr':'sg'}">${esc(s)}</b>`:'<span class="muted">—</span>';}
function render(body,items,kind){const query=kind==='stock'?($('stockSearch').value||'').trim().toLowerCase():'';const rows=(items||[]).filter(x=>{if(!query)return true;return [x.symbol,x.name,x.index_membership,(x.index_tags||[]).join(' ')].join(' ').toLowerCase().includes(query);});body.innerHTML=rows.length?rows.map((x,i)=>{const c=x.candles||[],l=c.at(-1)||{};return `<tr data-i="${i}"><td>${i+1}</td><td><strong>${esc(x.symbol)}</strong></td><td class="company">${esc(x.name||x.symbol)}</td><td>${membership(x.index_membership)}</td><td>${candles(c)}</td><td>${signal(x.signal)}</td><td>${money(l.open)}</td><td>${money(l.high)}</td><td>${money(l.low)}</td><td>${money(l.close)}</td></tr>`}).join(''):'<tr><td colspan="10" class="muted">No data available</td></tr>';body.querySelectorAll('tr[data-i]').forEach((r,i)=>r.onclick=()=>openModal(rows[i]));}
function fmtTime(value){if(!value)return'—';const raw=String(value);const d=new Date(raw);if(!Number.isNaN(d.getTime()))return d.toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:true,day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});const m=raw.match(/^(\d{2}-\d{2}-\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})/);if(m){let h=Number(m[2]);const ap=h>=12?'PM':'AM';h=h%12||12;return `${m[1]} ${String(h).padStart(2,'0')}:${m[3]}:${m[4]} ${ap}`;}return raw.replace('T',' ').replace('+05:30','');}
function openModal(x){$('modalTitle').textContent=`${x.symbol} · ${x.interval}`;$('modalSub').textContent=`${x.name||x.symbol} · ${x.index_membership||'OTHER'} · ${(x.index_tags||[]).join(' · ')}`;$('modalBody').innerHTML='<table class="detail"><thead><tr><th>No.</th><th>Type</th><th>Wick/Body</th><th>Time</th><th>Closed</th><th>Open</th><th>High</th><th>Low</th><th>Close</th></tr></thead><tbody>'+((x.candles||[]).map((c,i)=>`<tr class="${i===(x.candles.length-1)?'latest':''}"><td>${i+1}</td><td>${c.type}</td><td>${c.wick_body_percent==null?'N/A':Number(c.wick_body_percent).toFixed(1)+'%'}</td><td>${esc(fmtTime(c.time||c.time_display))}</td><td>${esc(fmtTime(c.closed_at||c.closed_at_display))}</td><td>${money(c.open)}</td><td>${money(c.high)}</td><td>${money(c.low)}</td><td>${money(c.close)}</td></tr>`).join('')||'<tr><td colspan="9">No data</td></tr>')+'</tbody></table>';$('modal').classList.remove('hidden');}
function renderSignals(a){$('signalPanel').classList.toggle('hidden',!a.length);$('signals').innerHTML=a.map(x=>`<article class="signalcard"><div class="signal-top"><strong>${esc(x.symbol)}</strong>${membership(x.index_membership)}</div><small>${esc((x.index_tags||[]).join(' · '))}</small><h3>${esc(x.signal)}</h3><div class="signal-pattern">${candles(x.seven_candles||[]).replace('candle-visual','candle-visual signal-visual')}</div><div class="signal-meta"><span>${esc(x.interval)} · SC study limit ${Number(x.sc_wick_limit_percent||40).toFixed(0)}% · candle closed ${esc(fmtTime(x.signal_candle_closed_at||x.signal_candle_closed_at_display))}</span><span>Visible ${x.dashboard_remaining_seconds||0}s</span></div></article>`).join('');}
function updateLastRefresh(){const now=new Date();$('lastRefresh').textContent=now.toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:true});}
async function scan(){if(busy)return;busy=true;$('status').textContent='Scanning…';try{const r=await fetch('/api/scanner?interval='+encodeURIComponent(interval)+'&_='+Date.now(),{cache:'no-store'});const d=await r.json();if(!r.ok||!d.success)throw Error(d.error||'Scanner error');latestStocks=d.stocks||[];render($('indicesBody'),d.indices||[],'index');render($('stocksBody'),latestStocks,'stock');renderSignals(d.signals||[]);$('indexCount').textContent=d.index_count;$('stockCount').textContent=d.stock_count;$('indexSectionCount').textContent=d.index_count;$('stockSectionCount').textContent=d.stock_count;$('signalCount').textContent=(d.signals||[]).length;$('scanTime').textContent=d.elapsed_seconds+'s';$('status').textContent='Live · closed candles only';updateLastRefresh();}catch(e){console.error(e);$('status').textContent='Error: '+e.message;}finally{busy=false;}}
function restart(){clearInterval(timer);timer=setInterval(scan,refresh);}
$('interval').onchange=e=>{interval=e.target.value;scan();};$('refresh').onchange=e=>{refresh=+e.target.value;restart();};$('scanNow').onclick=scan;$('stockSearch').oninput=()=>render($('stocksBody'),latestStocks,'stock');$('close').onclick=()=>$('modal').classList.add('hidden');$('modal').onclick=e=>{if(e.target===$('modal'))$('modal').classList.add('hidden')};setInterval(()=>$('clock').textContent=new Date().toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:true}),1000);scan();restart();