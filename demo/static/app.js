>
const $ = s => document.querySelector(s);
const pct = x => (x*100).toFixed(0) + '%';
const wrColor = w => w>=0.5?'var(--ok)':w>=0.3?'var(--warn)':'var(--bad)';
const realColor = w => w>=0.5?'#4ade80':w>=0.3?'#facc15':'#fb7185';
// 胜诉率单元格：decided=0 表示该维度尚无已判定案件（全是「待分析」），
// 不能直接显示 0%——那会读成「这个平台/地区全输」，实际只是还没判定。
const winRateCell = x => (x && (x.decided===undefined || x.decided>0)) ? pct(x.win_rate) : '— 待分析';
let _ins = null;  // 最近一次 insights 响应，供供应商下钻本地计算

// ---- 数据源开关（演示数据 / 实际数据）----
// 当前数据源，持久化到 localStorage，刷新页面不丢失；所有数据接口经 apiFetch 附带 ?source=
let CURRENT_SOURCE = (localStorage.getItem('rg_source') || 'demo');
async function setSource(s){
  CURRENT_SOURCE = (s==='real') ? 'real' : 'demo';
  localStorage.setItem('rg_source', CURRENT_SOURCE);
  document.querySelectorAll('#srcToggle .src-btn').forEach(b=>b.classList.toggle('active', b.dataset.src===CURRENT_SOURCE));
  updateAuthBtnVisibility(); // demo 时隐藏登录按钮，real 时显示
  $('#entryTarget').textContent = '将写入：' + (CURRENT_SOURCE==='real'?'实际数据':'演示数据');
  const banner = $('#entryBanner');
  if(CURRENT_SOURCE==='real'){
    banner.querySelector('.sb-body').textContent='⚠ 当前为「实际数据」：看板与录入均作用于真实案件库（cases_real.db），与演示数据物理隔离。';
    banner.classList.add('show');
    banner.classList.remove('hidden');
  } else {
    banner.classList.remove('show');
  }
  // 切换数据源：先看板（写入 _ins）再填筛选下拉，避免用旧源数据填充；列表也等看板就绪
  await loadInsights();
  if(typeof populateFilters==='function') populateFilters();
  await loadEntryList();
}
// 统一给接口地址附加当前数据源（?source=）
function apiUrl(path){
  const u = new URL(path, location.href);
  u.searchParams.set('source', CURRENT_SOURCE);
  return u.pathname + u.search;
}
function apiFetch(path, opts){
  opts = opts || {};
  opts.headers = Object.assign({}, opts.headers || {});
  const tok = localStorage.getItem('rg_token');
  if(tok) opts.headers['Authorization'] = 'Bearer ' + tok;
  return fetch(apiUrl(path), opts);
}

// HTML 转义（P1-3）：所有动态文本拼进 innerHTML 前统一转义，杜绝 live 模型自由文本引发的 XSS
function esc(s){
  return (s==null?'':String(s)).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// 复制文本：优先 Clipboard API（需安全上下文 https / localhost），
// 非安全上下文（如 http 直连）静默失败时回退 execCommand，保证演示现场可用（B-前端 P1）。
async function copyText(text){
  try{
    if(navigator.clipboard && window.isSecureContext){
      await navigator.clipboard.writeText(text);
      return true;
    }
  }catch(_){ /* 落到下方回退 */ }
  try{
    const ta=document.createElement('textarea');
    ta.value=text; ta.style.position='fixed'; ta.style.opacity='0';
    document.body.appendChild(ta); ta.focus(); ta.select();
    const ok=document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  }catch(_){ return false; }
}

// 同款一致性阈值（P2-4）：默认兜底 0.82，初始化时从 /api/config 拉取单一来源值
let SAME_ITEM_THRESHOLD = 0.82;

// 标签页切换（组件切换，不整页滑动，带动画）
function switchTab(name){
  document.querySelectorAll('.tabpane').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tabs button').forEach(b=>{
    const on=b.dataset.tab===name;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', on?'true':'false');
  });
  const target=document.getElementById('tab-'+name);
  if(target){
    target.classList.add('active');
    const board=target.querySelector('.board');
    if(board){board.classList.remove('animated'); void board.offsetWidth; board.classList.add('animated');}
    if(name==='supplier' && _ins){renderSuppliers(_ins);}
  }
}
document.querySelectorAll('.tabs button').forEach(b=>b.addEventListener('click',()=>switchTab(b.dataset.tab)));

// 评委体验指引横幅（P0-2）：可关闭（仅会话内，刷新即重现），步骤 2 可点击跳转
(function initJudgeGuide(){
  const guide=document.getElementById('judgeGuide');
  if(!guide) return;
  const close=document.getElementById('jgClose');
  if(close) close.addEventListener('click',()=>{
    guide.style.display='none';
    // 不写 localStorage，刷新页面即重新显示
  });
  guide.querySelectorAll('.jg-step[data-go]').forEach(s=>s.addEventListener('click',()=>switchTab(s.dataset.go)));
})();

// 数据源提示浮动面板关闭（仅会话内，刷新即重现）
(function initSrcBanner(){
  const banner=document.getElementById('entryBanner');
  if(!banner) return;
  const close=document.getElementById('sbClose');
  if(close) close.addEventListener('click',()=>{
    banner.classList.add('hidden');
    banner.classList.remove('show');
  });
})();


// 胜诉率环形图（带动画）
function renderDonut(svg, rate){
  const R=38, cx=46, cy=46, c=2*Math.PI*R;
  const v=Math.max(0,Math.min(1,rate||0));
  const col=realColor(v);
  const dash=`${(v*c).toFixed(1)} ${c.toFixed(1)}`;
  svg.style.setProperty('--dash-full', c.toFixed(1));
  svg.innerHTML=`<circle cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke="var(--border)" stroke-width="9"/>`
    +`<circle class="donut-ring" cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke="${col}" stroke-width="9" stroke-linecap="round" `
    +`stroke-dasharray="${dash}" stroke-dashoffset="${c.toFixed(1)}" transform="rotate(-90 ${cx} ${cy})"/>`;
  // 触发下一帧动画
  requestAnimationFrame(()=>{
    const ring=svg.querySelector('.donut-ring');
    if(ring){ring.style.transition='stroke-dashoffset .9s cubic-bezier(.2,.8,.2,1)'; ring.style.strokeDashoffset='0';}
  });
}

// 数字滚动动画（KPI 用）
function animateValue(el, target, fmt, duration=700){
  const start=performance.now();
  const from=parseFloat(el.dataset.value||0)||0;
  function step(t){
    const p=Math.min(1,(t-start)/duration);
    const ease=1-Math.pow(1-p,3);
    const cur=from+(target-from)*ease;
    el.textContent=fmt(cur);
    if(p<1) requestAnimationFrame(step);
    else {el.textContent=fmt(target); el.dataset.value=target;}
  }
  requestAnimationFrame(step);
}

// 通用横向条形图
// opts.absolute=true 时直接把 o.v 当 0-100 的百分比宽度（用于平台维权难度等本身已是比率的数据）
function renderBarh(el, items, opts={}){
  el.innerHTML='';
  if(!items.length){el.innerHTML='<span class="note">暂无数据。</span>';return;}
  const absolute=!!opts.absolute;
  // 非绝对模式：每个图表独立按自己的最大值归一化，确保同一张卡片内部比例正确
  const max=absolute?100:Math.max(1,...items.map(o=>o.v));
  items.forEach(o=>{
    const wpct=absolute
      ?Math.max(0,Math.min(100,Math.round(Number(o.v)||0)))
      :Math.max(1,Math.round(o.v/max*100));
    const div=document.createElement('div'); div.className='barh';
    div.innerHTML=`<span class="lab" title="${esc(o.label)}">${esc(o.label)}</span>`
      +`<span class="track"><span class="fill" style="width:${wpct}%;background:${o.color||'var(--acc)'}" data-pct="${wpct}%" title="${esc(o.label)}：${esc(o.text)}（占本图表 ${wpct}%）"></span></span>`
      +`<span class="val">${esc(o.text)}</span>`;
    el.appendChild(div);
  });
}

// 平台 × 供应商 交叉热力
function renderMatrix(el, rows){
  el.innerHTML='';
  if(!rows.length){el.innerHTML='<span class="note">暂无交叉数据。</span>';return;}
  const plats=[...new Set(rows.map(r=>r.platform))];
  const sups=[...new Set(rows.map(r=>r.supplier))];
  const map={}; rows.forEach(r=>{map[r.platform+'|'+r.supplier]=r;});
  let html='<tr><th>平台 ＼ 供应商</th>'+sups.map(s=>`<th>${esc(s)}</th>`).join('')+'</tr>';
  plats.forEach(p=>{
    html+=`<tr><td class="pl">${esc(p)}</td>`;
    sups.forEach(s=>{
      const r=map[p+'|'+s];
      if(!r){html+='<td>-</td>';return;}
      const rc=realColor(r.win_rate);
      const rgba=rc==='#34d399'?'52,211,153':rc==='#fbbf24'?'251,191,36':'248,113,113';
      html+=`<td style="background:rgba(${rgba},.18);color:${rc};font-weight:600">${winRateCell(r)}`
        +`<br><span style="font-size:10px;color:var(--txt3)">${r.cases}笔</span></td>`;
    });
    html+='</tr>';
  });
  el.innerHTML=`<table class="matrix">${html}</table>`;
}

