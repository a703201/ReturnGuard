import { state } from './store.js';
import { apiFetch, apiUrl, copyText } from './api.js';

export const $ = s => document.querySelector(s);

export const pct = x => (x*100).toFixed(0) + '%';

export const wrColor = w => w>=0.5?'var(--ok)':w>=0.3?'var(--warn)':'var(--bad)';

export const realColor = w => w>=0.5?'#4ade80':w>=0.3?'#facc15':'#fb7185';

export const winRateCell = x => (x && (x.decided===undefined || x.decided>0)) ? pct(x.win_rate) : '— 待分析';

export function esc(s){
  return (s==null?'':String(s)).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}


export function renderDonut(svg, rate){
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


export function animateValue(el, target, fmt, duration=700){
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


export function renderBarh(el, items, opts={}){
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


export function renderMatrix(el, rows){
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


export function trendLabel(t){
  return t==='up'?'上行 ↑':t==='down'?'下行 ↓':'平稳 →';
}


export function renderTrendLine(el, ts, forecast){
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


export function renderForecast(kpiEl, listEl, alertEl, forecast, alerts){
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


export function renderSourcingLoop(el, items){
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


export const SUP_PALETTE=['#f87171','#fbbf24','#38bdf8','#a78bfa','#34d399','#fb923c','#e879f9','#22d3ee'];

export function renderSuppliers(d){
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


export function openSupplier(name){
  const d=state.ins; if(!d) return;
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

export function closeOverlay(){$('#overlay').classList.remove('show');}


export function reportText(d){
  const L=[];
  L.push('ReturnGuard 选品·品控洞察报告');
  const cat=$('#catSel').value||'', plat=$('#platSel').value||'';
  const scope=(cat?cat+' / ':'')+(plat||'全平台');
  L.push(`生成时间：${new Date().toLocaleString('zh-CN')}｜数据源：${state.source==='real'?'实际数据':'演示数据'}｜筛选：${scope}`);
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

export function exportReport(){
  const d=state.ins||{};
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
      <div class="r-meta">生成时间：${new Date().toLocaleString('zh-CN')} ｜ 数据源：${state.source==='real'?'实际数据':'演示数据'} ｜ 筛选：${esc(scope)}</div>
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

export function copyReportText(d){
  copyText(reportText(d)).then(ok=>{
    const b=$('#copyReportBtn');
    if(ok){ b.textContent='已复制'; setTimeout(()=>{b.textContent='复制报告文本';},1800); }
    else { b.textContent='复制失败'; setTimeout(()=>{b.textContent='复制报告文本';},1800); }
  });
}

export async function downloadPdfReport(){
  const btn=$('#downloadPdfBtn');
  const old=btn.textContent; btn.textContent='生成中…'; btn.disabled=true;
  try{
    const mode=state.source==='real'?'live':'mock', cat=$('#catSel').value, plat=$('#platSel').value;
    const reg=$('#regionSel').value, seas=$('#seasonSel').value;
    const qs=new URLSearchParams({mode});
    if(cat) qs.set('category',cat);
    if(plat) qs.set('platform',plat);
    if(reg) qs.set('region',reg);
    if(seas) qs.set('season',seas);
    // source 由 apiUrl 统一附加，但 export_pdf 也会从 query 读取，这里显式保证一致
    qs.set('source', state.source);
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


export function renderAnnot(boxes, imgUrl, boxLive){
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


export function setStep(n){
  document.querySelectorAll('#forensicSteps .st').forEach((el,i)=>{
    el.classList.toggle('cur', i+1===n);
    el.classList.toggle('done', i+1<n);
  });
}

export function renderBadge(mode){
  const b=$('#modeBadge'); b.classList.remove('hide','mock','live','fallback');
  if(mode==='live'){ b.classList.add('live'); b.textContent='真实 AI 归因'; }
  else if(mode==='mock(fallback)'){ b.classList.add('fallback'); b.textContent='真实 AI（降级演示）'; }
  else { b.classList.add('mock'); b.textContent='演示模式'; }
}

export function renderOrchestration(d){
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

export async function copyDossier(){
  const txt=$('#dossier').textContent||'';
  if(!txt) return;
  const ok=await copyText(txt);
  const b=$('#copyDossier');
  if(ok){ b.textContent='已复制'; b.classList.add('copied'); }
  else { b.textContent='复制失败'; if($('#err')) $('#err').textContent='复制失败，请手动选择文本。'; }
  setTimeout(()=>{ b.textContent='复制'; b.classList.remove('copied'); },2000);
}


export function populateFilters(){
  const d=state.ins||{};
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


export function _expandCard(card){
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

export function _collapseCard(card){
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