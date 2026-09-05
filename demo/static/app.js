import { state } from './store.js';
import { apiFetch, authToken } from './api.js';
import { $, _collapseCard, _expandCard, animateValue, closeOverlay, copyDossier, esc, exportReport, pct, populateFilters, realColor, renderAnnot, renderBadge, renderBarh, renderDonut, renderForecast, renderMatrix, renderOrchestration, renderSourcingLoop, renderSuppliers, renderTrendLine, setStep, trendLabel, winRateCell, wrColor } from './render.js';

// 胜诉率单元格：decided=0 表示该维度尚无已判定案件（全是「待分析」），

// 不能直接显示 0%——那会读成「这个平台/地区全输」，实际只是还没判定。

// 数据源不再由顶部开关切换，改由登录态自动决定（store.js 中 source 为派生属性）：
//   - 未登录 → demo（演示布局，预置种子数据）
//   - 已登录 → real（AI 实算，数据按租户隔离）
// 所有数据接口仍经 apiFetch 附带 ?source=，无需前端手动维护。

// 统一给接口地址附加当前数据源（?source=）

// HTML 转义（P1-3）：所有动态文本拼进 innerHTML 前统一转义，杜绝 live 模型自由文本引发的 XSS

// 复制文本：优先 Clipboard API（需安全上下文 https / localhost），

// 非安全上下文（如 http 直连）静默失败时回退 execCommand，保证演示现场可用（B-前端 P1）。

// 同款一致性阈值（P2-4）：默认兜底 0.82，初始化时从 /api/config 拉取单一来源值

// 标签页切换（组件切换，不整页滑动，带动画）