// ===================== B组：时间序列趋势线 =====================
function trendLabel(t){
  return t==='up'?'上行 ↑':t==='down'?'下行 ↓':'平稳 →';
}

function renderTrendLine(el, ts, forecast){
  el.innerHTML='';
  if(!ts || !ts.length){ el.innerHTML='<span class="note">暂无时间序列数据。</span>'; return; }
  const fpts = (forecast && forecast.points) || [];
  const hist = ts.map(x=>({label:x.month.slice(2), v:x.cases}));
  const fc = fpts.map(x=>({label:x.month.slice(2), v:x.cases}));
  const all = hist.concat(fc);
  const W=580, H=210, padL=34, padB=28, padT=14, padR=12;
  const maxV = Math.max(1, ...all.map(p=>p.v));
  const n = all.length;
  const xStep = (W-padL-padR)/Math.max(1,(n-1));
  const Y = v => (H-padB - (v/maxV)*(H-padB-padT)).toFixed(1);
  const X = i => (padL + i*xStep).toFixed(1);
  // 历史实线 + 预测虚线（从最后一个历史点续接）
  let histPath='', fPath='';
  all.forEach((p,i)=>{
    const cmd = (i===0)?'M':(p.f?'L':(histPath? ' L':''));
    if(!p.f){ histPath += (histPath? ' ':'') + cmd + X(i)+',' + Y(p.v); }
  });
  if(fc.length){
    const hLast = hist.length-1;
    fPath = `M${X(hLast)},${Y(hist[hLast].v)}`;
    fc.forEach((p,i)=> fPath += ` L${X(hist.length+i)},${Y(p.v)}`);
  }
  // 网格 + 标签
  let grid='', xlab='';
  for(let g=0; g<=4; g++){
    const gy=(padT + (H-padB-padT)*g/4).toFixed(1);
    const gv=Math.round(maxV*(1-g/4));
    grid+=`<line x1="${padL}" y1="${gy}" x2="${W-padR}" y2="${gy}" stroke="#1e293b" stroke-width="1"></line>`;
    grid+=`<text x="${padL-5}" y="${(+gy+3).toFixed(1)}" fill="#64748b" font-size="9" text-anchor="end">${gv}</text>`;
  }
  all.forEach((p,i)=>{
    xlab+=`<text x="${X(i)}" y="${H-10}" fill="${p.f?'#fbbf24':'#94a3b8'}" font-size="9" text-anchor="middle">${esc(p.label)}</text>`;
  });
  let dots='';
  all.forEach((p,i)=>{ dots+=`<circle cx="${X(i)}" cy="${Y(p.v)}" r="2.6" fill="${p.f?'#fbbf24':'#22d3ee'}"></circle>`; });
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet" style="display:block">
    ${grid}${histPath?`<path d="${histPath}" fill="none" stroke="#22d3ee" stroke-width="2.2"></path>`:''}
    ${fPath?`<path d="${fPath}" fill="none" stroke="#fbbf24" stroke-width="2.2" stroke-dasharray="5 4"></path>`:''}
    ${dots}${xlab}</svg>`;
}

// ===================== B组：预测预警 =====================
function renderForecast(kpiEl, listEl, alertEl, forecast, alerts){
  kpiEl.innerHTML='';
  if(!forecast || !forecast.available){
    kpiEl.innerHTML='<span class="note">历史不足 3 个月，暂无法预测（多录入几个月的带日期案件即可）。</span>';
    listEl.innerHTML=''; alertEl.innerHTML=''; return;
  }
  const trendColor = forecast.trend==='up'?'var(--bad)':forecast.trend==='down'?'var(--ok)':'var(--warn)';
  kpiEl.innerHTML =
    `<div class="kv"><span>趋势</span><b style="color:${trendColor}">${trendLabel(forecast.trend)}</b></div>`
    +`<div class="kv"><span>下月预计退货</span><b>${forecast.next_month_cases} 笔</b></div>`
    +`<div class="kv"><span>近3月均值</span><b>${forecast.recent_avg} 笔</b></div>`
    +`<div class="kv"><span>下月预计退款</span><b>¥${Number(forecast.next_month_refund||0).toLocaleString('zh-CN',{maximumFractionDigits:0})}</b></div>`;
  listEl.innerHTML='';
  (forecast.points||[]).forEach(p=>{
    const div=document.createElement('div'); div.style.cssText='background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:8px 10px;margin-top:6px;font-size:13px;display:flex;justify-content:space-between';
    div.innerHTML=`<span style="color:var(--txt)">${esc(p.month)}</span><span style="color:var(--txt)">预计 <b>${p.cases}</b> 笔 · ¥${Number(p.refund).toLocaleString('zh-CN',{maximumFractionDigits:0})}</span>`;
    listEl.appendChild(div);
  });
  alertEl.innerHTML='';
  (alerts||[]).forEach(a=>{
    const div=document.createElement('div'); div.className='alert'; div.style.marginTop='8px';
    div.textContent='⚠ '+a.reason;
    alertEl.appendChild(div);
  });
}

// ===================== B组：选品避坑闭环 =====================
function renderSourcingLoop(el, items){
  el.innerHTML='';
  if(!items || !items.length){ el.innerHTML='<span class="note">暂无明显负面信号，继续保持。</span>'; return; }
  const sevColor={'高':'var(--bad)','中':'var(--warn)','低':'var(--ok)'};
  items.forEach(it=>{
    const div=document.createElement('div');
    div.style.cssText='border:1px solid var(--border);border-left:4px solid '+sevColor[it.severity||'低']+';border-radius:8px;padding:9px 11px;margin-top:8px;background:var(--bg2)';
    div.innerHTML=`<div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
        <b style="font-size:13px;color:var(--txt)">${esc(it.action)}</b>
        <span class="pill" style="background:${sevColor[it.severity||'低']}">${esc(it.severity)}</span></div>
      <div style="font-size:12px;color:var(--txt2);margin-top:4px">对象：<b style="color:var(--txt)">${esc(it.target)}</b></div>
      <div style="font-size:12px;color:var(--txt3);margin-top:2px">${esc(it.reason)}</div>`;
    el.appendChild(div);
  });
}

// 供应商透视：增强评分榜渲染（扩展 C）
const SUP_PALETTE=['#f87171','#fbbf24','#38bdf8','#a78bfa','#34d399','#fb923c','#e879f9','#22d3ee'];
function renderSuppliers(d){
  const el=$('#supList'); el.innerHTML='';
  const sc=d.supplier_scorecard||[];
  if(!sc.length){el.innerHTML='<span class="note">暂无供应商数据。</span>';return;}
  sc.forEach(s=>{
    const col=s.level==='高风险'?'var(--bad)':s.level==='待改进'?'var(--warn)':s.level==='合格'?'var(--acc)':'var(--ok)';
    const dd=s.defect_dist||{};
    const total=Object.values(dd).reduce((a,b)=>a+b,0)||1;
    let i=0;
    const segs=Object.entries(dd).sort((a,b)=>b[1]-a[1]).map(([k,v])=>{
      const c=SUP_PALETTE[i++%SUP_PALETTE.length];
      // SEC-P0: k 是缺陷标签，源自用户导入的 CSV/数据集，未转义即构成存储型 XSS
      // （title 属性可被 " onmouseover=... 提前闭合利用）。同数据在下方下钻视图已正确 esc。
      return `<span style="width:${Math.round(v/total*100)}%;background:${c}" title="${esc(k)}: ${esc(v)}"></span>`;
    }).join('');
    const div=document.createElement('div'); div.className='sup-card'; div.style.borderLeftColor=col;
    div.innerHTML=`<div class="sup-head"><div><b style="font-size:15px">${esc(s.supplier)}</b> <span class="note">${esc(s.name)}</span></div>`
      +`<span class="pill" style="background:${col}">${s.level} · 质量分 ${s.quality_score}</span></div>`
      +`<div class="sup-metrics">`
      +`<div><span class="note">案件</span><b>${s.cases}</b></div>`
      +`<div><span class="note">胜诉率</span><b style="color:${wrColor(s.win_rate)}">${pct(s.win_rate)}</b></div>`
      +`<div><span class="note">缺陷率</span><b style="color:var(--bad)">${pct(s.defect_rate)}</b></div>`
      +`<div><span class="note">平均退款</span><b>¥${s.avg_refund}</b></div>`
      +`<div><span class="note">SKU 数</span><b>${s.sku_count}</b></div>`
      +`<div><span class="note">平台覆盖</span><b>${s.platform_count}</b></div>`
      +`</div>`
      +`<div class="defbar">${segs}</div>`
      +`<div class="note" style="margin-top:5px">点击查看 SKU 清单 / 平台分布 / 缺陷明细</div>`;
    div.addEventListener('click',()=>openSupplier(s.supplier));
    el.appendChild(div);
  });
}

// 供应商下钻：从已加载洞察本地计算（无额外接口）
function openSupplier(name){
  const d=_ins; if(!d) return;
  const sc=(d.supplier_scorecard||[]).find(s=>s.supplier===name)||{};
  const skus=(d.sku_ranking||[]).filter(r=>r.supplier===name).sort((a,b)=>b.refund-a.refund).slice(0,30);
  const plats=(d.platform_supplier_matrix||[]).filter(r=>r.supplier===name).sort((a,b)=>b.cases-a.cases);
  const platsHtml=plats.map(p=>`<tr><td>${esc(p.platform)}</td><td>${p.cases}</td><td style="color:${wrColor(p.win_rate)};font-weight:600">${pct(p.win_rate)}</td><td>¥${p.refund}</td></tr>`).join('');
  const skuRows=skus.map(r=>`<tr><td>${esc(r.sku)}</td><td>${esc(r.category)}</td><td>${r.cases}</td><td>¥${r.refund}</td><td style="color:${wrColor(r.win_rate)}">${pct(r.win_rate)}</td><td>${esc(r.top_defect)}</td></tr>`).join('');
  const dd=sc.defect_dist||{};
  const dmax=Math.max(1,...Object.values(dd));
  const defectsHtml=Object.entries(dd).sort((a,b)=>b[1]-a[1]).map(([k,v])=>{const wp=Math.round(v/dmax*100);return`<div class="barh"><span class="lab">${esc(k)}</span><span class="track"><span class="fill" style="width:${wp}%;background:var(--warn)"></span></span><span class="val">${v}</span></div>`}).join('');
  $('#ovTitle').textContent='供应商透视 · '+name;
  $('#ovBody').innerHTML=`<div class="sup-metrics" style="margin-bottom:10px">`
    +`<div><span class="note">质量分</span><b>${sc.quality_score??'-'}</b></div>`
    +`<div><span class="note">等级</span><b>${sc.level??'-'}</b></div>`
    +`<div><span class="note">案件</span><b>${sc.cases??'-'}</b></div>`
    +`<div><span class="note">胜诉率</span><b style="color:${wrColor(sc.win_rate||0)}">${pct(sc.win_rate||0)}</b></div>`
    +`<div><span class="note">缺陷率</span><b style="color:var(--bad)">${pct(sc.defect_rate||0)}</b></div>`
    +`<div><span class="note">平均退款</span><b>¥${sc.avg_refund??'-'}</b></div>`
    +`<div><span class="note">SKU 数</span><b>${sc.sku_count??'-'}</b></div>`
    +`<div><span class="note">平台覆盖</span><b>${sc.platform_count??'-'}</b></div>`
    +`</div>`
    +`<h4 style="margin:10px 0 4px;font-size:13px;color:var(--txt2)">平台分布（胜诉率）</h4>`
    +`<table><thead><tr><th>平台</th><th>案件</th><th>胜诉率</th><th>退款</th></tr></thead><tbody>${platsHtml||'<tr><td colspan="4">无</td></tr>'}</tbody></table>`
    +`<h4 style="margin:12px 0 4px;font-size:13px;color:var(--txt2)">缺陷构成</h4>`
    +`${defectsHtml||'<span class="note">无明显缺陷</span>'}`
    +`<h4 style="margin:12px 0 4px;font-size:13px;color:var(--txt2)">SKU 清单（按退款排序，最多 30）</h4>`
    +`<div class="scrollx"><table><thead><tr><th>SKU</th><th>品类</th><th>案件</th><th>退款</th><th>胜诉率</th><th>头号问题</th></tr></thead><tbody>${skuRows||'<tr><td colspan="6">无</td></tr>'}</tbody></table></div>`
    +`<div class="annot-note" style="margin-top:10px">※ 仅基于已沉淀退货数据的客观统计，不构成对供应商的最终裁决结论。</div>`;
  $('#overlay').classList.add('show');
}
function closeOverlay(){$('#overlay').classList.remove('show');}

// ============ 洞察报告导出（演示/交付：一键出报告，服务端生成 PDF 下载 / 复制文本） ============
function reportText(d){
  const L=[];
  L.push('ReturnGuard 选品·品控洞察报告');
  const cat=$('#catSel').value||'', plat=$('#platSel').value||'';
  const scope=(cat?cat+' / ':'')+(plat||'全平台');
  L.push(`生成时间：${new Date().toLocaleString('zh-CN')}｜数据源：${CURRENT_SOURCE==='real'?'实际数据':'演示数据'}｜筛选：${scope}`);
  L.push('');
  L.push(`【核心指标】已分析退货 ${d.total_cases} 笔｜累计退款 ¥${Number(d.total_refund||0).toLocaleString('zh-CN',{maximumFractionDigits:2})}｜维权胜诉率 ${pct(d.win_rate||0)}｜货不对板嫌疑率 ${pct(d.avg_dispute_rate||0)}`);
  L.push(`【退货成本】物流成本（估算）¥${Number(d.logistics_cost||0).toLocaleString('zh-CN',{maximumFractionDigits:0})}｜退货总成本（退款+物流）¥${Number(d.total_return_cost||0).toLocaleString('zh-CN',{maximumFractionDigits:0})}`);
  L.push('');
  L.push(`【根因分析】${d.root_cause||'暂无足够数据'}`);
  if(d.report) L.push(`【洞察报告】${d.report}`);
  L.push('');
  L.push('【选品 / 品控建议】');
  (d.recommendations||[]).forEach((r,i)=>L.push(`${i+1}. ${r}`));
  const blacks=(d.supplier_blacklist&&d.supplier_blacklist.length)?d.supplier_blacklist
    :(d.supplier_scorecard||[]).filter(s=>s.level==='高风险'||s.quality_score<50).slice(0,5);
  if(blacks.length){
    L.push(''); L.push('【供应商红黑榜（黑榜=高风险，建议换）】');
    blacks.forEach(s=>L.push(`- ${s.supplier} ${s.name||''}：质量分 ${Number(s.quality_score||0).toFixed(1)}，${s.level||'高风险'}（胜诉率 ${pct(s.win_rate||0)}）`));
  }
  const alerts=d.anomaly_alerts||[];
  if(alerts.length){
    L.push(''); L.push('【异常 SKU 预警】');
    alerts.slice(0,5).forEach(a=>L.push(`- ${a.sku}（${a.category||''}）：${a.reason||''}`));
  }
  L.push('');
  L.push('※ 以上仅基于已沉淀退货数据的客观统计，不构成对平台裁决的替代。ReturnGuard V1.0');
  return L.join('\n');
}
function exportReport(){
  const d=_ins||{};
  if(!d.total_cases){ $('#insStatus').textContent='请先刷新看板'; return; }
  const cat=$('#catSel').value||'', plat=$('#platSel').value||'';
  const scope=(cat?cat+' / ':'')+(plat||'全平台');
  const blacks=(d.supplier_blacklist&&d.supplier_blacklist.length)?d.supplier_blacklist
    :(d.supplier_scorecard||[]).filter(s=>s.level==='高风险'||s.quality_score<50).slice(0,5);
  const alerts=d.anomaly_alerts||[];
  $('#ovTitle').textContent='选品·品控洞察报告';
  $('#ovBody').innerHTML=`
    <div class="report">
      <h3 style="margin:0 0 2px;font-size:18px">ReturnGuard 选品 · 品控洞察报告</h3>
      <div class="r-meta">生成时间：${new Date().toLocaleString('zh-CN')} ｜ 数据源：${CURRENT_SOURCE==='real'?'实际数据':'演示数据'} ｜ 筛选：${esc(scope)}</div>
      <div class="r-kpis">
        <div class="r-kpi"><b>${Number(d.total_cases).toLocaleString()}</b><span>已分析退货（笔）</span></div>
        <div class="r-kpi"><b style="color:${wrColor(d.win_rate||0)}">${pct(d.win_rate||0)}</b><span>维权胜诉率</span></div>
        <div class="r-kpi"><b>¥${Number(d.total_refund||0).toLocaleString('zh-CN',{maximumFractionDigits:0})}</b><span>累计退款</span></div>
        <div class="r-kpi"><b>¥${Number(d.logistics_cost||0).toLocaleString('zh-CN',{maximumFractionDigits:0})}</b><span>物流成本（估算）</span></div>
        <div class="r-kpi"><b style="color:var(--warn)">¥${Number(d.total_return_cost||0).toLocaleString('zh-CN',{maximumFractionDigits:0})}</b><span>退货总成本</span></div>
        <div class="r-kpi"><b>${pct(d.avg_dispute_rate||0)}</b><span>货不对板嫌疑率</span></div>
      </div>
      <h4>根因分析</h4>
      <div style="font-size:13px;line-height:1.7">${esc(d.root_cause||'暂无足够数据')}</div>
      ${d.report?`<h4>洞察报告</h4><div style="font-size:13px;line-height:1.7">${esc(d.report)}</div>`:''}
      <h4>选品 / 品控建议</h4>
      <ul>${(d.recommendations||[]).map(r=>`<li>${esc(r)}</li>`).join('')||'<li>暂无建议</li>'}</ul>
      ${blacks.length?`<h4>供应商黑名单（质量分 &lt; 50，建议换）</h4>
      <ul>${blacks.map(s=>`<li><b>${esc(s.supplier)}</b> ${esc(s.name||'')}：质量分 ${Number(s.quality_score||0).toFixed(1)}${s.reason?`（${esc(s.reason)}）`:''}</li>`).join('')}</ul>`:''}
      ${alerts.length?`<h4>异常 SKU 预警</h4>
      <ul>${alerts.slice(0,5).map(a=>`<li><b>${esc(a.sku)}</b>（${esc(a.category||'')}）：${esc(a.reason||'')}</li>`).join('')}</ul>`:''}
      <div class="r-actions">
        <button type="button" id="downloadPdfBtn">下载 PDF</button>
        <button type="button" class="ghost" id="copyReportBtn">复制报告文本</button>
      </div>
      <div class="r-foot">※ 以上仅基于已沉淀退货数据的客观统计，不构成对平台裁决的替代。ReturnGuard V1.0</div>
    </div>`;
  $('#overlay').classList.add('show');
  $('#copyReportBtn').onclick=()=>copyReportText(d);
  $('#downloadPdfBtn').onclick=()=>downloadPdfReport();
}
function copyReportText(d){
  copyText(reportText(d)).then(ok=>{
    const b=$('#copyReportBtn');
    if(ok){ b.textContent='已复制'; setTimeout(()=>{b.textContent='复制报告文本';},1800); }
    else { b.textContent='复制失败'; setTimeout(()=>{b.textContent='复制报告文本';},1800); }
  });
}
async function downloadPdfReport(){
  const btn=$('#downloadPdfBtn');
  const old=btn.textContent; btn.textContent='生成中…'; btn.disabled=true;
  try{
    const mode=CURRENT_SOURCE==='real'?'live':'mock', cat=$('#catSel').value, plat=$('#platSel').value;
    const reg=$('#regionSel').value, seas=$('#seasonSel').value;
    const qs=new URLSearchParams({mode});
    if(cat) qs.set('category',cat);
    if(plat) qs.set('platform',plat);
    if(reg) qs.set('region',reg);
    if(seas) qs.set('season',seas);
    // source 由 apiUrl 统一附加，但 export_pdf 也会从 query 读取，这里显式保证一致
    qs.set('source', CURRENT_SOURCE);
    const r=await apiFetch('/api/export_pdf?'+qs.toString());
    if(!r.ok) throw new Error('导出失败 '+r.status);
    const blob=await r.blob();
    const url=URL.createObjectURL(blob);
    const a=document.createElement('a'); a.href=url;
    const disp=r.headers.get('Content-Disposition')||'';
    const m=disp.match(/filename="?([^";]+)"?/);
    a.download=m?m[1]:'ReturnGuard洞察报告.pdf';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(url), 1200);
  }catch(e){
    btn.textContent=old; btn.disabled=false;
    if($('#copyReportBtn')) $('#copyReportBtn').textContent='导出失败';
    console.error('导出 PDF 失败：', e);
  }
  finally{ btn.textContent=old; btn.disabled=false; }
}

// 单案举证：退货图叠加缺陷红框（P3-5：改为加载 /uploads 返回的 URL，而非内联 base64）
function renderAnnot(boxes, imgUrl, boxLive){
  const cv=$('#annot');
  if(!boxes||!boxes.length||!imgUrl){cv.style.display='none';return;}
  // boxLive=true：真实视觉模型坐标 → 红色实线框；false：live 回退示意框 / mock 演示框 → 琥珀虚线框
  const live = !!boxLive;
  const stroke = live ? '#f87171' : '#fbbf24';
  const dash = live ? [] : [6,4];
  const labelColor = live ? '#fecaca' : '#fde68a';
  const badge = $('#boxBadge');
  if(badge){
    badge.textContent = live ? '红框：AI 实算（真实视觉坐标）' : '红框：演示示意（回退）';
    badge.className = 'box-badge ' + (live ? 'live' : 'fallback');
  }
  const img=new Image();
  img.onload=()=>{
    const W=Math.min(640, Math.max(480, img.width||640)), H=Math.round(img.height*W/(img.width||1));
    cv.width=W; cv.height=H; cv.style.display='block';
    const ctx=cv.getContext('2d');
    ctx.drawImage(img,0,0,W,H);
    boxes.forEach(b=>{
      const x=Math.max(0,b.x*W), y=Math.max(0,b.y*H), w=Math.min(W-b.x*W,b.w*W), h=Math.min(H-b.y*H,b.h*H);
      ctx.save();
      ctx.setLineDash(dash);
      ctx.strokeStyle=stroke; ctx.lineWidth=3; ctx.strokeRect(x,y,w,h);
      ctx.restore();
      // 置信度（真实分数或演示示意值）：有则拼到标签，让红框更接近真实检测呈现（不替代平台裁决）
      const showConf = (b.confidence!=null && b.confidence>0);
      const suffix = live ? '' : '（示意）';
      const txt = (showConf ? `${b.label} · ${Math.round(b.confidence*100)}%` : b.label) + suffix;
      ctx.font='12px sans-serif';
      const tw=ctx.measureText(txt).width;
      const ly = y>16 ? y-15 : y+h+3;
      // 标签底衬，提升红框上文字可读性（关键帧红框打磨）
      ctx.fillStyle='rgba(15,23,42,.82)';
      ctx.fillRect(x, ly-12, tw+8, 16);
      ctx.fillStyle=labelColor;  // 真实红/回退琥珀，配底衬更清晰
      // 标签文本走 esc 转义，杜绝 live 模型自由文本引发的 XSS（P1-3）
      ctx.fillText(esc(txt), x+4, ly);
    });
  };
  img.onerror=()=>{cv.style.display='none';};  // URL 加载失败则静默隐藏，不阻断结果展示
  img.src=imgUrl;
}

async function loadInsights(){
  const status=$('#insStatus');
  status.textContent='加载中…'; status.classList.add('loading');
  const board=$('.board'); if(board){board.classList.remove('animated'); void board.offsetWidth; board.classList.add('animated');}
  try{
  const mode=CURRENT_SOURCE==='real'?'live':'mock', cat=$('#catSel').value, plat=$('#platSel').value;
  const reg=$('#regionSel').value, seas=$('#seasonSel').value;
  const qs=new URLSearchParams({mode});
  if(cat) qs.set('category',cat);
  if(plat) qs.set('platform',plat);
  if(reg) qs.set('region',reg);
  if(seas) qs.set('season',seas);
  const r=await apiFetch('/api/insights?'+qs.toString()); if(!r.ok) throw new Error('洞察接口 '+r.status);
  const d=await r.json();
  _ins = d;  // 供供应商下钻本地计算
  // C组：实际数据(real)未登录时显示登录门；已登录但 AI 仍在计算时显示加载态
  const _board=document.querySelector('.board');
  if(d.requires_login){
    // 已有令牌说明用户已登录，API 仍返回 requires_login 说明 AI 正在计算（或租户初始化中）→ 显示加载态而非登录门
    if(authToken()){
      if(_board){ _board.classList.remove('gated'); }
      const _lgm=document.getElementById('loginGateMsg');
      if(_lgm){ _lgm.textContent='AI 正在计算洞察结果，请稍候…'; }
      status.textContent='计算中…'; status.classList.add('loading');
      // 显示加载卡片而非登录门
      const _gate=document.getElementById('loginGate');
      if(_gate){ _gate.style.display='none'; }
      // 显示一个全宽加载提示
      let _load=document.getElementById('computingHint');
      if(!_load){
        _load=document.createElement('div'); _load.id='computingHint';
        _load.className='card';
        _load.innerHTML='<div style="text-align:center;padding:40px 20px"><div class="analyzing" style="display:inline-flex;justify-content:center;margin-bottom:14px"><span class="spin"></span><span>AI 正在计算洞察结果</span></div><p class="desc" style="margin:0">首次切换到实际数据需要运行 AI 聚类分析，通常需要 10–30 秒。</p></div>';
        _load.style.display='';
        const _b=document.querySelector('.board');
        if(_b) _b.insertBefore(_load, _b.firstChild);
      } else { _load.style.display=''; }
      return;
    }
    // 未登录 → 显示登录门
    if(_board) _board.classList.add('gated');
    const _lgm=document.getElementById('loginGateMsg');
    if(_lgm) _lgm.textContent=d.message||'请登录后查看实际数据';
    status.textContent='请登录'; status.classList.remove('loading');
    // 隐藏加载提示
    const _load=document.getElementById('computingHint');
    if(_load) _load.style.display='none';
    return;
  }
  // 隐藏加载提示（正常返回数据时）
  const _load=document.getElementById('computingHint');
  if(_load) _load.style.display='none';
  if(_board) _board.classList.remove('gated');
  // 实际数据为空时给出引导（演示数据默认有种子，不会空）
  const emptyHint=$('#scopeTag');
  if(d.source==='real' && d.total_cases===0){
    emptyHint.textContent='实际数据为空 · 去「数据录入」添加';
    emptyHint.style.background='var(--warn)';
  }
  // 模式标签：实际数据源统一显示"AI 实算"（表示该源走 AI 计算链路，无论当前是否已回退 mock）
  const isRealSource = CURRENT_SOURCE==='real';
  const modeLabel= isRealSource ? 'AI 实算' : '演示数据';
  $('#insModeTag').textContent=modeLabel+(d.error&&!isRealSource?' (已切回演示)':'');
  $('#insModeTag').style.background=isRealSource?'var(--ok)':'var(--warn)';
  $('#scopeTag').textContent=(cat?cat+' / ':'')+(plat||'全平台')+(reg?' / '+reg:'')+(seas?' / '+seas:'');

  // KPI（带动画）
  animateValue($('#kTotal'), d.total_cases, v=>Math.round(v).toLocaleString());
  animateValue($('#kRefund'), d.total_refund||0, v=>Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2}));
  $('#kWin').style.color=wrColor(d.win_rate||0);
  animateValue($('#kWin'), d.win_rate||0, v=>pct(v));
  $('#kDisp').style.color='var(--bad)';
  animateValue($('#kDisp'), d.avg_dispute_rate||0, v=>pct(v));
  const note=d.dispute_rate_note||'代理指标：由退货图与本店主图相似度推算，非平台争议笔数。';
  $('#kDispNote').title=note;

  // ① 品类热力
  const ct=$('#catTbl').querySelector('tbody'); ct.innerHTML='';
  (d.category_heatmap||[]).forEach(x=>{
    const a=Math.min(0.5,(x.dispute_rate||0)*0.7);
    const tr=document.createElement('tr');
    tr.style.background=`rgba(248,113,113,${a.toFixed(2)})`;
    tr.innerHTML=`<td>${esc(x.category)}</td><td>${x.cases}</td><td>${x.refund}</td>`
      +`<td style="color:${wrColor(x.win_rate)};font-weight:600">${pct(x.win_rate)}</td><td>${esc(x.top_defect)}</td>`;
    ct.appendChild(tr);
  });

  // ② 根因归因
  const rd=$('#rootDist'); rd.innerHTML='';
  const rc=d.root_cause_dist||{}; const rmax=Math.max(1,...Object.values(rc));
  Object.entries(rc).sort((a,b)=>b[1]-a[1]).forEach(([k,v])=>{
    const div=document.createElement('div'); div.style.marginTop='6px';
    div.innerHTML=`<div style="font-size:12px;display:flex;justify-content:space-between"><span>${esc(k)}</span><span>${v} 笔</span></div>`
      +`<div class="bar"><i style="width:${Math.round(v/rmax*100)}%;background:var(--warn)"></i></div>`;
    rd.appendChild(div);
  });
  $('#rootCause').textContent=d.root_cause||'-';

  // ③ 供应商红黑榜
  const sc=d.supplier_scorecard||[];
  const black=sc.filter(s=>s.level==='高风险');
  const red=sc.slice(-3).reverse();
  const sg=$('#supBlack'); sg.innerHTML='<div style="font-size:12px;color:var(--bad);font-weight:600">黑榜 · 高风险，建议换</div>';
  (black.length?black:sc.slice(0,1)).forEach(s=>{
    const div=document.createElement('div'); div.className='sup'; div.style.borderColor='var(--bad)';
    div.innerHTML=`<span><b style="color:var(--txt)">${esc(s.supplier)}</b> ${esc(s.name)}<br><span style="color:var(--txt3);font-size:11px">缺陷率${pct(s.defect_rate)} · 胜诉率${pct(s.win_rate)} · ${s.cases}笔</span></span>`
      +`<span class="pill" style="background:var(--bad)">质量分 ${s.quality_score}</span>`;
    sg.appendChild(div);
  });
  const sr=$('#supRed'); sr.innerHTML='<div style="font-size:12px;color:var(--ok);font-weight:600">红榜 · 优质，可长期合作</div>';
  red.forEach(s=>{
    const div=document.createElement('div'); div.className='sup'; div.style.borderColor='var(--ok)';
    div.innerHTML=`<span><b style="color:var(--txt)">${esc(s.supplier)}</b> ${esc(s.name)}<br><span style="color:var(--txt3);font-size:11px">缺陷率${pct(s.defect_rate)} · 胜诉率${pct(s.win_rate)} · ${s.cases}笔</span></span>`
      +`<span class="pill" style="background:var(--ok)">质量分 ${s.quality_score}</span>`;
    sr.appendChild(div);
  });

  // ④ 平台对比
  const pt=$('#platTbl').querySelector('tbody'); pt.innerHTML='';
  (d.platform_view||[]).forEach(x=>{
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${esc(x.platform)}</td><td>${x.cases}</td>`
      +`<td style="color:${wrColor(x.win_rate)};font-weight:600">${winRateCell(x)}</td><td>${x.refund}</td>`;
    pt.appendChild(tr);
  });

  // ⑤ 异常预警
  const al=$('#alerts'); al.innerHTML='';
  (d.anomaly_alerts||[]).forEach(a=>{
    const div=document.createElement('div'); div.className='alert';
    div.textContent='⚠ '+a.reason; al.appendChild(div);
  });
  if(!(d.anomaly_alerts||[]).length) al.innerHTML='<span class="note">本期无异常（近 30 天增量未超阈值）。</span>';

  // ⑥ SKU 明细
  const st=$('#skuTbl').querySelector('tbody'); st.innerHTML='';
  (d.sku_ranking||[]).slice(0,15).forEach(x=>{
    const tr=document.createElement('tr');
    if(x.anomaly) tr.style.background='rgba(251,191,36,.12)';
    tr.innerHTML=`<td>${esc(x.sku)}</td><td>${esc(x.category)}</td><td>${esc(x.supplier)}</td>`
      +`<td>${x.cases}</td><td>${x.refund}</td>`
      +`<td style="color:${wrColor(x.win_rate)};font-weight:600">${pct(x.win_rate)}</td>`
      +`<td>${esc(x.top_defect)}</td><td>${x.anomaly?'⚠':'-'}</td>`;
    st.appendChild(tr);
  });

  // ⑦⑧ 报告 + 建议
  $('#report').textContent=d.report||'-';
  const adv=$('#advice'); adv.innerHTML='';
  (d.sourcing_advice||d.recommendations||[]).forEach(t=>{
    const div=document.createElement('div'); div.style.cssText='background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:10px;margin-top:8px;font-size:13px;color:var(--txt)';
    div.textContent='▸ '+t; adv.appendChild(div);
  });
  if(d.error) $('#report').textContent+='\n[提示] AI 实算失败，已切回演示数据：'+d.error;

  // ⑬ 地区分布
  const rt=$('#regionTbl').querySelector('tbody'); rt.innerHTML='';
  (d.region_view||[]).forEach(x=>{
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${esc(x.region)}</td><td>${x.cases}</td><td>${x.refund}</td>`
      +`<td style="color:${wrColor(x.win_rate)};font-weight:600">${winRateCell(x)}</td>`;
    rt.appendChild(tr);
  });
  renderBarh($('#regionBars'), (d.region_view||[]).map(x=>({label:x.region,v:x.refund,text:'¥'+x.refund,color:'#22d3ee'})));

  // ⑭ 季节分布
  const stt=$('#seasonTbl').querySelector('tbody'); stt.innerHTML='';
  (d.season_view||[]).forEach(x=>{
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${esc(x.season)}</td><td>${x.cases}</td><td>${x.refund}</td>`
      +`<td style="color:${wrColor(x.win_rate)};font-weight:600">${pct(x.win_rate)}</td>`;
    stt.appendChild(tr);
  });
  renderBarh($('#seasonBars'), (d.season_view||[]).map(x=>({label:x.season,v:x.refund,text:'¥'+x.refund,color:'#e879f9'})));

  // ⑮ 退货成本 & 供应商黑名单
  $('#costKpis').innerHTML =
    `<div class="kv"><span>物流成本（估算）</span><b>¥${Number(d.logistics_cost||0).toLocaleString('zh-CN',{maximumFractionDigits:0})}</b></div>`
    +`<div class="kv"><span>退货总成本（退款+物流）</span><b>¥${Number(d.total_return_cost||0).toLocaleString('zh-CN',{maximumFractionDigits:0})}</b></div>`;
  const bl=$('#blacklist'); bl.innerHTML='<div style="font-size:12px;color:var(--bad);font-weight:600">供应商黑名单 · 质量分&lt;50</div>';
  const blacks=d.supplier_blacklist||[];
  if(blacks.length){
    blacks.forEach(s=>{
      const div=document.createElement('div'); div.className='sup'; div.style.borderColor='var(--bad)';
      div.innerHTML=`<span><b style="color:var(--txt)">${esc(s.supplier)}</b> ${esc(s.name)}<br><span style="color:var(--txt3);font-size:11px">${esc(s.reason)}</span></span>`
        +`<span class="pill" style="background:var(--bad)">${s.quality_score}</span>`;
      bl.appendChild(div);
    });
  } else {
    bl.innerHTML+='<span class="note">暂无质量分&lt;50 的高风险供应商。</span>';
  }

  // ⑯⑰⑱ B组：时间序列 / 预测预警 / 选品避坑闭环
  renderTrendLine($('#trendLine'), d.time_series||[], d.forecast||{});
  $('#trendNote').textContent = (d.time_series&&d.time_series.length)
    ? `历史 ${d.time_series.length} 个月；趋势 ${trendLabel((d.forecast||{}).trend)}`
    : '暂无带日期的案件，无法生成时间序列（录入时填写「案件日期」即可）。';
  renderForecast($('#forecastKpis'), $('#forecastList'), $('#forecastAlerts'), d.forecast||{}, d.forecast_alerts||[]);
  renderSourcingLoop($('#sourcingLoop'), d.sourcing_checklist||[]);

  // 图形化
  renderBarh($('#catBars'), (d.category_heatmap||[]).map(x=>({label:x.category,v:x.refund,text:'¥'+x.refund,color:'#fbbf24'})));
  renderBarh($('#platBars'), (d.platform_view||[]).map(x=>({label:x.platform,v:Math.round((x.win_rate||0)*100),text:pct(x.win_rate),color:realColor(x.win_rate||0)})), {absolute:true});
  renderBarh($('#supBars'), (d.supplier_scorecard||[]).map(x=>({label:x.supplier,v:x.quality_score,text:String(x.quality_score),color:x.level==='高风险'?'#fb7185':x.level==='优质'?'#4ade80':'#facc15'})));
  renderMatrix($('#matrixHeat'), d.platform_supplier_matrix||[]);
  renderSuppliers(d);
  renderDonut($('#kWinDonut'), d.win_rate||0);
  status.textContent='已更新 · '+new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});
  status.classList.remove('loading');
  }catch(e){ status.textContent='加载失败'; status.classList.remove('loading'); console.error('loadInsights 出错', e); }
}

