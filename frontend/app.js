/* ── StockRadar · 异动雷达前端 v5 — 方案化筛选 ── */

const CONCEPT_MAP = {
  '000001':['银行','金融科技'], '600519':['白酒','消费'], '300750':['锂电池','新能源车','储能'],
  '688256':['AI芯片','人工智能'], '002230':['人工智能','AI应用'], '300308':['光模块','CPO','算力'],
  '601360':['网络安全','AI大模型'], '300418':['AI大模型','AIGC'], '002261':['算力','华为概念','鸿蒙'],
  '300339':['鸿蒙','华为概念'], '000977':['服务器','算力','国产替代'], '688111':['AI办公','信创'],
  '688041':['AI芯片','国产替代'], '300364':['AI内容','AIGC'], '300624':['AIGC','AI应用'],
  '600570':['金融科技','数据要素'], '002371':['半导体设备','国产替代'], '688981':['芯片','国产替代'],
  '300059':['券商','金融科技'], '601012':['光伏','新能源'], '002475':['苹果产业链','消费电子','MR'],
  '300760':['医疗器械','创新药'], '600036':['银行','金融科技'], '601318':['保险','金融科技'],
  '002594':['新能源车','锂电池','智能驾驶'], '300274':['光伏','储能'], '688012':['半导体设备','国产替代'],
  '300033':['金融科技','AI应用'], '300496':['智能驾驶','鸿蒙'], '002049':['芯片','军工电子'],
  '688036':['消费电子','手机'], '603986':['存储芯片','国产替代'], '300782':['射频芯片','5G'],
  '002415':['安防','人工智能','智慧城市'], '300124':['工业自动化','机器人'], '688169':['扫地机器人','智能家居'],
  '300474':['GPU','国产替代','军工电子'], '002241':['MR','苹果产业链'], '300661':['模拟芯片','芯片'],
};

/* ── 默认方案 ── */
const DEFAULT_SCHEMES = [{
  id: 'scheme_' + Date.now(),
  name: '方案1',
  enabled: true,
  conditions: {
    marketCap:      { enabled: false, min: 20, max: 200 },
    bigOrder:       { enabled: false, ratio: 0.1 },
    amountHigh:     { enabled: false, days: 5 },
    amountLow:      { enabled: false, days: 5 },
    limitUp:        { enabled: false },
    limitDown:      { enabled: false },
    shortRise:      { enabled: false, seconds: 60, percent: 3 },
    breakMinMA:     { enabled: false, minutes: 5 },
    breakDayMA:     { enabled: false, period: 5 },
    breakGolden:    { enabled: false, days: 20, ratio: 0.382 },
    amountMultiple: { enabled: false, multiple: 2 },
    volumeRatio:    { enabled: false, min: 2 },
    bollingerUp:    { enabled: false, band: 'upper', period: '20d' },
    bollingerDown:  { enabled: false, band: 'lower', period: '20d' },
    cupHandle:      { enabled: false, days: 20, dayA: 5, dayB: 10, minPct: 10, maxPct: 30 },
  }
}];

const CONDITION_DEFS = [
  { key:'marketCap',    label:'流通市值范围', unit:'亿', fields:['min','max'] },
  { key:'bigOrder',     label:'大单占流通市值 ≥', unit:'%', fields:['ratio'] },
  { key:'amountHigh',   label:'近N天成交金额新高', unit:'天', fields:['days'] },
  { key:'amountLow',    label:'近N天成交金额新低', unit:'天', fields:['days'] },
  { key:'limitUp',      label:'涨停', unit:'', fields:[] },
  { key:'limitDown',    label:'跌停', unit:'', fields:[] },
  { key:'shortRise',    label:'短时涨幅', unit:'', fields:['seconds','percent'] },
  { key:'breakMinMA',   label:'突破X分钟均线', unit:'分钟', fields:['minutes'] },
  { key:'breakDayMA',   label:'突破X日均线', unit:'', fields:['period'] },
  { key:'breakGolden',  label:'突破回撤值', unit:'', fields:['days','ratio'] },
  { key:'amountMultiple', label:'今日成交金额≥昨日X倍', unit:'倍', fields:['multiple'] },
  { key:'volumeRatio',   label:'量比 ≥', unit:'', fields:['min'] },
  { key:'cupHandle',     label:'杯柄形态', unit:'', fields:['days','dayA','dayB','minPct','maxPct'], multiLine:true },
  { key:'bollingerUp',   label:'突破布林线', unit:'', fields:['band','period'] },
  { key:'bollingerDown', label:'跌破布林线', unit:'', fields:['band','period'] },
  { key:'priceCompare',  label:'价格组合比较', unit:'', fields:[], dynamic:true },
  { key:'amountCompare', label:'成交额组合比较', unit:'', fields:[], dynamic:true },
];

/* ── 状态 ── */
let schemes = JSON.parse(localStorage.getItem('stock-radar-schemes')) || JSON.parse(JSON.stringify(DEFAULT_SCHEMES));
let alerts = [];
let reviewAlerts = [];  // 复盘结果
let isPinned = true;
let ws = null;
let wsConnected = false;
let chartMode = 'kline';
let settingsOpen = false;
let currentMode = 'realtime'; // 'realtime' | 'review'
const klinesMap = {};

/* ── DOM ── */
const alertList     = document.getElementById('alertList');
const marketStatus  = document.getElementById('marketStatus');
const refreshStatus = document.getElementById('refreshStatus');
const refreshDot    = document.getElementById('refreshDot');
const refreshBtn    = document.getElementById('refreshBtn');
const settingsBtn   = document.getElementById('settingsBtn');
const settingsPanel = document.getElementById('settingsPanel');
const schemeBar     = document.getElementById('schemeBar');
const pinBtn        = document.getElementById('pinBtn');
const minimizeBtn   = document.getElementById('minimizeBtn');
const closeBtn      = document.getElementById('closeBtn');
const opacitySlider = document.getElementById('opacitySlider');
const modeKline      = document.getElementById('modeKline');
const modeSentiment  = document.getElementById('modeSentiment');
const modeRealtime   = document.getElementById('modeRealtime');
const modeReview     = document.getElementById('modeReview');
const sentimentPanel = document.getElementById('sentimentPanel');
const hotPanel       = document.getElementById('hotPanel');

/* ── 工具函数 ── */
const MARKET_LABELS = { open:'交易中', closed:'已收盘', lunch:'午休', pre:'未开盘', call:'集合竞价' };
function updateMarketLabel(s) {
  marketStatus.textContent = MARKET_LABELS[s]||'未知';
  marketStatus.className = `market-status ${s==='open'||s==='call'?'open':s==='lunch'?'lunch':'closed'}`;
}
function esc(s) { return s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : ''; }
function saveSchemes() {
  localStorage.setItem('stock-radar-schemes', JSON.stringify(schemes));
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: 'update_schemes', schemes }));
  }
}