export function switchTab(name){
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
    if(name==='supplier' && state.ins){renderSuppliers(state.ins);}
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

// 数字滚动动画（KPI 用）

// 通用横向条形图

// opts.absolute=true 时直接把 o.v 当 0-100 的百分比宽度（用于平台维权难度等本身已是比率的数据）

// 平台 × 供应商 交叉热力

// ===================== B组：时间序列趋势线 =====================

// ===================== B组：预测预警 =====================

// ===================== B组：选品避坑闭环 =====================

// 供应商透视：增强评分榜渲染（扩展 C）

// 供应商下钻：从已加载洞察本地计算（无额外接口）

// ============ 洞察报告导出（演示/交付：一键出报告，服务端生成 PDF 下载 / 复制文本） ============

// 单案举证：退货图叠加缺陷红框（P3-5：改为加载 /uploads 返回的 URL，而非内联 base64）

export async function loadInsights(){
  const status=$('#insStatus');
  status.textContent='加载中…'; status.classList.add('loading');
  const board=$('.board'); if(board){board.classList.remove('animated'); void board.offsetWidth; board.classList.add('animated');}
  try{
  const mode=state.source==='real'?'live':'mock', cat=$('#catSel').value, plat=$('#platSel').value;
  const reg=$('#regionSel').value, seas=$('#seasonSel').value;
  const qs=new URLSearchParams({mode});
  if(cat) qs.set('category',cat);
  if(plat) qs.set('platform',plat);
  if(reg) qs.set('region',reg);
  if(seas) qs.set('season',seas);
  const r=await apiFetch('/api/insights?'+qs.toString()); if(!r.ok) throw new Error('洞察接口 '+r.status);
  const d=await r.json();
  state.ins = d;  // 供供应商下钻本地计算
  // C组：real 源（登录态）未登录时显示登录门；已登录但 AI 仍在计算时显示加载态
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
        _load.innerHTML='<div style="text-align:center;padding:40px 20px"><div class="analyzing" style="display:inline-flex;justify-content:center;margin-bottom:14px"><span class="spin"></span><span>AI 正在计算洞察结果</span></div><p class="desc" style="margin:0">首次登录后需要运行 AI 聚类分析，通常需要 10–30 秒。</p></div>';
        _load.style.display='';
        const _b=document.querySelector('.board');
        if(_b) _b.insertBefore(_load, _b.firstChild);
      } else { _load.style.display=''; }
      return;
    }
    // 未登录 → 显示登录门
    if(_board) _board.classList.add('gated');
    const _lgm=document.getElementById('loginGateMsg');
    if(_lgm) _lgm.textContent=d.message||'请登录后查看 AI 实算数据';
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
  // 实算数据为空时给出引导（演示布局默认有种子，不会空）
  const emptyHint=$('#scopeTag');
  if(d.source==='real' && d.total_cases===0){
    emptyHint.textContent='实算数据为空 · 去「数据录入」添加';
    emptyHint.style.background='var(--warn)';
  }
  // 模式标签：登录态走 AI 实算；未登录为演示布局
  const isRealSource = state.source==='real';
  const modeLabel= isRealSource ? 'AI 实算' : '演示布局';
  $('#insModeTag').textContent=modeLabel+(d.error&&!isRealSource?' (已切回演示布局)':'');
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
  if(d.error) $('#report').textContent+='\n[提示] AI 实算失败，已切回演示布局：'+d.error;

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

export async function loadPlatforms(){
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

export async function doAnalyze(e){
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
    // P2-4 前端：阈值统一取自 /api/config（state.threshold），不再硬编码 0.82
    $('#simbar').style.background=d.similarity>=state.threshold?'var(--ok)':'var(--bad)';
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

// 结果模式徽标：mock=演示 / live=真实AI / mock(fallback)=真实AI(降级)

// P2 多模型协同编排链路：把单案取证的 6 项模型能力 + 1 项本地公式串成可视化链路，

// 每步如实显示「真实模型 / 回退演示 / 本地公式」，体现"网关渐进开通即生效"的设计。

// 一键复制举证材料（演示「可直接提交平台仲裁」）

// 用洞察响应填充顶部品类/平台/供应商筛选下拉（P3-2 复用一次响应）

// 加载「当前数据源」已录入案件列表（数据录入页右侧）——支持分页（A23：后端 /api/cases 分页信封）

export async function loadEntryList(page){
  if(page) state.entryPage = page;
  try{
    const r=await apiFetch(`/api/cases?slim=1&page=${state.entryPage}&page_size=${state.pageSize}`);
    const res=await r.json();
    const list=res.items||[];
    const wrap=$('#entryTableWrap');
    if(!list.length){ wrap.innerHTML='<span class="note">当前数据源暂无案件。</span>'; return; }
    const total=res.total||0;
    const totalPages=Math.max(1, Math.ceil(total/state.pageSize));
    let html='<table><thead><tr><th>SKU</th><th>品类</th><th>供应商</th><th>金额</th><th>判定</th><th></th></tr></thead><tbody>';
    list.slice().reverse().forEach(x=>{
      html+=`<tr><td>${esc(x.sku)}</td><td>${esc(x.category)}</td><td>${esc(x.supplier)}</td>`
        +`<td>¥${Number(x.amount||0).toFixed(0)}</td><td>${esc(x.outcome||'待分析')}</td>`
        +`<td><button class="entry-del" data-id="${esc(x.case_id)}">删除</button></td></tr>`;
    });
    html+='</tbody></table>';
    html+=`<div class="pager"><button id="prevPage" ${state.entryPage<=1?'disabled':''}>‹ 上一页</button>`
        +`<span class="pager-info">第 ${state.entryPage}/${totalPages} 页 · 共 ${total} 条</span>`
        +`<button id="nextPage" ${state.entryPage>=totalPages?'disabled':''}>下一页 ›</button></div>`;
    wrap.innerHTML=html;
    const prev=$('#prevPage'), next=$('#nextPage');
    if(prev) prev.onclick=()=>loadEntryList(Math.max(1, state.entryPage-1));
    if(next) next.onclick=()=>loadEntryList(Math.min(totalPages, state.entryPage+1));
  }catch(e){ $('#entryTableWrap').innerHTML='<span class="err">列表加载失败</span>'; }
}


// 提交一条手动录入案件到当前数据源

export async function submitEntry(e){
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
    if(!r.ok){ if(r.status===401){ openAuthModal(); } throw new Error(d.detail||'提交失败'); }
    $('#entryMsg').textContent='✓ 已添加到「'+(state.source==='real'?'真实案件库':'演示布局')+'」：'+d.case_id;
    $('#entryMsg').className='entry-msg ok';
    $('#entryForm').reset();
    loadEntryList(); loadInsights();  // 同步刷新列表与看板
  }catch(err){ $('#entryMsg').textContent='错误：'+err.message; $('#entryMsg').className='entry-msg err'; }
  finally{ btn.disabled=false; btn.textContent='添加到当前数据源'; }
}


// 文件导入（数据集 xlsx/csv）→ 按 case_id 去重 upsert 到「当前数据源」

export async function submitImport(){
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
    msg.textContent='✓ 导入完成（真实案件库），看板已刷新。'; msg.className='entry-msg ok';
    loadInsights(); loadEntryList();
  }catch(err){ msg.textContent='错误：'+err.message; msg.className='entry-msg err'; }
  finally{ btn.disabled=false; btn.textContent='导入并去重'; }
}


// 初始化：拉取后端常量（P2-4）→ 设定数据源 UI → 加载看板/筛选/举证包

(async function init(){
  try{
    const cfg=await fetch('/api/config'); const c=await cfg.json();
    if(typeof c.same_item_threshold==='number' && isFinite(c.same_item_threshold)) state.threshold=c.same_item_threshold;
    if(c.version) $('#appVer').textContent='V'+String(c.version).replace(/^v/i,'');
  }catch(e){ /* 网络异常则用默认 0.82 兜底 */ }

  // 清理旧版手动数据源开关的 localStorage 残留；source 现由登录态自动推导。
  localStorage.removeItem('rg_source');

  // 数据录入页提示：登录后写入租户真实案件库；未登录则提示需登录。
  $('#entryTarget').textContent='将写入：'+(state.source==='real'?'真实案件库':'请登录后录入');
  const banner=$('#entryBanner');
  if(state.source==='real'){
    banner.querySelector('.sb-body').textContent='⚠ 当前已登录：看板与录入均作用于您的租户真实案件库（与演示布局物理隔离）。';
    banner.classList.add('show'); banner.classList.remove('hidden');
  }

  await loadInsights();
  populateFilters();
  await loadPlatforms();
  if(state.source==='real') await loadEntryList();

})();


// 事件绑定

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
      if(r.status===401){ openAuthModal(); }
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

// 令牌存 localStorage（rg_token）。登录后 source 自动为 real，数据按当前租户隔离；

// 未登录为匿名（public 公共基准），source 自动为 demo（演示布局）。登录态在初始化与每次刷新看板后校验一次。

// 登录入口始终可见（P1-E）：未登录时可点登录进入 demo/demo123 演示账户体验 AI 实算。

export function updateAuthBtnVisibility(){
  const isReal = state.source==='real';
  const btn=$('#authBtn'), tag=$('#userTag');
  // P1-E：登录入口始终可见。demo 模式下用户须能登录预置 demo/demo123 账户，
  // 否则取证/录入（写入强制落 real 且需会话）会因找不到登录入口而卡死。
  // 登录态下按钮显示「退出」，未登录显示「登录」。
  if(btn) btn.style.display = '';
  // 租户标签：仅登录后展示（无论 demo/real），登出即隐藏
  if(tag){
    const hasToken = !!authToken();
    tag.style.display = hasToken ? 'inline-block' : 'none';
  }
}

export function updateAuthUI(){
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

export function openAuthModal(){
  $('#authOverlay').classList.add('show');
  $('#authMsg').textContent='';
  // a11y：打开即把焦点移入对话框首个可聚焦元素
  const u=$('#authUser'); if(u) setTimeout(()=>u.focus(),0);
}

export function closeAuthModal(){ $('#authOverlay').classList.remove('show'); }

export async function doAuth(e){
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
  $('#authHint').textContent = el.dataset.mode==='register' ? '注册即创建一个独立租户空间，AI 实算数据按租户隔离。' : '登录后查看按本租户隔离的 AI 实算数据；未登录时仅展示演示布局。';
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