// 平台适配举证包（交付物 A）渲染
async function loadPlatforms(){
  try{
    const r=await fetch('/api/platforms'); const d=await r.json();
    const ps=d.platforms||[];
    const attrs=[['return_window','退货窗口'],['response_window','响应时限'],['shipping_payer','运费承担'],['burden_bias','举证偏向']];
    let html='<tr><th>维度</th>'+ps.map(p=>`<th>${esc(p.label)}</th>`).join('')+'</tr>';
    attrs.forEach(([k,name])=>{
      html+='<tr><th>'+name+'</th>'+ps.map(p=>`<td>${esc(p[k])}</td>`).join('')+'</tr>';
    });
    $('#platCmp').innerHTML=`<table class="cmp">${html}</table>`;
    // 各平台政策：默认折叠，点击平台名展开（单开折叠，大屏演示清洁）
    let tmpl='';
    ps.forEach(p=>{
      const cap=p.capability_map||{};
      const capItems=Object.entries(cap).map(([k,v])=>`<li><b>${esc(k)}</b>：${esc(v)}</li>`).join('');
      tmpl+=`<div class="plat-acc" data-key="${esc(p.key)}">`
        +`<button type="button" class="plat-head" aria-expanded="false">`
        +`<span class="plat-name">${esc(p.label)}</span>`
        +`<span class="plat-hint">举证偏向：${esc(p.burden_bias||'-')}</span>`
        +`<span class="plat-arrow" aria-hidden="true">▸</span>`
        +`</button>`
        +`<div class="plat-body">`
        +`<div class="kv"><span>退货窗口</span><b>${esc(p.return_window)}</b></div>`
        +`<div class="kv"><span>响应时限</span><b>${esc(p.response_window)}</b></div>`
        +`<div class="kv"><span>运费承担</span><b>${esc(p.shipping_payer)}</b></div>`
        +`<div class="kv"><span>举证偏向</span><b>${esc(p.burden_bias)}</b></div>`
        +`<div style="font-size:12px;color:var(--txt3);margin-top:10px">必备举证材料</div><ul class="ev">${p.required_evidence.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`
        +`<div style="font-size:12px;color:var(--txt3);margin-top:8px">常见失分 / 败诉原因</div><ul class="ev bad">${p.common_loss_reasons.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`
        +`<div style="font-size:12px;color:var(--txt3);margin-top:8px">平台特殊条款</div><ul class="ev dim">${(p.special_clauses||[]).map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`
        +`<div style="font-size:12px;color:var(--txt3);margin-top:8px">ReturnGuard 怎么帮你举证</div><ul class="ev cap">${capItems}</ul>`
        +`</div></div>`;
    });
    $('#platTmpl').innerHTML=tmpl;
  }catch(e){ $('#platCmp').innerHTML='<span class="err">举证包加载失败</span>'; }
}
// 平台举证包折叠：事件委托，单开折叠（点其他平台自动收上当前）
// 真 auto 高度：用 plat-body.scrollHeight 实测内容高度过渡，结束后解除上限
$('#platTmpl').addEventListener('click', e=>{
  const head = e.target.closest('.plat-head');
  if(!head) return;
  const acc = head.parentElement;
  const wasOpen = acc.classList.contains('open');
  // 关闭所有已展开
  document.querySelectorAll('#platTmpl .plat-acc.open').forEach(a=>{
    const b=a.querySelector('.plat-body');
    if(b && b.style.maxHeight===''){ b.style.maxHeight = Math.max(1,b.scrollHeight)+'px'; void b.offsetHeight; }
    a.classList.remove('open');
    const h=a.querySelector('.plat-head'); if(h) h.setAttribute('aria-expanded','false');
    if(b) b.style.maxHeight='0px';
  });
  // 展开点击的平台（若原本收起）
  if(!wasOpen){
    acc.classList.add('open');
    head.setAttribute('aria-expanded','true');
    const b=acc.querySelector('.plat-body');
    if(b){
      b.style.maxHeight='0px';
      void b.offsetHeight;
      b.style.maxHeight = Math.max(1,b.scrollHeight)+'px';
      const te=ev=>{ if(ev.propertyName==='max-height'){ b.style.maxHeight=''; b.removeEventListener('transitionend', te); } };
      b.addEventListener('transitionend', te);
    }
  }
});