/* ── 迷你图 ── */
function drawAllMiniCharts() {
  alertList.querySelectorAll('.alert-chart canvas').forEach(cv => {
    const p = parseFloat(cv.dataset.price)||50, c = parseFloat(cv.dataset.change)||0;
    const aid = cv.dataset.alertId || '';
    const klines = klinesMap[aid] || [];
    const r = cv.parentElement.getBoundingClientRect();
    if (!r.width||!r.height) return;
    cv.width=r.width*2; cv.height=r.height*2;
    cv.style.width=r.width+'px'; cv.style.height=r.height+'px';
    const ctx=cv.getContext('2d'); ctx.scale(2,2);
    chartMode==='kline'?drawK(ctx,r.width,r.height,p,c,klines):drawM(ctx,r.width,r.height,p,c);
  });
}
function drawK(ctx,W,H,bp,cp,klines) {
  let d = klines && klines.length ? klines : null;
  if (!d) { const n=10; d=[];let cl=bp/(1+cp/100); for(let i=0;i<n;i++){const o=cl+(Math.random()-.45)*bp*.025,h=Math.max(o,cl)+Math.random()*bp*.015,l=Math.min(o,cl)-Math.random()*bp*.015,nc=i===n-1?bp:o+(Math.random()-.45)*bp*.03;d.push({o,h,l,c:nc});cl=nc;} }
  const n=d.length,all=d.flatMap(x=>[x.h,x.l]),mn=Math.min(...all),mx=Math.max(...all),rng=mx-mn||1;
  const p=2,cH=H-p*2,bW=W/n,toY=v=>p+(1-(v-mn)/rng)*cH;
  for(let i=0;i<n;i++){const x=bW*i+bW/2,up=d[i].c>=d[i].o,col=up?'#ef4444':'#22c55e';
    ctx.strokeStyle=col;ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,toY(d[i].h));ctx.lineTo(x,toY(d[i].l));ctx.stroke();
    const bt=toY(Math.max(d[i].o,d[i].c)),bh=Math.max(toY(Math.min(d[i].o,d[i].c))-bt,.8);
    ctx.fillStyle=col;ctx.fillRect(x-bW*.28,bt,bW*.56,bh);}
}
function drawM(ctx,W,H,bp,cp) {
  const clP=bp/(1+cp/100),pts=60,data=[];
  for(let i=0;i<=pts;i++){data.push(clP*(1+(cp/100)*(i/pts))+(Math.random()-.5)*bp*.006);}
  const mn=Math.min(...data)*.999,mx=Math.max(...data)*1.001,rng=mx-mn||1;
  const p=2,cH=H-p*2,toX=i=>(i/pts)*W,toY=v=>p+(1-(v-mn)/rng)*cH;
  ctx.strokeStyle='rgba(255,255,255,.08)';ctx.lineWidth=.5;ctx.setLineDash([2,2]);
  ctx.beginPath();ctx.moveTo(0,toY(clP));ctx.lineTo(W,toY(clP));ctx.stroke();ctx.setLineDash([]);
  const g=ctx.createLinearGradient(0,0,0,H);
  if(cp>=0){g.addColorStop(0,'rgba(239,68,68,.2)');g.addColorStop(1,'rgba(239,68,68,0)');}
  else{g.addColorStop(0,'rgba(34,197,94,.2)');g.addColorStop(1,'rgba(34,197,94,0)');}
  ctx.beginPath();ctx.moveTo(toX(0),toY(data[0]));
  for(let i=1;i<data.length;i++)ctx.lineTo(toX(i),toY(data[i]));
  ctx.lineTo(W,H);ctx.lineTo(0,H);ctx.closePath();ctx.fillStyle=g;ctx.fill();
  ctx.beginPath();ctx.moveTo(toX(0),toY(data[0]));
  for(let i=1;i<data.length;i++)ctx.lineTo(toX(i),toY(data[i]));
  ctx.strokeStyle=cp>=0?'#ef4444':'#22c55e';ctx.lineWidth=1.2;ctx.stroke();
}

/* ── 事件绑定 ── */
settingsBtn?.addEventListener('click', () => {
  settingsOpen = !settingsOpen;
  settingsPanel.classList.toggle('active', settingsOpen);
  if (settingsOpen) renderSettings();
});
let sentimentOpen = false;
let sentimentData = null;

modeKline?.addEventListener('click', () => {
  chartMode = 'kline';
  modeKline.classList.add('active');
  modeSentiment.classList.remove('active');
  sentimentOpen = false;
  sentimentPanel.classList.remove('active');
  alertList.style.display = '';
  hotPanel.style.display = '';
  schemeBar.style.display = '';   // ← 恢复方案标签栏
  // 恢复盘中/复盘按钮
  if (modeRealtime) { modeRealtime.disabled = false; modeRealtime.style.opacity = ''; }
  if (modeReview)   { modeReview.disabled   = false; modeReview.style.opacity   = ''; }
  drawAllMiniCharts();
});
modeSentiment?.addEventListener('click', () => {
  sentimentOpen = !sentimentOpen;
  modeSentiment.classList.toggle('active', sentimentOpen);
  modeKline.classList.toggle('active', !sentimentOpen);
  sentimentPanel.classList.toggle('active', sentimentOpen);
  // 情绪面板打开时隐藏方案栏/列表；关闭时恢复
  alertList.style.display = sentimentOpen ? 'none' : '';
  hotPanel.style.display  = sentimentOpen ? 'none' : '';
  schemeBar.style.display = sentimentOpen ? 'none' : '';
  // 情绪面板不禁用盘中/复盘按钮（允许随时切换）
  if (sentimentOpen) {
    // 每次打开都重新拉取最新数据（不使用缓存）
    renderSentimentPanel();
    sentimentData = null;
    fetchSentimentData();
  }
});
modeRealtime?.addEventListener('click', () => {
  // 切换到盘中时，关闭情绪面板
  if (sentimentOpen) {
    sentimentOpen = false;
    modeSentiment.classList.remove('active');
    modeKline.classList.add('active');
    sentimentPanel.classList.remove('active');
    alertList.style.display = '';
    hotPanel.style.display  = '';
    schemeBar.style.display = '';
  }
  switchMode('realtime');
});
modeReview?.addEventListener('click', () => {
  // 切换到复盘时，关闭情绪面板
  if (sentimentOpen) {
    sentimentOpen = false;
    modeSentiment.classList.remove('active');
    modeKline.classList.add('active');
    sentimentPanel.classList.remove('active');
    alertList.style.display = '';
    hotPanel.style.display  = '';
    schemeBar.style.display = '';
  }
  switchMode('review');
});
refreshBtn?.addEventListener('click', () => {
  // 旋转动画
  refreshBtn.style.transition = 'transform 0.6s ease';
  refreshBtn.style.transform = 'rotate(360deg)';
  setTimeout(() => { refreshBtn.style.transition = ''; refreshBtn.style.transform = ''; }, 650);

  if (sentimentOpen) {
    // 情绪面板：重新拉取情绪数据
    renderSentimentPanel();
    fetchSentimentData();
    return;
  }

  if (ws && ws.readyState === WebSocket.OPEN) {
    // 先同步最新方案到后端
    ws.send(JSON.stringify({ action: 'update_schemes', schemes }));
    setTimeout(() => {
      if (currentMode === 'review') {
        // 复盘模式：触发后端重新扫描
        ws.send(JSON.stringify({ action: 'refresh' }));
      } else {
        // 盘中模式：请求后端重新推送 init（含最新异动列表）
        ws.send(JSON.stringify({ action: 'refresh' }));
      }
    }, 200);
  } else {
    // WS 未连接：尝试重连
    connectWS();
  }
});
pinBtn?.addEventListener('click', () => { isPinned=!isPinned; pinBtn.classList.toggle('pinned',isPinned); window.radarAPI?.togglePin?.(); });
pinBtn?.classList.add('pinned');
minimizeBtn?.addEventListener('click', () => window.radarAPI?.minimize?.());
closeBtn?.addEventListener('click', () => window.radarAPI?.close?.());
opacitySlider?.addEventListener('input', e => { const v=Number(e.target.value)/100; document.body.style.opacity=v; window.radarAPI?.setOpacity?.(v); });

/* ── WebSocket ── */
function connectWS() {
  refreshStatus.textContent='连接中…'; refreshDot.style.background='#f59e0b';
  ws = new WebSocket('ws://localhost:9876');
  ws.onopen = () => {
    wsConnected=true; refreshStatus.textContent='已连接'; refreshDot.style.background='#22c55e';
    ws.send(JSON.stringify({ action: 'update_schemes', schemes }));
    renderList();
  };
  ws.onmessage = e => { try { const d = JSON.parse(e.data);
    if (d.type==='init') { alerts=d.alerts||[]; for(const a of alerts){if(a.klines&&a.klines.length)klinesMap[a.id]=a.klines;} if(d.market)updateMarketLabel(d.market); if(d.review_alerts) reviewAlerts=d.review_alerts; renderList(); }
    if (d.type==='alerts') { const items=d.items||[],ids=items.map(i=>i.id); for(const a of items){if(a.klines&&a.klines.length)klinesMap[a.id]=a.klines;} alerts=[...items,...alerts].slice(0,200); if(currentMode==='realtime'){renderList(ids); alertList.scrollTop=0;} }
    if (d.type==='review_progress') {
      // 显示复盘进度（数据下载/扫描中）
      const frBtn=document.getElementById('forceReviewBtn');
      if(frBtn){ frBtn.textContent=`⏳ ${d.msg||'处理中…'}`; frBtn.disabled=true; frBtn.style.opacity='0.7'; }
      // 在列表区域显示进度提示
      if(currentMode==='review'){
        alertList.innerHTML=`<div class="empty-state"><div class="empty-icon">⏳</div><div class="empty-title">${d.step==='downloading'?'下载行情数据':'复盘扫描中'}</div><div class="empty-desc" style="font-size:10px;max-width:200px;word-break:break-all;">${esc(d.msg||'')}</div></div>`;
      }
    }
    if (d.type==='review_init' || d.type==='review_alerts') { reviewAlerts=d.alerts||d.items||[]; for(const a of reviewAlerts){if(a.klines&&a.klines.length)klinesMap[a.id]=a.klines;} if(currentMode==='review') renderList(); const frBtn=document.getElementById('forceReviewBtn'); if(frBtn){frBtn.textContent='📋 立即复盘';frBtn.disabled=false;frBtn.style.opacity='';} }
    if (d.type==='review_update') { const updates=d.updates||{}; for(const a of reviewAlerts){if(updates[a.code]){a.price=updates[a.code].price;a.change=updates[a.code].change;a.speed=updates[a.code].speed||0;a.amount=updates[a.code].amount||a.amount;}} if(currentMode==='review') renderList(); }
    if (d.type==='market') updateMarketLabel(d.state);
    if (d.type==='sentiment') { sentimentData = d.data; renderSentimentFromData(d.data); }
    if (d.type==='sector_stocks') {
      // 板块股票数据返回，填充对应的展开区域
      const sectorName = d.sector_name;
      const stocks = d.stocks || [];
      // 找到对应的 sector-stocks div
      document.querySelectorAll('.sector-row').forEach(row => {
        if (row.dataset.sectorName === sectorName) {
          const key = row.dataset.sectorKey;
          const stocksDiv = document.getElementById(`stocks_${key}`);
          if (stocksDiv) {
            if (!stocks.length) {
              stocksDiv.innerHTML = '<div style="color:var(--muted);font-size:10px;">暂无数据</div>';
            } else {
              stocksDiv.innerHTML = stocks.map(s => {
                const cls = s.change >= 0 ? 'up' : 'down';
                const sign = s.change >= 0 ? '+' : '';
                return `<div style="display:flex;justify-content:space-between;padding:2px 4px;font-size:10px;border-bottom:1px solid rgba(255,255,255,0.04);">
                  <span style="color:var(--text);">${esc(s.name)}</span>
                  <span class="${cls}" style="font-weight:600;">${sign}${s.change.toFixed(2)}%</span>
                </div>`;
              }).join('');
            }
          }
        }
      });
    }
  } catch(err){console.error('[WS]',err);} };
  ws.onclose = () => { wsConnected=false; refreshStatus.textContent='断开，5s重连…'; refreshDot.style.background='#ef4444'; renderList(); setTimeout(connectWS,5000); };
  ws.onerror = () => ws.close();
}

/* ── 模式切换 ── */
function switchMode(mode) {
  currentMode = mode;
  modeRealtime.classList.toggle('active', mode === 'realtime');
  modeReview.classList.toggle('active', mode === 'review');
  renderSchemeBar();
  renderList();
  if (settingsOpen) renderSettings();
}

/* ── 启动 ── */
updateMarketLabel('closed');
renderSchemeBar();
connectWS();

/* ── 获取当前启用的方案名集合 ── */
function getEnabledSchemeNames() {
  return new Set(schemes.filter(s => s.enabled).map(s => s.name));
}

/* ── 渲染卡片 ── */
function renderAlert(a, isNew, enabledNames) {
  const cc = a.change >= 0 ? 'up' : 'down';
  const sign = a.change >= 0 ? '+' : '';
  const nc = isNew ? ' new' : '';
  let concepts = a.concepts || [];
  if (!concepts.length && a.code && CONCEPT_MAP[a.code]) concepts = CONCEPT_MAP[a.code];
  let cHtml = concepts.length ? '<div class="concept-tags">' + concepts.map(c => `<span class="concept-tag">${esc(c)}</span>`).join('') + '</div>' : '';
  let mHtml = '';
  if (a.matched_schemes && a.matched_schemes.length) {
    // 只显示当前仍启用的方案标签
    const visibleSchemes = enabledNames ? a.matched_schemes.filter(m => enabledNames.has(m)) : a.matched_schemes;
    if (visibleSchemes.length) {
      mHtml = '<div class="matched-tags">' + visibleSchemes.map(m => `<span class="matched-tag">${esc(m)}</span>`).join('') + '</div>';
    }
  }
  let bigOrderHtml = '';
  if (a.big_order_count && a.big_order_count > 0) {
    bigOrderHtml = `<span class="big-order-count">大单×${a.big_order_count}</span>`;
  }
  return `<div class="alert-card${nc}" data-id="${a.id}"><div class="alert-info">
  <div class="alert-top"><span class="stock-name">${esc(a.name)}</span><span class="stock-code">${a.code}</span>${cHtml}<span class="alert-time">${a.time}</span></div>
  <div class="alert-middle">${mHtml}${bigOrderHtml}<span class="change ${cc}">${sign}${a.change}%</span><span class="alert-meta">速${a.speed}%/m · ${a.amount}亿</span></div>
</div><div class="alert-chart"><canvas data-alert-id="${a.id}" data-price="${a.price}" data-change="${a.change}"></canvas></div></div>`;
}

/* ── 列表渲染 ── */
function renderList(newIds) {
  const f = currentMode === 'review' ? reviewAlerts : alerts;
  const enabledNames = getEnabledSchemeNames();
  // 过滤：只显示至少有一个启用方案匹配的 alert
  const filtered = f.filter(a => {
    if (!a.matched_schemes || !a.matched_schemes.length) return true; // 无方案标签的保留
    return a.matched_schemes.some(m => enabledNames.has(m));
  });
  if (!filtered.length) {
    const emptyMsg = currentMode === 'review'
      ? { icon:'📋', title:'暂无复盘数据', desc:'收盘后自动扫描符合方案的个股' }
      : { icon:'📡', title: wsConnected?'暂无异动':'等待连接', desc: wsConnected?'等待符合方案的个股…':'python engine/server.py' };
    alertList.innerHTML = `<div class="empty-state"><div class="empty-icon">${emptyMsg.icon}</div><div class="empty-title">${emptyMsg.title}</div><div class="empty-desc">${emptyMsg.desc}</div></div>`;
    return;
  }
  const ns = new Set(newIds||[]);
  alertList.innerHTML = filtered.map(a => renderAlert(a, ns.has(a.id), enabledNames)).join('');
  requestAnimationFrame(drawAllMiniCharts);
  alertList.querySelectorAll('.alert-card').forEach(card => {
    card.addEventListener('click', () => {
      const id = card.dataset.id || '';
      const code = id.split('-')[0];
      if (code && window.radarAPI?.openStock) {
        window.radarAPI.openStock(code);
        card.style.background = 'rgba(99,102,241,0.15)';
        card.style.borderColor = 'var(--accent)';
        setTimeout(() => { card.style.background = ''; card.style.borderColor = ''; }, 400);
      }
    });
  });
}