// 单案举证
async function doAnalyze(e){
  e.preventDefault();
  $('#err').textContent=''; $('#res').classList.add('hide'); $('#resEmpty').classList.add('hide');
  $('#modeBadge').classList.add('hide');
  const btn=$('#btn'); btn.disabled=true; btn.textContent='举证中…';
  // 分析中状态：live 模式耗时长，明确提示避免误以为卡死
  const fd=new FormData($('#f'));
  $('#analyzing').classList.remove('hide');
  $('#analyzingText').textContent = fd.get('mode')==='live' ? '真实 AI 分析中（约 30-60 秒，请稍候）…' : '正在生成取证结果…';
  setStep(2);
  try{
    const r=await apiFetch('/api/analyze',{method:'POST',body:fd});
    const d=await r.json();
    if(!r.ok) throw new Error(d.detail||'请求失败');
    $('#sim').textContent=Math.round(d.similarity*100)+'%';
    $('#simbar').style.width=Math.round(d.similarity*100)+'%';
    // P2-4 前端：阈值统一取自 /api/config（SAME_ITEM_THRESHOLD），不再硬编码 0.82
    $('#simbar').style.background=d.similarity>=SAME_ITEM_THRESHOLD?'var(--ok)':'var(--bad)';
    $('#same').textContent=d.same_item?'是同一件':'疑似调包/非同款';
    $('#same').style.background=d.same_item?'var(--ok)':'var(--bad)';
    $('#cons').textContent=d.consistency;
    // P1-3：缺陷标签拼进 innerHTML 前转义，杜绝 live 模型自由文本 XSS
    $('#defects').innerHTML=(d.defect_tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join('');
    // P3-5：红框图从 /uploads 返回的 URL 加载（后端已不返回内联 base64）
    // boxLive：红框来自真实视觉模型(True)还是回退示意框(False)；mock 模式恒为 False
    const boxLive = !!(d.defect_boxes_live || (d.capabilities && d.capabilities.boxes));
    renderAnnot(d.defect_boxes, d.returned_image_url, boxLive);
    $('#prio').textContent=d.priority_score;
    $('#dossier').textContent=d.dossier;
    $('#vtext').textContent=d.voice_text;
    $('#audio').src='data:audio/wav;base64,'+d.voice_audio_b64;
    if(d.platform && (d.platform_evidence||[]).length){
      $('#platName').textContent=d.platform;
      $('#platEv').innerHTML=(d.platform_evidence||[]).map(t=>`<li>${esc(t)}</li>`).join('');
      $('#platEvWrap').classList.remove('hide');
    } else { $('#platEvWrap').classList.add('hide'); }
    // 分析完成：关分析中、步骤条到③、展示本次取证模式徽标
    $('#analyzing').classList.add('hide');
    setStep(3);
    renderBadge(d.mode);
    renderOrchestration(d);
    const cb=$('#copyDossier'); cb.textContent='复制'; cb.classList.remove('copied');
    $('#res').classList.remove('hide');
  }catch(err){ $('#analyzing').classList.add('hide'); setStep(1); $('#err').textContent='错误：'+err.message; }
  finally{ btn.disabled=false; btn.textContent='开始举证'; }
}

// 取证流程步骤条：1 上传 → 2 分析中 → 3 完成
function setStep(n){
  document.querySelectorAll('#forensicSteps .st').forEach((el,i)=>{
    el.classList.toggle('cur', i+1===n);
    el.classList.toggle('done', i+1<n);
  });
}
// 结果模式徽标：mock=演示 / live=真实AI / mock(fallback)=真实AI(降级)
function renderBadge(mode){
  const b=$('#modeBadge'); b.classList.remove('hide','mock','live','fallback');
  if(mode==='live'){ b.classList.add('live'); b.textContent='真实 AI 归因'; }
  else if(mode==='mock(fallback)'){ b.classList.add('fallback'); b.textContent='真实 AI（降级演示）'; }
  else { b.classList.add('mock'); b.textContent='演示模式'; }
}
// P2 多模型协同编排链路：把单案取证的 6 项模型能力 + 1 项本地公式串成可视化链路，
// 每步如实显示「真实模型 / 回退演示 / 本地公式」，体现"网关渐进开通即生效"的设计。
function renderOrchestration(d){
  const wrap=$('#orchWrap');
  if(d.mode!=='live' && d.mode!=='mock(fallback)'){ wrap.style.display='none'; return; }
  wrap.style.display='block';
  const caps=d.capabilities||{};
  const steps=[
    {k:'同款比对', t:'similarity'},
    {k:'瑕疵识别', t:'defects'},
    {k:"缺陷定位", t:'boxes'},
    {k:'承诺OCR', t:'ocr'},
    {k:'文本归因', t:'llm'},
    {k:'优先级', t:'rerank'},
    {k:'语音陈述', t:'tts'},
  ];
  const chain=$('#orchChain'); chain.innerHTML='';
  steps.forEach(s=>{
    let cls, state;
    if(s.t==='rerank'){ cls='local'; state='本地公式'; }
    else if(s.t==='llm'){ const live=(d.mode==='live'); cls=live?'live':'fallback'; state=live?'真实模型':'回退演示'; }
    else { const live=(d.mode==='live') && caps[s.t]===true; cls=live?'live':'fallback'; state=live?'真实模型':'回退演示'; }
    const chip=document.createElement('div');
    chip.className='orch-chip '+cls;
    chip.innerHTML=`<span class="orch-step">${esc(s.k)}</span><span class="orch-state">${esc(state)}</span>`;
    chain.appendChild(chip);
  });
}
// 一键复制举证材料（演示「可直接提交平台仲裁」）
async function copyDossier(){
  const txt=$('#dossier').textContent||'';
  if(!txt) return;
  const ok=await copyText(txt);
  const b=$('#copyDossier');
  if(ok){ b.textContent='已复制'; b.classList.add('copied'); }
  else { b.textContent='复制失败'; if($('#err')) $('#err').textContent='复制失败，请手动选择文本。'; }
  setTimeout(()=>{ b.textContent='复制'; b.classList.remove('copied'); },2000);
}

// 用洞察响应填充顶部品类/平台/供应商筛选下拉（P3-2 复用一次响应）
function populateFilters(){
  const d=_ins||{};
  $('#catSel').innerHTML='<option value="">全部品类</option>';
  $('#formCat').innerHTML='<option value="">未指定</option>';
  $('#platSel').innerHTML='<option value="">全部平台</option>';
  $('#formSup').innerHTML='<option value="">未指定</option>';
  [...new Set((d.category_heatmap||[]).map(x=>x.category))].forEach(c=>{
    const o=document.createElement('option'); o.value=c; o.textContent=c;
    $('#catSel').appendChild(o); $('#formCat').appendChild(o.cloneNode(true));
  });
  [...new Set((d.platform_view||[]).map(x=>x.platform))].forEach(p=>{
    const o=document.createElement('option'); o.value=p; o.textContent=p;
    $('#platSel').appendChild(o);
  });
  // 供应商规范花名册（与后端 convert_datasets.py SUPPLIERS 对齐）
  const SUPPLIER_NAMES = {"S1":"鼎峰精密","S2":"云仓优选","S3":"鑫源电子(劣)","S4":"通达包装弱","S5":"联创供货","S6":"海贸乱发(劣)","S7":"锐捷制造","S8":"万通杂货"};
  [...new Set((d.supplier_scorecard||[]).map(s=>s.supplier))].forEach(s=>{
    if(s){ const o=document.createElement('option'); o.value=s; o.textContent=s+(SUPPLIER_NAMES[s]?' '+SUPPLIER_NAMES[s]:''); $('#formSup').appendChild(o); }
  });
}

// 加载「当前数据源」已录入案件列表（数据录入页右侧）——支持分页（A23：后端 /api/cases 分页信封）
let entryPage = 1;
const ENTRY_PAGE_SIZE = 20;
async function loadEntryList(page){
  if(page) entryPage = page;
  try{
    const r=await apiFetch(`/api/cases?slim=1&page=${entryPage}&page_size=${ENTRY_PAGE_SIZE}`);
    const res=await r.json();
    const list=res.items||[];
    const wrap=$('#entryTableWrap');
    if(!list.length){ wrap.innerHTML='<span class="note">当前数据源暂无案件。</span>'; return; }
    const total=res.total||0;
    const totalPages=Math.max(1, Math.ceil(total/ENTRY_PAGE_SIZE));
    let html='<table><thead><tr><th>SKU</th><th>品类</th><th>供应商</th><th>金额</th><th>判定</th><th></th></tr></thead><tbody>';
    list.slice().reverse().forEach(x=>{
      html+=`<tr><td>${esc(x.sku)}</td><td>${esc(x.category)}</td><td>${esc(x.supplier)}</td>`
        +`<td>¥${Number(x.amount||0).toFixed(0)}</td><td>${esc(x.outcome||'待分析')}</td>`
        +`<td><button class="entry-del" data-id="${esc(x.case_id)}">删除</button></td></tr>`;
    });
    html+='</tbody></table>';
    html+=`<div class="pager"><button id="prevPage" ${entryPage<=1?'disabled':''}>‹ 上一页</button>`
        +`<span class="pager-info">第 ${entryPage}/${totalPages} 页 · 共 ${total} 条</span>`
        +`<button id="nextPage" ${entryPage>=totalPages?'disabled':''}>下一页 ›</button></div>`;
    wrap.innerHTML=html;
    const prev=$('#prevPage'), next=$('#nextPage');
    if(prev) prev.onclick=()=>loadEntryList(Math.max(1, entryPage-1));
    if(next) next.onclick=()=>loadEntryList(Math.min(totalPages, entryPage+1));
  }catch(e){ $('#entryTableWrap').innerHTML='<span class="err">列表加载失败</span>'; }
}

// 提交一条手动录入案件到当前数据源
async function submitEntry(e){
  e.preventDefault();
  const btn=$('#entryBtn'); btn.disabled=true; btn.textContent='提交中…';
  $('#entryMsg').textContent=''; $('#entryMsg').className='entry-msg';
  try{
    const fd=new FormData($('#entryForm'));
    const payload={}; fd.forEach((v,k)=>{ payload[k]=v; });
    payload.amount=parseFloat(payload.amount||0)||0;
    payload.similarity=parseFloat(payload.similarity||0)||0;
    payload.same_item=(payload.same_item==='true');
    payload.defect_tags=(payload.defect_tags||'').split(',').map(s=>s.trim()).filter(Boolean);
    const r=await apiFetch('/api/cases',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const d=await r.json();
    if(!r.ok) throw new Error(d.detail||'提交失败');
    $('#entryMsg').textContent='✓ 已添加到「'+(CURRENT_SOURCE==='real'?'实际数据':'演示数据')+'」：'+d.case_id;
    $('#entryMsg').className='entry-msg ok';
    $('#entryForm').reset();
    loadEntryList(); loadInsights();  // 同步刷新列表与看板
  }catch(err){ $('#entryMsg').textContent='错误：'+err.message; $('#entryMsg').className='entry-msg err'; }
  finally{ btn.disabled=false; btn.textContent='添加到当前数据源'; }
}

// 文件导入（数据集 xlsx/csv）→ 按 case_id 去重 upsert 到「当前数据源」
async function submitImport(){
  const btn=$('#importBtn'); const f=$('#importFile'); const msg=$('#importMsg'); const res=$('#importResult');
  msg.textContent=''; msg.className='entry-msg'; res.innerHTML='';
  if(!f.files || !f.files.length){ msg.textContent='请先选择数据集文件（.xlsx/.csv）'; msg.className='entry-msg err'; return; }
  btn.disabled=true; btn.textContent='导入中…';
  try{
    const fd=new FormData();
    fd.append('file', f.files[0]);
    const r=await apiFetch('/api/import_file',{method:'POST',body:fd});
    const d=await r.json();
    if(!r.ok || !d.ok) throw new Error(d.error||d.detail||'导入失败');
    res.innerHTML =
      '<div>识别类型：<span class="v">'+esc(d.detected||'未知')+'</span></div>'+
      '<div><span class="k">新增</span> <span class="v">'+d.imported+'</span>　'+
      '<span class="k">更新(删旧留新)</span> <span class="v upd">'+d.updated+'</span>　'+
      '<span class="k">跳过(同日/更旧)</span> <span class="v skip">'+d.skipped+'</span>　'+
      '<span class="k">文件内重复</span> <span class="v skip">'+d.file_duplicates+'</span></div>';
    if(d.errors && d.errors.length){ res.innerHTML += '<div class="k">提示：'+esc(d.errors.slice(0,5).join('；'))+'</div>'; }
    msg.textContent='✓ 导入完成（实际数据），看板已刷新。'; msg.className='entry-msg ok';
    loadInsights(); loadEntryList();
  }catch(err){ msg.textContent='错误：'+err.message; msg.className='entry-msg err'; }
  finally{ btn.disabled=false; btn.textContent='导入并去重'; }
}

// 初始化：拉取后端常量（P2-4）→ 设定数据源 UI → 加载看板/筛选/举证包
(async function init(){
  try{
    const cfg=await fetch('/api/config'); const c=await cfg.json();
    if(typeof c.same_item_threshold==='number' && isFinite(c.same_item_threshold)) SAME_ITEM_THRESHOLD=c.same_item_threshold;
    if(c.version) $('#appVer').textContent='V'+String(c.version).replace(/^v/i,'');
  }catch(e){ /* 网络异常则用默认 0.82 兜底 */ }

  // 设定初始数据源 UI（不在此处触发重载，避免与下方 loadInsights 重复）
  document.querySelectorAll('#srcToggle .src-btn').forEach(b=>b.classList.toggle('active', b.dataset.src===CURRENT_SOURCE));
  $('#entryTarget').textContent='将写入：'+(CURRENT_SOURCE==='real'?'实际数据':'演示数据');
  const banner=$('#entryBanner');
  if(CURRENT_SOURCE==='real'){ banner.querySelector('.sb-body').textContent='⚠ 当前为「实际数据」：看板与录入均作用于真实案件库（cases_real.db），与演示数据物理隔离。'; banner.classList.add('show'); banner.classList.remove('hidden'); }

  await loadInsights();
  populateFilters();
  await loadPlatforms();
  if(CURRENT_SOURCE==='real') await loadEntryList();
})();

// 事件绑定
document.querySelectorAll('#srcToggle .src-btn').forEach(b=>b.addEventListener('click',()=>setSource(b.dataset.src)));
$('#f').addEventListener('submit',doAnalyze);
$('#copyDossier').addEventListener('click',copyDossier);
$('#btnReport').addEventListener('click',exportReport);
$('#entryForm').addEventListener('submit',submitEntry);
$('#importBtn').addEventListener('click',submitImport);
$('#loadIns').addEventListener('click',loadInsights);
$('#catSel').addEventListener('change',loadInsights);
$('#platSel').addEventListener('change',loadInsights);
$('#regionSel').addEventListener('change',loadInsights);
$('#seasonSel').addEventListener('change',loadInsights);
$('#ovClose').addEventListener('click',closeOverlay);
$('#overlay').addEventListener('click',e=>{if(e.target.id==='overlay')closeOverlay();});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeOverlay();});
// 切换到「数据录入」页时加载列表
document.querySelectorAll('.tabs button').forEach(b=>b.addEventListener('click',()=>{ if(b.dataset.tab==='entry') loadEntryList(); }));
// 列表内删除（事件委托）
$('#entryTableWrap').addEventListener('click',async e=>{
  const btn=e.target.closest('.entry-del'); if(!btn) return;
  const id=btn.dataset.id;
  if(!confirm('确认删除案件 '+id+'？')) return;
  btn.disabled=true; btn.textContent='删除中…';
  try{
    const r=await apiFetch('/api/cases/'+encodeURIComponent(id),{method:'DELETE'});
    if(r.ok){
      loadEntryList(); loadInsights();
    } else {
      const d=await r.json().catch(()=>({}));
      btn.textContent='删除失败';
      if($('#entryErr')) $('#entryErr').textContent='删除失败：'+(d.detail||r.status);
      setTimeout(()=>{ btn.textContent='删除'; },2000);
    }
  }catch(err){
    btn.textContent='删除失败';
    if($('#entryErr')) $('#entryErr').textContent='删除失败：'+(err&&err.message||'网络错误');
    setTimeout(()=>{ btn.textContent='删除'; },2000);
  }
});