/* ── 方案栏渲染 ── */
function renderSchemeBar() {
  let html = schemes.map(s => {
    const cls = s.enabled ? 'scheme-pill active' : 'scheme-pill';
    return `<button class="${cls}" data-id="${s.id}">${esc(s.name)}</button>`;
  }).join('');

  // 复盘模式下加"立即复盘"按钮
  if (currentMode === 'review') {
    const isOpen = marketStatus.classList.contains('open');
    const disabled = isOpen ? 'disabled title="盘中不可用，请收盘后使用"' : '';
    const style = isOpen
      ? 'opacity:0.4;cursor:not-allowed;'
      : 'background:rgba(99,102,241,0.15);border-color:var(--accent);color:var(--accent);cursor:pointer;';
    html += `<button id="forceReviewBtn" class="scheme-pill" style="margin-left:auto;flex-shrink:0;${style}" ${disabled}>📋 立即复盘</button>`;
  }

  schemeBar.innerHTML = html;
  schemeBar.querySelectorAll('.scheme-pill').forEach(btn => {
    if (btn.id === 'forceReviewBtn') {
      btn.addEventListener('click', () => {
        if (btn.disabled) return;
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ action: 'update_schemes', schemes }));
          setTimeout(() => {
            ws.send(JSON.stringify({ action: 'force_review' }));
          }, 100);
          btn.textContent = '⏳ 扫描中…';
          btn.disabled = true;
          btn.style.opacity = '0.5';
          // 3分钟后恢复（防止卡住）
          setTimeout(() => {
            btn.textContent = '📋 立即复盘';
            btn.disabled = false;
            btn.style.opacity = '';
          }, 180000);
        } else {
          connectWS();
        }
      });
      return;
    }
    btn.addEventListener('click', () => {
      const sc = schemes.find(x => x.id === btn.dataset.id);
      if (sc) { sc.enabled = !sc.enabled; saveSchemes(); renderSchemeBar(); renderList(); }
    });
  });
}

/* ── 设置面板渲染 ── */
function renderSettings() {
  let html = `<div class="settings-header"><button class="settings-back-btn" id="settingsBackBtn">←</button><span class="settings-title">⚙️ 方案设置</span></div><div class="settings-scroll">`;
  for (const s of schemes) {
    html += `<div class="scheme-card" data-id="${s.id}"><div class="scheme-card-head">`;
    html += `<input class="scheme-name-input" value="${esc(s.name)}" data-id="${s.id}" />`;
    html += `<div style="display:flex;gap:4px;"><button class="scheme-save-btn" data-id="${s.id}" style="background:rgba(34,197,94,0.1);border:1px solid #22c55e;color:#22c55e;font-size:11px;padding:2px 8px;border-radius:5px;cursor:pointer;font-weight:600;">💾 保存</button>`;
    html += `<button class="scheme-delete-btn" data-id="${s.id}">🗑</button></div></div>`;
    for (const def of CONDITION_DEFS) {
      const cond = s.conditions[def.key] || {};
      const checked = cond.enabled ? 'checked' : '';
      html += `<div class="condition-row"><input type="checkbox" class="cond-check" data-scheme="${s.id}" data-key="${def.key}" ${checked} />`;
      html += `<span class="cond-label">${def.label}</span>`;
      if (def.key === 'marketCap') {
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="marketCap" data-field="min" value="${cond.min||20}" step="1" /><span class="cond-sep">~</span>`;
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="marketCap" data-field="max" value="${cond.max||200}" step="1" /><span class="cond-unit">亿</span>`;
      } else if (def.key === 'bigOrder') {
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="bigOrder" data-field="ratio" value="${cond.ratio||0.1}" step="0.01" /><span class="cond-unit">%</span>`;
        html += `<div style="font-size:9px;color:var(--muted);margin:1px 0 0 20px;">触发时前端统计当日大单次数</div>`;
      } else if (def.key === 'amountHigh' || def.key === 'amountLow') {
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="${def.key}" data-field="days" value="${cond.days||5}" step="1" /><span class="cond-unit">天</span>`;
      } else if (def.key === 'shortRise') {
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="shortRise" data-field="seconds" value="${cond.seconds||60}" step="1" /><span class="cond-unit">秒涨</span>`;
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="shortRise" data-field="percent" value="${cond.percent||3}" step="0.5" /><span class="cond-unit">%</span>`;
      } else if (def.key === 'breakMinMA') {
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="breakMinMA" data-field="minutes" value="${cond.minutes||5}" step="1" /><span class="cond-unit">分钟</span>`;
      } else if (def.key === 'breakDayMA') {
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="breakDayMA" data-field="period" value="${cond.period||5}" step="1" /><span class="cond-unit">日</span>`;
      } else if (def.key === 'breakGolden') {
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="breakGolden" data-field="days" value="${cond.days||20}" step="1" /><span class="cond-unit">天内</span>`;
        html += `<input type="number" class="cond-input w70" data-scheme="${s.id}" data-key="breakGolden" data-field="ratio" value="${cond.ratio||0.382}" step="0.001" /><span class="cond-unit">系数</span>`;
        html += `<div style="font-size:9px;color:var(--muted);margin:1px 0 0 20px;">最高价 −（最高价 − 最低价）× 系数</div>`;
      } else if (def.key === 'amountMultiple') {
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="amountMultiple" data-field="multiple" value="${cond.multiple||2}" step="0.5" /><span class="cond-unit">倍</span>`;
      } else if (def.key === 'volumeRatio') {
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="volumeRatio" data-field="min" value="${cond.min||2}" step="0.5" />`;
      } else if (def.key === 'bollingerUp' || def.key === 'bollingerDown') {
        const band = cond.band || (def.key === 'bollingerUp' ? 'upper' : 'lower');
        const period = cond.period || '20d';
        html += `<select class="cond-input" style="width:58px;" data-scheme="${s.id}" data-key="${def.key}" data-field="band">`;
        html += `<option value="upper" ${band==='upper'?'selected':''}>上轨</option>`;
        html += `<option value="middle" ${band==='middle'?'selected':''}>中轨</option>`;
        html += `<option value="lower" ${band==='lower'?'selected':''}>下轨</option></select>`;
        html += `<select class="cond-input" style="width:68px;" data-scheme="${s.id}" data-key="${def.key}" data-field="period">`;
        html += `<option value="20d" ${period==='20d'?'selected':''}>20日</option>`;
        html += `<option value="5d" ${period==='5d'?'selected':''}>5日</option>`;
        html += `<option value="30m" ${period==='30m'?'selected':''}>30分钟</option></select>`;
      } else if (def.key === 'cupHandle') {
        html += `</div><div class="condition-row" style="padding-left:20px;flex-wrap:wrap;gap:4px;">`;
        html += `<span class="cond-unit" style="color:var(--muted);">现价突破最近</span>`;
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="cupHandle" data-field="days" value="${cond.days||20}" step="1" />`;
        html += `<span class="cond-unit">天高点</span>`;
        html += `</div><div class="condition-row" style="padding-left:20px;flex-wrap:wrap;gap:4px;">`;
        html += `<span class="cond-unit" style="color:var(--muted);">往前第</span>`;
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="cupHandle" data-field="dayA" value="${cond.dayA||5}" step="1" />`;
        html += `<span class="cond-unit" style="color:var(--muted);">天收盘高于第</span>`;
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="cupHandle" data-field="dayB" value="${cond.dayB||10}" step="1" />`;
        html += `<span class="cond-unit" style="color:var(--muted);">天收盘</span>`;
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="cupHandle" data-field="minPct" value="${cond.minPct||10}" step="1" />`;
        html += `<span class="cond-sep">~</span>`;
        html += `<input type="number" class="cond-input" data-scheme="${s.id}" data-key="cupHandle" data-field="maxPct" value="${cond.maxPct||30}" step="1" />`;
        html += `<span class="cond-unit">%</span>`;
      } else if (def.key === 'priceCompare') {
        // 价格组合比较：动态多行
        const rules = cond.rules || [{ dayL:1, fieldL:'close', op:'gt', dayR:2, fieldR:'close' }];
        html += `</div>`;
        rules.forEach((rule, ri) => {
          html += `<div class="condition-row pc-rule" style="padding-left:20px;flex-wrap:wrap;gap:3px;" data-scheme="${s.id}" data-key="priceCompare" data-ri="${ri}">`;
          html += `<span class="cond-unit" style="color:var(--muted);">往前第</span>`;
          html += `<input type="number" class="cond-input pc-field" data-f="dayL" value="${rule.dayL||1}" step="1" min="1" style="width:36px;" />`;
          html += `<span class="cond-unit" style="color:var(--muted);">天</span>`;
          html += `<select class="cond-input pc-field" data-f="fieldL" style="width:52px;"><option value="close" ${rule.fieldL==='close'?'selected':''}>收盘</option><option value="open" ${rule.fieldL==='open'?'selected':''}>开盘</option><option value="high" ${rule.fieldL==='high'?'selected':''}>最高</option><option value="low" ${rule.fieldL==='low'?'selected':''}>最低</option></select>`;
          html += `<select class="cond-input pc-field" data-f="op" style="width:42px;"><option value="gt" ${rule.op==='gt'?'selected':''}>大于</option><option value="lt" ${rule.op==='lt'?'selected':''}>小于</option></select>`;
          html += `<span class="cond-unit" style="color:var(--muted);">往前第</span>`;
          html += `<input type="number" class="cond-input pc-field" data-f="dayR" value="${rule.dayR||2}" step="1" min="1" style="width:36px;" />`;
          html += `<span class="cond-unit" style="color:var(--muted);">天</span>`;
          html += `<select class="cond-input pc-field" data-f="fieldR" style="width:52px;"><option value="close" ${rule.fieldR==='close'?'selected':''}>收盘</option><option value="open" ${rule.fieldR==='open'?'selected':''}>开盘</option><option value="high" ${rule.fieldR==='high'?'selected':''}>最高</option><option value="low" ${rule.fieldR==='low'?'selected':''}>最低</option></select>`;
          html += `<span class="cond-unit" style="color:var(--muted);">的</span>`;
          html += `<input type="number" class="cond-input pc-field" data-f="multiplier" value="${rule.multiplier||''}" step="0.1" min="0" style="width:40px;" placeholder="" />`;
          html += `<span class="cond-unit" style="color:var(--muted);">倍</span>`;
          if (ri > 0) html += `<button class="pc-del-btn" data-scheme="${s.id}" data-key="priceCompare" data-ri="${ri}" style="background:none;border:none;color:#ef4444;cursor:pointer;font-size:13px;padding:0 2px;">✕</button>`;
          html += `</div>`;
        });
        html += `<div class="condition-row" style="padding-left:20px;font-size:9px;color:var(--muted);">倍数不填代表只要满足大于或小于即可</div>`;
        html += `<div class="condition-row" style="padding-left:20px;"><button class="pc-add-btn" data-scheme="${s.id}" data-key="priceCompare" style="background:none;border:1px dashed var(--border);color:var(--accent);cursor:pointer;font-size:11px;padding:2px 10px;border-radius:4px;">＋ 增加条件</button></div>`;
        html += `<div`; // dummy open tag to match the closing </div> below
      } else if (def.key === 'amountCompare') {
        // 成交额组合比较：动态多行
        const rules = cond.rules || [{ dayL:1, op:'gt', dayR:2 }];
        html += `</div>`;
        rules.forEach((rule, ri) => {
          html += `<div class="condition-row ac-rule" style="padding-left:20px;flex-wrap:wrap;gap:3px;" data-scheme="${s.id}" data-key="amountCompare" data-ri="${ri}">`;
          html += `<span class="cond-unit" style="color:var(--muted);">往前第</span>`;
          html += `<input type="number" class="cond-input ac-field" data-f="dayL" value="${rule.dayL||1}" step="1" min="1" style="width:36px;" />`;
          html += `<span class="cond-unit" style="color:var(--muted);">天成交额</span>`;
          html += `<select class="cond-input ac-field" data-f="op" style="width:42px;"><option value="gt" ${rule.op==='gt'?'selected':''}>大于</option><option value="lt" ${rule.op==='lt'?'selected':''}>小于</option></select>`;
          html += `<span class="cond-unit" style="color:var(--muted);">往前第</span>`;
          html += `<input type="number" class="cond-input ac-field" data-f="dayR" value="${rule.dayR||2}" step="1" min="1" style="width:36px;" />`;
          html += `<span class="cond-unit" style="color:var(--muted);">天成交额的</span>`;
          html += `<input type="number" class="cond-input ac-field" data-f="multiplier" value="${rule.multiplier||''}" step="0.1" min="0" style="width:40px;" placeholder="" />`;
          html += `<span class="cond-unit" style="color:var(--muted);">倍</span>`;
          if (ri > 0) html += `<button class="ac-del-btn" data-scheme="${s.id}" data-key="amountCompare" data-ri="${ri}" style="background:none;border:none;color:#ef4444;cursor:pointer;font-size:13px;padding:0 2px;">✕</button>`;
          html += `</div>`;
        });
        html += `<div class="condition-row" style="padding-left:20px;font-size:9px;color:var(--muted);">倍数不填代表只要满足大于或小于即可</div>`;
        html += `<div class="condition-row" style="padding-left:20px;"><button class="ac-add-btn" data-scheme="${s.id}" data-key="amountCompare" style="background:none;border:1px dashed var(--border);color:var(--accent);cursor:pointer;font-size:11px;padding:2px 10px;border-radius:4px;">＋ 增加条件</button></div>`;
        html += `<div`; // dummy open tag to match the closing </div> below
      }
      html += `</div>`;
    }
    html += `</div>`;
  }
  html += `</div><div style="display:flex;gap:6px;padding:4px 8px 10px;"><button class="add-scheme-btn" id="addSchemeBtn" style="flex:1;margin:0;">＋ 新建方案</button></div>`;
  settingsPanel.innerHTML = html;
  bindSettingsEvents();
}

/* ══════════════════════════════════════════════════════
   情绪面板
══════════════════════════════════════════════════════ */

/* 渲染骨架（加载中状态） */
function renderSentimentPanel() {
  sentimentPanel.innerHTML = `
    <div class="sent-section">
      <div class="sent-section-title">📈 沪深指数</div>
      <div id="sent-index">
        <div style="color:var(--muted);font-size:11px;">加载中…</div>
      </div>
    </div>
    <div class="sent-section">
      <div class="sent-section-title">🌡️ 市场宽度</div>
      <div id="sent-breadth">
        <div style="color:var(--muted);font-size:11px;">加载中…</div>
      </div>
    </div>
    <div class="sent-section">
      <div class="sent-section-title">🔥 题材涨停排名（今日）</div>
      <div id="sent-sectors">
        <div style="color:var(--muted);font-size:11px;">加载中…</div>
      </div>
    </div>
    <div class="sent-section">
      <div class="sent-section-title">📅 近7日板块热力</div>
      <div id="sent-history">
        <div style="color:var(--muted);font-size:11px;">加载中…</div>
      </div>
    </div>
  `;
}

/* 通过 WebSocket 向后端请求情绪数据 */
function fetchSentimentData() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: 'get_sentiment' }));
  } else {
    // WS 未连接时，直接用前端接口（降级）
    fetchSentimentDataFrontend();
  }
}

/* 后端返回情绪数据后渲染 */
function renderSentimentFromData(data) {
  if (!sentimentOpen) return;
  if (data.error) {
    console.error('[情绪] 后端错误:', data.error);
    return;
  }

  // 1. 沪深指数 + 支撑/压力位
  const indices = data.indices || [];
  const klines = data.sh_klines || [];
  let indexHtml = '';
  for (const item of indices) {
    const cls = item.change >= 0 ? 'up' : 'down';
    const sign = item.change >= 0 ? '+' : '';
    indexHtml += `<div class="sh-index-row">
      <span class="sh-price">${item.price.toFixed(2)}</span>
      <span class="sh-change ${cls}">${sign}${item.change.toFixed(2)}%</span>
      <span style="font-size:10px;color:var(--muted);">${esc(item.name)}</span>
    </div>`;
  }
  // 计算支撑/压力位 + 冰点判断
  if (klines.length >= 20) {
    const closes = klines.map(k => k.close);
    const highs  = klines.map(k => k.high);
    const lows   = klines.map(k => k.low);
    const last   = closes[closes.length - 1];
    const ma = (arr, n) => arr.slice(-n).reduce((a,b)=>a+b,0)/n;
    const ma5  = ma(closes, 5);
    const ma10 = ma(closes, 10);
    const ma20 = ma(closes, 20);
    const ma60 = klines.length >= 60 ? ma(closes, 60) : null;
    const sma20 = ma20;
    const std20 = Math.sqrt(closes.slice(-20).reduce((s,v)=>s+(v-sma20)**2,0)/20);
    const boll_upper = sma20 + 2*std20;
    const boll_lower = sma20 - 2*std20;
    const high20 = Math.max(...highs.slice(-20));
    const low20  = Math.min(...lows.slice(-20));
    const levels = [
      { label:'五日均线', val:ma5 }, { label:'十日均线', val:ma10 }, { label:'二十日均线', val:ma20 },
      ...(ma60 ? [{ label:'六十日均线', val:ma60 }] : []),
      { label:'布林上轨', val:boll_upper }, { label:'布林下轨', val:boll_lower },
      { label:'二十日高点', val:high20 }, { label:'二十日低点', val:low20 },
    ].filter(l => Math.abs(l.val - last) / last < 0.15);
    const resists = levels.filter(l => l.val > last).sort((a,b)=>a.val-b.val).slice(0,2);
    const supports = levels.filter(l => l.val <= last).sort((a,b)=>b.val-a.val).slice(0,2);

    // ── 支撑/压力位强度计算（1-10分）──
    // 多维度评分：时间框架权重 + 历史触碰次数 + 多指标共振 + 距离衰减
    function levelStrength(lev, allLevels, last) {
      let score = 0;

      // 1. 时间框架权重（长周期指标更可靠）
      if (lev.label.includes('六十日均线')) score += 4;
      else if (lev.label.includes('二十日均线') || lev.label.includes('二十日高点') || lev.label.includes('二十日低点')) score += 3;
      else if (lev.label.includes('十日均线')) score += 2;
      else if (lev.label.includes('五日均线')) score += 1;
      else if (lev.label.includes('布林')) score += 2; // 布林轨道有统计意义

      // 2. 历史触碰次数（价格在该位置附近±0.8%反弹/受阻的K线数量）
      const touchZone = lev.val * 0.008;
      let touchCount = 0;
      for (let i = 0; i < closes.length - 1; i++) {
        const h = highs[i], l = lows[i];
        if (lev.val > last) {
          // 压力位：价格曾触及但未有效突破（收盘在位置下方）
          if (h >= lev.val - touchZone && closes[i] < lev.val) touchCount++;
        } else {
          // 支撑位：价格曾触及但未有效跌破（收盘在位置上方）
          if (l <= lev.val + touchZone && closes[i] > lev.val) touchCount++;
        }
      }
      if (touchCount >= 4) score += 3;
      else if (touchCount >= 2) score += 2;
      else if (touchCount >= 1) score += 1;

      // 3. 多指标共振（±0.8%内有其他指标重叠，每个+1，最多+2）
      const overlap = allLevels.filter(x => x !== lev && Math.abs(x.val - lev.val) / lev.val < 0.008).length;
      score += Math.min(overlap, 2);

      // 4. 距离衰减（太远的位置实际意义小）
      const dist = Math.abs(lev.val - last) / last;
      if (dist < 0.01) score += 1;       // 1%以内：非常近
      else if (dist > 0.05) score -= 1;  // 5%以外：较远，降权

      return Math.max(1, Math.min(10, score));
    }
    // 强度颜色
    function strengthColor(s) {
      if (s >= 8) return '#ef4444';
      if (s >= 6) return '#f97316';
      if (s >= 4) return '#f59e0b';
      return '#6b7280';
    }
    function strengthDots(s) {
      return '●'.repeat(Math.min(s, 5)) + '○'.repeat(Math.max(0, 5 - Math.min(s, 5)));
    }

    const CN_NUM = ['一','二','三'];
    indexHtml += `<div style="margin-top:6px;font-size:11px;line-height:1.9;">`;
    supports.forEach((s, i) => {
      const str = levelStrength(s, levels, last);
      const sc = strengthColor(str);
      indexHtml += `<div style="color:#4ade80;display:flex;align-items:center;gap:4px;">
        <span>向下第${CN_NUM[i]}支撑位</span>
        <span style="font-weight:600;">${s.val.toFixed(2)}</span>
        <span style="color:var(--muted);font-size:10px;">(${esc(s.label)})</span>
        <span style="color:${sc};font-size:9px;letter-spacing:-1px;" title="强度${str}/10">${strengthDots(str)}</span>
        <span style="color:${sc};font-size:9px;">${str}</span>
      </div>`;
    });
    resists.forEach((r, i) => {
      const str = levelStrength(r, levels, last);
      const sc = strengthColor(str);
      indexHtml += `<div style="color:#f87171;display:flex;align-items:center;gap:4px;">
        <span>附近压力位${CN_NUM[i]}</span>
        <span style="font-weight:600;">${r.val.toFixed(2)}</span>
        <span style="color:var(--muted);font-size:10px;">(${esc(r.label)})</span>
        <span style="color:${sc};font-size:9px;letter-spacing:-1px;" title="强度${str}/10">${strengthDots(str)}</span>
        <span style="color:${sc};font-size:9px;">${str}</span>
      </div>`;
    });
    indexHtml += `</div>`;

    // ── 冰点/情绪高点距离评分 ──
    // 冰点5个维度（越多越接近冰点），情绪高点5个维度（越多越接近高点）
    let icepointScore = 0, hotScore = 0;
    const icepointReasons = [], hotReasons = [];

    // 冰点维度
    if (last <= boll_lower * 1.01) { icepointScore++; icepointReasons.push('触及布林下轨'); }
    if (last <= low20 * 1.02) { icepointScore++; icepointReasons.push('接近20日低点'); }
    if (ma5 < ma10 && ma10 < ma20) { icepointScore++; icepointReasons.push('均线空头排列'); }
    if (closes.length >= 4) {
      const last3 = closes.slice(-4);
      if (last3[1] < last3[0] && last3[2] < last3[1] && last3[3] < last3[2]) {
        icepointScore++; icepointReasons.push('连续3日下跌');
      }
    }
    let rsiVal = 50;
    if (closes.length >= 15) {
      const gains = [], losses = [];
      for (let i = closes.length - 14; i < closes.length; i++) {
        const diff = closes[i] - closes[i-1];
        gains.push(diff > 0 ? diff : 0);
        losses.push(diff < 0 ? -diff : 0);
      }
      const avgGain = gains.reduce((a,b)=>a+b,0)/14;
      const avgLoss = losses.reduce((a,b)=>a+b,0)/14;
      rsiVal = avgLoss === 0 ? 100 : 100 - 100/(1 + avgGain/avgLoss);
      if (rsiVal < 30) { icepointScore++; icepointReasons.push(`RSI超卖(${rsiVal.toFixed(0)})`); }
    }

    // 情绪高点维度（与冰点相反）
    if (last >= boll_upper * 0.99) { hotScore++; hotReasons.push('触及布林上轨'); }
    if (last >= high20 * 0.98) { hotScore++; hotReasons.push('接近20日高点'); }
    if (ma5 > ma10 && ma10 > ma20) { hotScore++; hotReasons.push('均线多头排列'); }
    if (closes.length >= 4) {
      const last3 = closes.slice(-4);
      if (last3[1] > last3[0] && last3[2] > last3[1] && last3[3] > last3[2]) {
        hotScore++; hotReasons.push('连续3日上涨');
      }
    }
    if (rsiVal > 70) { hotScore++; hotReasons.push(`RSI超买(${rsiVal.toFixed(0)})`); }

    // 显示：距冰点还差几分 / 距情绪高点还差几分
    const iceLeft = 5 - icepointScore;
    const hotLeft = 5 - hotScore;
    if (icepointScore >= 3) {
      indexHtml += `<div style="margin-top:5px;padding:4px 8px;background:rgba(99,102,241,0.15);border-left:2px solid #818cf8;border-radius:3px;font-size:10px;color:#a5b4fc;">
        ❄️ 冰点信号 ${icepointScore}/5（还差${iceLeft}分满冰点）：${icepointReasons.join('、')}
      </div>`;
    } else if (hotScore >= 3) {
      indexHtml += `<div style="margin-top:5px;padding:4px 8px;background:rgba(239,68,68,0.12);border-left:2px solid #ef4444;border-radius:3px;font-size:10px;color:#fca5a5;">
        🔥 情绪高点 ${hotScore}/5（还差${hotLeft}分满高点）：${hotReasons.join('、')}
      </div>`;
    } else {
      // 显示当前更接近哪个方向
      if (icepointScore >= hotScore) {
        indexHtml += `<div style="margin-top:5px;font-size:10px;color:var(--muted);">❄️ 距冰点还差 ${iceLeft} 分（当前 ${icepointScore}/5）：${icepointReasons.join('、') || '无明显信号'}</div>`;
      } else {
        indexHtml += `<div style="margin-top:5px;font-size:10px;color:var(--muted);">🔥 距情绪高点还差 ${hotLeft} 分（当前 ${hotScore}/5）：${hotReasons.join('、') || '无明显信号'}</div>`;
      }
    }
  }
  const elIdx = document.getElementById('sent-index');
  if (elIdx) elIdx.innerHTML = indexHtml || '<div style="color:var(--muted);font-size:10px;">暂无数据</div>';

  // 2. 市场宽度
  const b = data.breadth || {};
  if (b.total) {
    const up = b.up||0, down = b.down||0, flat = b.flat||0;
    const limitUp = b.limit_up||0, limitDown = b.limit_down||0;
    const total = b.total||1;
    const upPct = (up/total*100).toFixed(0);
    const downPct = (down/total*100).toFixed(0);
    const limitRatio = (limitUp+limitDown) > 0 ? limitUp/(limitUp+limitDown)*100 : 0;
    const score = Math.min(100, up/total*100);
    const meterColor = score>60?'#ef4444':score>40?'#f59e0b':'#22c55e';
    const elB = document.getElementById('sent-breadth');
    if (elB) elB.innerHTML = `
      <div class="breadth-row">
        <span class="breadth-num up">↑${up}</span>
        <div class="breadth-bar">
          <div class="breadth-fill-up" style="width:${upPct}%"></div>
          <div class="breadth-fill-down" style="width:${downPct}%"></div>
        </div>
        <span class="breadth-num down">↓${down}</span>
      </div>
      <div class="limit-row">
        <span class="limit-badge up">🔴 涨停 ${limitUp}</span>
        <span class="limit-badge down">🟢 跌停 ${limitDown}</span>
        <span style="font-size:10px;color:var(--muted);margin-left:auto;">平盘 ${flat}</span>
      </div>
      <div style="margin-top:6px;">
        <div class="sentiment-meter">
          <span class="meter-label">市场情绪</span>
          <div class="meter-bar"><div class="meter-fill" style="width:${score.toFixed(0)}%;background:${meterColor}"></div></div>
          <span class="meter-val" style="color:${meterColor}">${score.toFixed(0)}</span>
        </div>
        <div class="sentiment-meter">
          <span class="meter-label">涨停比</span>
          <div class="meter-bar"><div class="meter-fill" style="width:${limitRatio.toFixed(0)}%;background:#ef4444"></div></div>
          <span class="meter-val" style="color:#fca5a5">${limitUp}/${limitUp+limitDown}</span>
        </div>
      </div>`;
  }

  // 3. 板块排名（前7，点击展开前5只股）
  const sectors = (data.sectors || []).slice(0, 7);
  const elS = document.getElementById('sent-sectors');
  if (elS) {
    if (!sectors.length) {
      elS.innerHTML = '<div style="color:var(--muted);font-size:10px;">暂无数据</div>';
    } else {
      elS.innerHTML = sectors.map((s, i) => {
        const isLimit = s.isLimitCount;
        const cls = isLimit ? 'up' : (s.change >= 0 ? 'up' : 'down');
        const changeText = isLimit
          ? `涨停${s.change}只`
          : `${s.change >= 0 ? '+' : ''}${s.change.toFixed(2)}%`;
        const sectorKey = `sector_${i}`;
        return `<div class="sector-row" data-sector-key="${sectorKey}" data-sector-name="${esc(s.name)}" style="cursor:pointer;user-select:none;">
          <span class="sector-rank">${i+1}</span>
          <span class="sector-name">${esc(s.name)}</span>
          <span style="color:var(--muted);font-size:10px;margin-left:2px;">${s.leader ? esc(s.leader) : ''}</span>
          <span class="sector-change ${cls}" style="margin-left:auto;">${changeText}</span>
          <span class="sector-expand-arrow" style="color:var(--muted);font-size:10px;margin-left:4px;">▶</span>
        </div>
        <div class="sector-stocks" id="stocks_${sectorKey}" style="display:none;padding:2px 0 4px 16px;"></div>`;
      }).join('');

      // 绑定点击展开事件
      elS.querySelectorAll('.sector-row').forEach(row => {
        row.addEventListener('click', () => {
          const key = row.dataset.sectorKey;
          const name = row.dataset.sectorName;
          const stocksDiv = document.getElementById(`stocks_${key}`);
          const arrow = row.querySelector('.sector-expand-arrow');
          if (!stocksDiv) return;
          const isOpen = stocksDiv.style.display !== 'none';
          if (isOpen) {
            stocksDiv.style.display = 'none';
            if (arrow) arrow.textContent = '▶';
          } else {
            stocksDiv.style.display = 'block';
            if (arrow) arrow.textContent = '▼';
            // 如果已有内容则不重复加载
            if (stocksDiv.innerHTML) return;
            stocksDiv.innerHTML = '<div style="color:var(--muted);font-size:10px;">加载中…</div>';
            // 从后端请求该板块前5只股票
            fetchSectorTopStocks(name, stocksDiv);
          }
        });
      });
    }
  }

  // 4. 历史板块
  const history = data.history || [];
  const elH = document.getElementById('sent-history');
  if (elH) {
    if (!history.length) {
      elH.innerHTML = '<div style="color:var(--muted);font-size:10px;">历史数据暂不可用</div>';
    } else {
      elH.innerHTML = history.map(day => `
        <div class="history-day">
          <div class="history-day-label">${day.date}</div>
          <div class="history-sectors">
            ${day.top5.map((s,i) => `<span class="history-sector-tag rank${i+1}">${esc(s.name)} ${s.change>=0?'+':''}${s.change.toFixed(2)}%</span>`).join('')}
          </div>
        </div>`).join('');
    }
  }
}

/* 通过 WS 请求板块前5只股票 */
function fetchSectorTopStocks(sectorName, stocksDiv) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: 'get_sector_stocks', sector_name: sectorName }));
  } else {
    if (stocksDiv) stocksDiv.innerHTML = '<div style="color:var(--muted);font-size:10px;">未连接引擎</div>';
  }
}

/* 降级：WS 未连接时直接从东方财富拉取（仅指数和板块，不含全市场统计） */
async function fetchSentimentDataFrontend() {
  try {
    const url = 'https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fields=f12,f14,f2,f3&secids=1.000001,0.399001,1.000300';
    const resp = await fetch(url);
    const json = await resp.json();
    const diff = json?.data?.diff || [];
    let html = '';
    for (const item of diff) {
      const price = item.f2; const chg = item.f3;
      const cls = chg>=0?'up':'down'; const sign = chg>=0?'+':'';
      html += `<div class="sh-index-row"><span class="sh-price">${price}</span><span class="sh-change ${cls}">${sign}${chg}%</span><span style="font-size:10px;color:var(--muted);">${esc(item.f14)}</span></div>`;
    }
    const el = document.getElementById('sent-index');
    if (el) el.innerHTML = html || '<div style="color:var(--muted);font-size:10px;">请连接引擎获取完整数据</div>';
  } catch(e) {}
}

function bindSettingsEvents() {
  document.getElementById('settingsBackBtn')?.addEventListener('click', () => {
    settingsOpen = false;
    settingsPanel.classList.remove('active');
  });
  settingsPanel.querySelectorAll('.scheme-save-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      saveSchemes();
      btn.textContent = '✅ 已保存';
      btn.style.background = 'rgba(34,197,94,0.2)';
      setTimeout(() => { btn.textContent = '💾 保存'; btn.style.background = 'rgba(34,197,94,0.1)'; }, 1200);
    });
  });
  settingsPanel.querySelectorAll('.scheme-name-input').forEach(inp => {
    inp.addEventListener('change', () => {
      const sc = schemes.find(x => x.id === inp.dataset.id);
      if (sc) { sc.name = inp.value.trim() || '未命名'; saveSchemes(); renderSchemeBar(); }
    });
  });
  settingsPanel.querySelectorAll('.scheme-delete-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (schemes.length <= 1) return;
      const idx = schemes.findIndex(x => x.id === btn.dataset.id);
      if (idx >= 0) schemes.splice(idx, 1);
      saveSchemes(); renderSettings(); renderSchemeBar();
    });
  });
  settingsPanel.querySelectorAll('.cond-check').forEach(cb => {
    cb.addEventListener('change', () => {
      const sc = schemes.find(x => x.id === cb.dataset.scheme);
      if (sc && sc.conditions[cb.dataset.key]) { sc.conditions[cb.dataset.key].enabled = cb.checked; saveSchemes(); }
    });
  });
  settingsPanel.querySelectorAll('.cond-input').forEach(inp => {
    inp.addEventListener('change', () => {
      const sc = schemes.find(x => x.id === inp.dataset.scheme);
      if (sc && sc.conditions[inp.dataset.key]) {
        const val = inp.tagName === 'SELECT' ? inp.value : (parseFloat(inp.value) || 0);
        sc.conditions[inp.dataset.key][inp.dataset.field] = val;
        saveSchemes();
      }
    });
  });
  // ── 价格组合比较：动态行事件 ──
  settingsPanel.querySelectorAll('.pc-add-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const sc = schemes.find(x => x.id === btn.dataset.scheme);
      if (!sc) return;
      if (!sc.conditions.priceCompare) sc.conditions.priceCompare = { enabled: false, rules: [] };
      if (!sc.conditions.priceCompare.rules) sc.conditions.priceCompare.rules = [{ dayL:1, fieldL:'close', op:'gt', dayR:2, fieldR:'close' }];
      sc.conditions.priceCompare.rules.push({ dayL:1, fieldL:'close', op:'gt', dayR:2, fieldR:'close' });
      saveSchemes(); renderSettings();
    });
  });
  settingsPanel.querySelectorAll('.pc-del-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const sc = schemes.find(x => x.id === btn.dataset.scheme);
      if (!sc || !sc.conditions.priceCompare || !sc.conditions.priceCompare.rules) return;
      const ri = parseInt(btn.dataset.ri);
      sc.conditions.priceCompare.rules.splice(ri, 1);
      saveSchemes(); renderSettings();
    });
  });
  settingsPanel.querySelectorAll('.pc-rule .pc-field').forEach(inp => {
    inp.addEventListener('change', () => {
      const row = inp.closest('.pc-rule');
      if (!row) return;
      const sc = schemes.find(x => x.id === row.dataset.scheme);
      if (!sc || !sc.conditions.priceCompare || !sc.conditions.priceCompare.rules) return;
      const ri = parseInt(row.dataset.ri);
      const rule = sc.conditions.priceCompare.rules[ri];
      if (!rule) return;
      const f = inp.dataset.f;
      if (f === 'multiplier') {
        const v = parseFloat(inp.value);
        if (isNaN(v) || inp.value.trim() === '') { delete rule.multiplier; } else { rule.multiplier = v; }
      } else {
        rule[f] = inp.tagName === 'SELECT' ? inp.value : (parseInt(inp.value) || 1);
      }
      saveSchemes();
    });
  });

  // ── 成交额组合比较：动态行事件 ──
  settingsPanel.querySelectorAll('.ac-add-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const sc = schemes.find(x => x.id === btn.dataset.scheme);
      if (!sc) return;
      if (!sc.conditions.amountCompare) sc.conditions.amountCompare = { enabled: false, rules: [] };
      if (!sc.conditions.amountCompare.rules) sc.conditions.amountCompare.rules = [{ dayL:1, op:'gt', dayR:2 }];
      sc.conditions.amountCompare.rules.push({ dayL:1, op:'gt', dayR:2 });
      saveSchemes(); renderSettings();
    });
  });
  settingsPanel.querySelectorAll('.ac-del-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const sc = schemes.find(x => x.id === btn.dataset.scheme);
      if (!sc || !sc.conditions.amountCompare || !sc.conditions.amountCompare.rules) return;
      const ri = parseInt(btn.dataset.ri);
      sc.conditions.amountCompare.rules.splice(ri, 1);
      saveSchemes(); renderSettings();
    });
  });
  settingsPanel.querySelectorAll('.ac-rule .ac-field').forEach(inp => {
    inp.addEventListener('change', () => {
      const row = inp.closest('.ac-rule');
      if (!row) return;
      const sc = schemes.find(x => x.id === row.dataset.scheme);
      if (!sc || !sc.conditions.amountCompare || !sc.conditions.amountCompare.rules) return;
      const ri = parseInt(row.dataset.ri);
      const rule = sc.conditions.amountCompare.rules[ri];
      if (!rule) return;
      const f = inp.dataset.f;
      if (f === 'multiplier') {
        const v = parseFloat(inp.value);
        if (isNaN(v) || inp.value.trim() === '') { delete rule.multiplier; } else { rule.multiplier = v; }
      } else {
        rule[f] = inp.tagName === 'SELECT' ? inp.value : (parseInt(inp.value) || 1);
      }
      saveSchemes();
    });
  });

  document.getElementById('addSchemeBtn')?.addEventListener('click', () => {
    schemes.push({ id: 'scheme_' + Date.now(), name: `方案${schemes.length + 1}`, enabled: true,
      conditions: { marketCap:{enabled:false,min:20,max:200}, bigOrder:{enabled:false,ratio:0.1}, amountHigh:{enabled:false,days:5}, amountLow:{enabled:false,days:5}, limitUp:{enabled:false}, limitDown:{enabled:false}, shortRise:{enabled:false,seconds:60,percent:3}, breakMinMA:{enabled:false,minutes:5}, breakDayMA:{enabled:false,period:5}, breakGolden:{enabled:false,days:20,ratio:0.382}, amountMultiple:{enabled:false,multiple:2}, volumeRatio:{enabled:false,min:2}, bollingerUp:{enabled:false,band:'upper',period:'20d'}, bollingerDown:{enabled:false,band:'lower',period:'20d'}, cupHandle:{enabled:false,days:20,dayA:5,dayB:10,minPct:10,maxPct:30}, priceCompare:{enabled:false,rules:[{dayL:1,fieldL:'close',op:'gt',dayR:2,fieldR:'close'}]}, amountCompare:{enabled:false,rules:[{dayL:1,op:'gt',dayR:2}]} }
    });
    saveSchemes(); renderSettings(); renderSchemeBar();
  });
}