// ===================== C组：账户体系 + 多租户登录 =====================
// 令牌存 localStorage（rg_token）。登录后 real 源数据自动按当前租户隔离；
// 未登录为匿名（public 公共基准）。登录态在初始化与每次刷新看板后校验一次。
function authToken(){ return localStorage.getItem('rg_token') || ''; }
// 演示数据(demo)时隐藏登录按钮/租户标签；实际数据(real)才显示（实际数据需登录查看）
function updateAuthBtnVisibility(){
  const isReal = CURRENT_SOURCE==='real';
  const btn=$('#authBtn'), tag=$('#userTag');
  if(btn) btn.style.display = isReal ? '' : 'none';
  if(tag && !isReal) tag.style.display='none';
}
function updateAuthUI(){
  const tok=authToken();
  const btn=$('#authBtn'), tag=$('#userTag');
  if(tok){
    fetch('/api/auth/me',{headers:{'Authorization':'Bearer '+tok}}).then(r=>r.ok?r.json():null).then(d=>{
      if(d && d.user){
        tag.textContent='租户：'+d.user.username; tag.style.display='inline-block';
        btn.textContent='退出'; btn.classList.add('authed');
      } else {
        localStorage.removeItem('rg_token'); tag.style.display='none'; btn.textContent='登录'; btn.classList.remove('authed');
      }
      updateAuthBtnVisibility();
    }).catch(()=>{ updateAuthBtnVisibility(); });
  } else {
    tag.style.display='none'; btn.textContent='登录'; btn.classList.remove('authed');
    updateAuthBtnVisibility();
  }
}
function openAuthModal(){
  $('#authOverlay').classList.add('show');
  $('#authMsg').textContent='';
  // a11y：打开即把焦点移入对话框首个可聚焦元素
  const u=$('#authUser'); if(u) setTimeout(()=>u.focus(),0);
}
function closeAuthModal(){ $('#authOverlay').classList.remove('show'); }
async function doAuth(e){
  e.preventDefault();
  const isReg=$('#authTab').dataset.mode==='register';
  const u=($('#authUser').value||'').trim(), p=$('#authPass').value;
  const msg=$('#authMsg');
  const body={username:u,password:p};
  if(isReg) body.tenant_name=($('#authTenant').value||'').trim()||u;
  const r=await fetch('/api/auth/'+(isReg?'register':'login'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json().catch(()=>({}));
  if(!r.ok){ msg.textContent='✗ '+(d.detail||'失败'); return; }
  localStorage.setItem('rg_token', d.token);
  closeAuthModal(); updateAuthUI(); loadInsights(); loadEntryList();
  msg.textContent='';
}
$('#authBtn').addEventListener('click',()=>{ if(authToken()){ localStorage.removeItem('rg_token'); updateAuthUI(); loadInsights(); } else { openAuthModal(); } });
$('#loginGateBtn').addEventListener('click',openAuthModal);

// 看板按列折叠（Issue B）：每列只展开一张卡，点击标题切换；同列其他自动收起
// 初始由 HTML 中 aria-expanded="true" 决定（已默认每列第一张展开）
// 真 auto 高度：用 body.scrollHeight 实测内容高度做 max-height 过渡，结束后解除上限
function _expandCard(card){
  const body = card.querySelector('.card-body');
  card.classList.remove('collapsed');
  const head = card.querySelector('.card-head'); if(head) head.setAttribute('aria-expanded','true');
  if(!body) return;
  body.style.maxHeight = '0px';
  void body.offsetHeight; // 强制回流，保证从 0 起过渡
  body.style.maxHeight = Math.max(1, body.scrollHeight) + 'px';
  const te = ev => { if(ev.propertyName==='max-height'){ body.style.maxHeight=''; body.removeEventListener('transitionend', te); } };
  body.addEventListener('transitionend', te);
}
function _collapseCard(card){
  const body = card.querySelector('.card-body');
  if(!body) return;
  // 若当前是 auto(none)，先固定到当前内容高度，再收起
  if(body.style.maxHeight==='' || !body.style.maxHeight){
    body.style.maxHeight = Math.max(1, body.scrollHeight) + 'px';
    void body.offsetHeight;
  }
  body.style.maxHeight = '0px';
  const te = ev => { if(ev.propertyName==='max-height'){ card.classList.add('collapsed'); const h=card.querySelector('.card-head'); if(h) h.setAttribute('aria-expanded','false'); body.removeEventListener('transitionend', te); } };
  body.addEventListener('transitionend', te);
}
document.addEventListener('click', e=>{
  const head = e.target.closest('.card-head');
  if(!head || !head.closest('.col')) return; // 仅看板内的 card-head
  const card = head.closest('.card');
  const col = card.parentElement;
  const wasOpen = !card.classList.contains('collapsed');
  // 收起同列所有已展开的卡
  col.querySelectorAll('.card').forEach(c=>{
    if(!c.classList.contains('collapsed')) _collapseCard(c);
  });
  // 若点的是未展开的卡，则展开它（点已展开的卡则保持全部收起）
  if(!wasOpen) _expandCard(card);
});
// 键盘可达：Enter / Space 触发点击
document.addEventListener('keydown', e=>{
  if((e.key==='Enter'||e.key===' ') && e.target.classList && e.target.classList.contains('card-head')){
    e.preventDefault(); e.target.click();
  }
});
$('#authOverlay').addEventListener('click',e=>{ if(e.target.id==='authOverlay') closeAuthModal(); });
$('#authClose').addEventListener('click',closeAuthModal);
$('#authForm').addEventListener('submit',doAuth);
$('#authTab').addEventListener('click',()=>{
  const el=$('#authTab'); el.dataset.mode = el.dataset.mode==='register' ? 'login' : 'register';
  el.textContent = el.dataset.mode==='register' ? '登录' : '注册';
  $('#authTenantWrap').style.display = el.dataset.mode==='register' ? 'flex' : 'none';
  $('#authHint').textContent = el.dataset.mode==='register' ? '注册即创建一个独立租户空间，实际数据按租户隔离。' : '登录后查看按本租户隔离的实际数据；未登录不可见。';
});
updateAuthUI();
// 看板折叠初始：把 aria-expanded="false" 的卡片加上 .collapsed 类（HTML 已写好默认每列首张展开）
document.querySelectorAll('.board .col .card').forEach(c=>{
  const head=c.querySelector('.card-head');
  if(head && head.getAttribute('aria-expanded')==='false') c.classList.add('collapsed');
});

  // P1-7 ROI 示例测算
  function calcROI(){
    var q=parseFloat(document.getElementById('roiQty').value)||0;
    var p=parseFloat(document.getElementById('roiPrice').value)||0;
    var d=(parseFloat(document.getElementById('roiDisp').value)||0)/100;
    var g=(parseFloat(document.getElementById('roiGain').value)||0)/100;
    var w=parseFloat(document.getElementById('roiWage').value)||0;
    var save=q*p*d*g;
    var hoursSave=q*(2-3/60);
    var wageSave=hoursSave*w;
    document.getElementById('roiSave').textContent='¥'+Math.round(save).toLocaleString('zh-CN');
    document.getElementById('roiTime').textContent='¥'+Math.round(wageSave).toLocaleString('zh-CN');
  }
  ['roiQty','roiPrice','roiDisp','roiGain','roiWage'].forEach(function(id){
    var el=document.getElementById(id); if(el) el.addEventListener('input', calcROI);
  });
  calcROI();
