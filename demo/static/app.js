// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
import { state } from './store.js';
import { apiFetch, authToken } from './api.js';
import { $, _collapseCard, _expandCard, animateValue, closeOverlay, copyDossier, esc, exportReport, pct, populateFilters, realColor, renderAnnot, renderBadge, renderBarh, renderDonut, renderForecast, renderMatrix, renderOrchestration, renderSourcingLoop, renderSuppliers, renderTrendLine, setStep, trendLabel, winRateCell, wrColor } from './render.js';
import { t, setLang, applyI18n, currentLang } from './i18n.js';

// 胜诉率单元格：decided=0 表示该维度尚无已判定案件（全是「待分析」），

// 不能直接显示 0%——那会读成「这个平台/地区全输」，实际只是还没判定。

// 数据源不再由顶部开关切换，改由登录态自动决定（store.js 中 source 为派生属性）：
//   - 未登录 → demo（演示布局，预置种子数据）
//   - 已登录 → real（AI 实算，数据按租户隔离）
// 所有数据接口仍经 apiFetch 附带 ?source=，无需前端手动维护。

// 统一给接口地址附加当前数据源（?source=）

// P2-6 骨架屏：首屏数据抵达前显示 shimmer 占位；各渲染函数覆盖 innerHTML 后自然消失。
// 仅在首次 loadInsights 注入，避免筛选刷新时的不必要闪烁。
const SKELETON_TARGETS = ['#catBars','#platBars','#regionBars','#seasonBars','#supBars',
  '#rootDist','#costKpis','#forecastKpis','#matrixHeat','#trendLine','#sourcingLoop','#advice',
  '#catTbl','#platTbl','#regionTbl','#seasonTbl','#skuTbl'];
let _skelShown = false;
function showSkeletons(){
  SKELETON_TARGETS.forEach(s=>{
    const el=$(s); if(!el) return;
    if(el.tagName==='TABLE'){
      const tb=el.querySelector('tbody');
      if(tb) tb.innerHTML='<tr><td colspan="8"><div class="skel-row"><div class="skel w90"></div><div class="skel w70"></div></div></td></tr>';
    } else {
      el.innerHTML='<div class="skel-row"><div class="skel w90"></div><div class="skel w70"></div><div class="skel w50"></div></div>';
    }
  });
  ['#kTotal','#kRefund','#kWin','#kDisp'].forEach(id=>{const e=$(id); if(e) e.classList.add('loading');});
}
function clearSkeletons(){
  ['#kTotal','#kRefund','#kWin','#kDisp'].forEach(id=>{const e=$(id); if(e) e.classList.remove('loading');});
}

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


// 新手体验指引横幅（P0-2）：可关闭（仅会话内，刷新即重现），步骤 2 可点击跳转

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


// ===================== 首次开启引导（onboarding）=====================
// 目的：让第一次打开的人 30 秒内明白「这是什么 / 数据从哪来 / 五个页面怎么用 /
// 哪些结论是真 AI / 边界在哪」，避免把演示种子当成真实业务数据、或把回退结果当成 AI 结论。
//
// 行为：
//   - 首次访问（localStorage 无 rg_onboarded=1）自动展示；
//   - 「跳过引导」「开始使用」「×」都关闭；勾选「不再自动显示」时写 rg_onboarded=1，
//     取消勾选则写 0（下次仍自动展示）；
//   - 顶栏「使用引导」按钮可随时重开，且不改动该标记；
//   - Esc 关闭；第 3 步的标签按钮可直接跳转对应页面。

const ONBOARD_KEY = 'rg_onboarded';
const ONB_TOTAL = 5;
// 后端能力矩阵的展示顺序（键与 providers.CAPABILITIES 一致）
const ONB_CAPS = ['text', 'vl', 'ocr', 'embed', 'rerank', 'tts'];
let onbStep = 1;

// 能力 → 本地化名。刻意写成 switch 而不是 `t('cap.'+cap)`：字面量调用才能被
// scripts/check_i18n.py 静态扫描到，从而保证新增能力时不会漏翻译。
function capLabel(cap){
  switch(cap){
    case 'text': return t('cap.text');
    case 'vl': return t('cap.vl');
    case 'ocr': return t('cap.ocr');
    case 'embed': return t('cap.embed');
    case 'rerank': return t('cap.rerank');
    case 'tts': return t('cap.tts');
    default: return cap;
  }
}

function onbEl(id){ return document.getElementById(id); }

export function renderOnbAiInfo(){
  const box = onbEl('onbAi');
  if(!box) return;
  const p = state.cfg && state.cfg.provider;
  if(!p){ box.textContent = ''; return; }
  const caps = ONB_CAPS.filter(cap => p.capabilities && p.capabilities[cap]).map(capLabel);
  // 模板来自本地字典（可信），插值来自后端（不可信）→ 整体经 esc() 转义后再插入
  box.innerHTML =
    `<div>${esc(t('onb.ai.provider').replace('{p}', p.label || p.key || ''))}</div>` +
    `<div>${esc(t('onb.ai.caps').replace('{list}', caps.length ? caps.join(' / ') : '—'))}</div>` +
    `<div>${esc(t('onb.ai.fallback'))}</div>`;
}

export function renderOnboardStep(){
  const ov = onbEl('onboardOverlay');
  if(!ov) return;
  ov.querySelectorAll('.onb-step').forEach(s => {
    s.classList.toggle('active', Number(s.dataset.step) === onbStep);
  });
  const dots = onbEl('onbDots');
  if(dots){
    dots.innerHTML = Array.from({length: ONB_TOTAL}, (_, i) =>
      `<i class="${i + 1 === onbStep ? 'on' : ''}"></i>`).join('');
  }
  const no = onbEl('onbStepNo');
  if(no) no.textContent = t('onb.stepOf').replace('{i}', String(onbStep)).replace('{n}', String(ONB_TOTAL));
  const prev = onbEl('onbPrev');
  const next = onbEl('onbNext');
  if(prev) prev.disabled = onbStep === 1;
  if(next) next.textContent = onbStep === ONB_TOTAL ? t('onb.start') : t('onb.next');
  // 第 4 步的「当前 AI 平台 / 真实可用能力」需要 /api/config 的 provider 字段
  if(onbStep === 4) renderOnbAiInfo();
}

export function openOnboard(){
  const ov = onbEl('onboardOverlay');
  if(!ov) return;
  onbStep = 1;
  renderOnboardStep();
  ov.classList.add('show');
}

export function closeOnboard(){
  const ov = onbEl('onboardOverlay');
  if(ov) ov.classList.remove('show');
}

function finishOnboard(){
  const chk = onbEl('onbDontShow');
  try{ localStorage.setItem(ONBOARD_KEY, chk && chk.checked ? '1' : '0'); }catch(_){ /* 隐私模式忽略 */ }
  closeOnboard();
}

(function initOnboarding(){
  const ov = onbEl('onboardOverlay');
  if(!ov) return;
  const skip = onbEl('onbSkip'), close = onbEl('onbClose');
  if(skip) skip.addEventListener('click', finishOnboard);
  if(close) close.addEventListener('click', finishOnboard);
  const prev = onbEl('onbPrev');
  if(prev) prev.addEventListener('click', () => { if(onbStep > 1){ onbStep--; renderOnboardStep(); } });
  const next = onbEl('onbNext');
  if(next) next.addEventListener('click', () => {
    if(onbStep < ONB_TOTAL){ onbStep++; renderOnboardStep(); } else { finishOnboard(); }
  });
  // 第 3 步：点标签直接跳到对应页面并结束引导（减少"看完还要自己找"的摩擦）
  ov.querySelectorAll('.onb-tabs button[data-go]').forEach(b => b.addEventListener('click', () => {
    switchTab(b.dataset.go);
    finishOnboard();
  }));
  // 点遮罩空白处关闭（与其它弹窗一致）
  ov.addEventListener('click', e => { if(e.target === ov) finishOnboard(); });
  // Esc：优先关引导（引导常在登录框之上）
  document.addEventListener('keydown', e => {
    if(e.key === 'Escape' && ov.classList.contains('show')){ e.stopPropagation(); finishOnboard(); }
  });
  const gb = onbEl('guideBtn');
  if(gb) gb.addEventListener('click', openOnboard);
})();

// 首启判定：仅在「未标记过」时自动打开；标记为 '0'（用户取消勾选）时依然展示
function maybeAutoOpenOnboard(){
  let seen = null;
  try{ seen = localStorage.getItem(ONBOARD_KEY); }catch(_){ /* 隐私模式：默认展示一次 */ }
  if(seen !== '1') openOnboard();
}


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
  status.textContent=t('st.loading'); status.classList.add('loading');
  if(!_skelShown){ showSkeletons(); _skelShown=true; }
  const board=$('.board'); if(board){board.classList.remove('animated'); void board.offsetWidth; board.classList.add('animated');}
  try{
  const mode=state.source==='real'?'live':'mock', cat=$('#catSel').value, plat=$('#platSel').value;
  const reg=$('#regionSel').value, seas=$('#seasonSel').value;
  const qs=new URLSearchParams({mode});
  if(cat) qs.set('category',cat);
  if(plat) qs.set('platform',plat);
  if(reg) qs.set('region',reg);
  if(seas) qs.set('season',seas);
  const r=await apiFetch('/api/insights?'+qs.toString()); if(!r.ok) throw new Error(t('st.insightsApi')+' '+r.status);
  const d=await r.json();
  state.ins = d;  // 供供应商下钻本地计算
  // C组：real 源（登录态）未登录时显示登录门；已登录但 AI 仍在计算时显示加载态
  const _board=document.querySelector('.board');
  if(d.requires_login){
    // 已有令牌说明用户已登录，API 仍返回 requires_login 说明 AI 正在计算（或租户初始化中）→ 显示加载态而非登录门
    if(authToken()){
      if(_board){ _board.classList.remove('gated'); }
      const _lgm=document.getElementById('loginGateMsg');
      if(_lgm){ _lgm.textContent=t('st.computing'); }
      status.textContent=t('st.calculating'); status.classList.add('loading');
      // 显示加载卡片而非登录门
      const _gate=document.getElementById('loginGate');
      if(_gate){ _gate.style.display='none'; }
      // 显示一个全宽加载提示
      let _load=document.getElementById('computingHint');
      if(!_load){
        _load=document.createElement('div'); _load.id='computingHint';
        _load.className='card';
        _load.innerHTML='<div style="text-align:center;padding:40px 20px"><div class="analyzing" style="display:inline-flex;justify-content:center;margin-bottom:14px"><span class="spin"></span><span>'+t('st.computingTitle')+'</span></div><p class="desc" style="margin:0">'+t('st.computingHint')+'</p></div>';
        _load.style.display='';
        const _b=document.querySelector('.board');
        if(_b) _b.insertBefore(_load, _b.firstChild);
      } else { _load.style.display=''; }
      return;
    }
    // 未登录 → 显示登录门
    if(_board) _board.classList.add('gated');
    const _lgm=document.getElementById('loginGateMsg');
    if(_lgm) _lgm.textContent=d.message||t('st.needLoginData');
    status.textContent=t('st.needLogin'); status.classList.remove('loading');
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
    emptyHint.textContent=t('st.realEmpty');
    emptyHint.style.background='var(--warn)';
  }
  // 模式标签：登录态走 AI 实算；未登录为演示布局
  const isRealSource = state.source==='real';
  const modeLabel= isRealSource ? t('rep.live') : t('rep.mock');
  $('#insModeTag').textContent=modeLabel+(d.error&&!isRealSource?' '+t('st.fallbackTag'):'');
  $('#insModeTag').style.background=isRealSource?'var(--ok)':'var(--warn)';
  $('#scopeTag').textContent=(cat?cat+' / ':'')+(plat||t('rep.allPlatforms'))+(reg?' / '+reg:'')+(seas?' / '+seas:'');

  // KPI（带动画）
  animateValue($('#kTotal'), d.total_cases, v=>Math.round(v).toLocaleString());
  animateValue($('#kRefund'), d.total_refund||0, v=>Number(v).toLocaleString(t('locale'),{maximumFractionDigits:2}));
  $('#kWin').style.color=wrColor(d.win_rate||0);
  animateValue($('#kWin'), d.win_rate||0, v=>pct(v));
  $('#kDisp').style.color='var(--bad)';
  animateValue($('#kDisp'), d.avg_dispute_rate||0, v=>pct(v));
  const note=d.dispute_rate_note||t('st.disputeNote');
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
    div.innerHTML=`<div style="font-size:12px;display:flex;justify-content:space-between"><span>${esc(k)}</span><span>${v} ${t('dyn.unitCases')}</span></div>`
      +`<div class="bar"><i style="width:${Math.round(v/rmax*100)}%;background:var(--warn)"></i></div>`;
    rd.appendChild(div);
  });
  $('#rootCause').textContent=d.root_cause||'-';

  // ③ 供应商红黑榜
  const sc=d.supplier_scorecard||[];
  const black=sc.filter(s=>s.level==='高风险');
  const red=sc.slice(-3).reverse();
  const sg=$('#supBlack'); sg.innerHTML='<div style="font-size:12px;color:var(--bad);font-weight:600">'+t('st.blackList')+'</div>';
  (black.length?black:sc.slice(0,1)).forEach(s=>{
    const div=document.createElement('div'); div.className='sup'; div.style.borderColor='var(--bad)';
    div.innerHTML=`<span><b style="color:var(--txt)">${esc(s.supplier)}</b> ${esc(s.name)}<br><span style="color:var(--txt3);font-size:11px">${t('m.defectRate')}${pct(s.defect_rate)} · ${t('m.winRate')}${pct(s.win_rate)} · ${s.cases}${t('dyn.unitCases')}</span></span>`
      +`<span class="pill" style="background:var(--bad)">${t('m.quality')} ${s.quality_score}</span>`;
    sg.appendChild(div);
  });
  const sr=$('#supRed'); sr.innerHTML='<div style="font-size:12px;color:var(--ok);font-weight:600">'+t('st.redList')+'</div>';
  red.forEach(s=>{
    const div=document.createElement('div'); div.className='sup'; div.style.borderColor='var(--ok)';
    div.innerHTML=`<span><b style="color:var(--txt)">${esc(s.supplier)}</b> ${esc(s.name)}<br><span style="color:var(--txt3);font-size:11px">${t('m.defectRate')}${pct(s.defect_rate)} · ${t('m.winRate')}${pct(s.win_rate)} · ${s.cases}${t('dyn.unitCases')}</span></span>`
      +`<span class="pill" style="background:var(--ok)">${t('m.quality')} ${s.quality_score}</span>`;
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
  if(!(d.anomaly_alerts||[]).length) al.innerHTML='<span class="note">'+t('st.noAnomaly')+'</span>';

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
  (d.sourcing_advice||d.recommendations||[]).forEach(tt=>{
    const div=document.createElement('div'); div.style.cssText='background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:10px;margin-top:8px;font-size:13px;color:var(--txt)';
    div.textContent='▸ '+tt; adv.appendChild(div);
  });
  if(d.error) $('#report').textContent+='\n'+t('st.liveFailHint')+d.error;

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
    `<div class="kv"><span>${t('m.logistics')}（${t('rep.est')}）</span><b>¥${Number(d.logistics_cost||0).toLocaleString(t('locale'),{maximumFractionDigits:0})}</b></div>`
    +`<div class="kv"><span>${t('m.returnCost')}（${t('rep.refundPlusShip')}）</span><b>¥${Number(d.total_return_cost||0).toLocaleString(t('locale'),{maximumFractionDigits:0})}</b></div>`;
  const bl=$('#blacklist'); bl.innerHTML='<div style="font-size:12px;color:var(--bad);font-weight:600">'+t('st.blacklistTop')+'</div>';
  const blacks=d.supplier_blacklist||[];
  if(blacks.length){
    blacks.forEach(s=>{
      const div=document.createElement('div'); div.className='sup'; div.style.borderColor='var(--bad)';
      div.innerHTML=`<span><b style="color:var(--txt)">${esc(s.supplier)}</b> ${esc(s.name)}<br><span style="color:var(--txt3);font-size:11px">${esc(s.reason)}</span></span>`
        +`<span class="pill" style="background:var(--bad)">${s.quality_score}</span>`;
      bl.appendChild(div);
    });
  } else {
    bl.innerHTML+='<span class="note">'+t('st.noBlacklist')+'</span>';
  }

  // ⑯⑰⑱ B组：时间序列 / 预测预警 / 选品避坑闭环
  renderTrendLine($('#trendLine'), d.time_series||[], d.forecast||{});
  $('#trendNote').textContent = (d.time_series&&d.time_series.length)
    ? `${t('st.trendMonths')} ${d.time_series.length} ${t('st.months')}；${t('dyn.trend')} ${trendLabel((d.forecast||{}).trend)}`
    : t('st.noDatedCases');
  renderForecast($('#forecastKpis'), $('#forecastList'), $('#forecastAlerts'), d.forecast||{}, d.forecast_alerts||[]);
  renderSourcingLoop($('#sourcingLoop'), d.sourcing_checklist||[]);

  // 图形化
  renderBarh($('#catBars'), (d.category_heatmap||[]).map(x=>({label:x.category,v:x.refund,text:'¥'+x.refund,color:'#fbbf24'})));
  renderBarh($('#platBars'), (d.platform_view||[]).map(x=>({label:x.platform,v:Math.round((x.win_rate||0)*100),text:pct(x.win_rate),color:realColor(x.win_rate||0)})), {absolute:true});
  renderBarh($('#supBars'), (d.supplier_scorecard||[]).map(x=>({label:x.supplier,v:x.quality_score,text:String(x.quality_score),color:x.level==='高风险'?'#fb7185':x.level==='优质'?'#4ade80':'#facc15'})));
  renderMatrix($('#matrixHeat'), d.platform_supplier_matrix||[]);
  renderSuppliers(d);
  renderDonut($('#kWinDonut'), d.win_rate||0);
  syncRoi(d);  // ROI 面板接入真实看板数据（客单价/争议占比/胜诉率口径）
  syncRoiBacktest(d);  // ROI 真实回测区间（后端基于真实聚合值，三档情景 + 敏感性）
  status.textContent=t('st.updated')+' · '+new Date().toLocaleTimeString(t('locale'),{hour:'2-digit',minute:'2-digit'});
  status.classList.remove('loading');
  clearSkeletons();
  }catch(e){ status.textContent=t('st.loadFail'); status.classList.remove('loading'); clearSkeletons(); console.error('loadInsights 出错', e); }
}


// 平台适配举证包（交付物 A）渲染

export async function loadPlatforms(){
  try{
    const r=await fetch('/api/platforms'); const d=await r.json();
    const ps=d.platforms||[];
    const attrs=[['return_window',t('plat.returnWindow')],['response_window',t('plat.responseWindow')],['shipping_payer',t('plat.shippingPayer')],['burden_bias',t('plat.burdenBias')]];
    let html='<tr><th>'+t('plat.dim')+'</th>'+ps.map(p=>`<th>${esc(p.label)}</th>`).join('')+'</tr>';
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
        +`<span class="plat-hint">${t('plat.burdenBias')}：${esc(p.burden_bias||'-')}</span>`
        +`<span class="plat-arrow" aria-hidden="true">▸</span>`
        +`</button>`
        +`<div class="plat-body">`
        +`<div class="kv"><span>${t('plat.returnWindow')}</span><b>${esc(p.return_window)}</b></div>`
        +`<div class="kv"><span>${t('plat.responseWindow')}</span><b>${esc(p.response_window)}</b></div>`
        +`<div class="kv"><span>${t('plat.shippingPayer')}</span><b>${esc(p.shipping_payer)}</b></div>`
        +`<div class="kv"><span>${t('plat.burdenBias')}</span><b>${esc(p.burden_bias)}</b></div>`
        +`<div style="font-size:12px;color:var(--txt3);margin-top:10px">${t('plat.requiredEvidence')}</div><ul class="ev">${p.required_evidence.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`
        +`<div style="font-size:12px;color:var(--txt3);margin-top:8px">${t('plat.lossReasons')}</div><ul class="ev bad">${p.common_loss_reasons.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`
        +`<div style="font-size:12px;color:var(--txt3);margin-top:8px">${t('plat.specialClauses')}</div><ul class="ev dim">${(p.special_clauses||[]).map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`
        +`<div style="font-size:12px;color:var(--txt3);margin-top:8px">${t('plat.howWeHelp')}</div><ul class="ev cap">${capItems}</ul>`
        +`</div></div>`;
    });
    $('#platTmpl').innerHTML=tmpl;
  }catch(e){ $('#platCmp').innerHTML='<span class="err">'+t('plat.loadFail')+'</span>'; }
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

// 当前取证请求的 AbortController（P1-4：长分析可取消 / 超时熔断）
let analyzeCtrl=null;
const ANALYZE_TIMEOUT_MS=180000;  // live 模式最迟 3 分钟未响应即主动中止，避免永久卡死

export async function doAnalyze(e){
  e.preventDefault();
  $('#err').textContent=''; $('#res').classList.add('hide'); $('#resEmpty').classList.add('hide');
  $('#modeBadge').classList.add('hide');
  const btn=$('#btn'); btn.disabled=true; btn.textContent=t('an.running');
  // 分析中状态：live 模式耗时长，明确提示避免误以为卡死
  const fd=new FormData($('#f'));
  $('#analyzing').classList.remove('hide');
  $('#analyzingText').textContent = fd.get('mode')==='live' ? t('an.liveHint') : t('an.mockHint');
  setStep(2);
  // P1-4：可取消 + 超时自中止（live 视觉调用可能较久）
  analyzeCtrl=new AbortController();
  const timer=setTimeout(()=>{ if(analyzeCtrl) analyzeCtrl.abort(); }, ANALYZE_TIMEOUT_MS);
  $('#btnCancelAnalyze').onclick=()=>{ if(analyzeCtrl) analyzeCtrl.abort(); };
  try{
    const r=await apiFetch('/api/analyze',{method:'POST',body:fd,signal:analyzeCtrl.signal});
    const d=await r.json().catch(()=>({}));
    // 取证是写接口，匿名会被 401 拒：弹出登录框衔接上，而不是只留一行"请先登录"红字
    if(!r.ok){
      if(r.status===401){ openAuthModal(); throw new Error(t('an.needLogin')); }
      throw new Error(d.detail||t('an.requestFail'));
    }
    $('#sim').textContent=Math.round(d.similarity*100)+'%';
    $('#simbar').style.width=Math.round(d.similarity*100)+'%';
    // P2-4 前端：阈值统一取自 /api/config（state.threshold），不再硬编码 0.82
    $('#simbar').style.background=d.similarity>=state.threshold?'var(--ok)':'var(--bad)';
    $('#same').textContent=d.same_item?t('an.sameItem'):t('an.swapped');
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
    // 母语语音：展示本单陈述语言与音色（后端返回 language/voice；mock 亦有）
    const vl=$('#voiceLang');
    if(vl) vl.textContent=(d.language||'zh')+' · '+(d.voice||'-');
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
    const cb=$('#copyDossier'); cb.textContent=t('dyn.copy'); cb.classList.remove('copied');
    state.lastAnalyze = d;  // 供切换语言后重渲染模式徽标与编排链路（dossier/语音为后端数据，不随语言变）
    $('#res').classList.remove('hide');
  }catch(err){
    $('#analyzing').classList.add('hide'); setStep(1);
    // P1-4：区分主动取消/超时与真实错误
    if(err && err.name==='AbortError'){
      $('#err').textContent=t('an.aborted');
    } else {
      $('#err').textContent=t('dyn.errorPrefix')+err.message;
    }
  }
  finally{
    clearTimeout(timer); analyzeCtrl=null;
    btn.disabled=false; btn.textContent=t('an.start');
  }
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
    if(!list.length){ wrap.innerHTML='<span class="note">'+t('ent.empty')+'</span>'; return; }
    const total=res.total||0;
    const totalPages=Math.max(1, Math.ceil(total/state.pageSize));
    let html='<table><thead><tr><th>SKU</th><th>'+t('m.category')+'</th><th>'+t('ent.supplier')+'</th><th>'+t('ent.amount')+'</th><th>'+t('ent.verdict')+'</th><th></th></tr></thead><tbody>';
    list.forEach(x=>{
      html+=`<tr><td>${esc(x.sku)}</td><td>${esc(x.category)}</td><td>${esc(x.supplier)}</td>`
        +`<td>¥${Number(x.amount||0).toFixed(0)}</td><td>${esc(x.outcome||t('dyn.pendingShort'))}</td>`
        +`<td><button class="entry-del" data-id="${esc(x.case_id)}">${t('ent.delete')}</button></td></tr>`;
    });
    html+='</tbody></table>';
    html+=`<div class="pager"><button id="prevPage" ${state.entryPage<=1?'disabled':''}>‹ ${t('ent.prev')}</button>`
        +`<span class="pager-info">${t('ent.page')} ${state.entryPage}/${totalPages} · ${t('ent.total')} ${total}</span>`
        +`<button id="nextPage" ${state.entryPage>=totalPages?'disabled':''}>${t('ent.next')} ›</button></div>`;
    wrap.innerHTML=html;
    const prev=$('#prevPage'), next=$('#nextPage');
    if(prev) prev.onclick=()=>loadEntryList(Math.max(1, state.entryPage-1));
    if(next) next.onclick=()=>loadEntryList(Math.min(totalPages, state.entryPage+1));
  }catch(e){ $('#entryTableWrap').innerHTML='<span class="err">'+t('ent.loadFail')+'</span>'; }
}


// 提交一条手动录入案件到当前数据源

export async function submitEntry(e){
  e.preventDefault();
  const btn=$('#entryBtn'); btn.disabled=true; btn.textContent=t('ent.submitting');
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
    if(!r.ok){ if(r.status===401){ openAuthModal(); } throw new Error(d.detail||t('ent.submitFail')); }
    $('#entryMsg').textContent='✓ '+t('ent.added')+'「'+(state.source==='real'?t('ent.realDb'):t('rep.mock'))+'」：'+d.case_id;
    $('#entryMsg').className='entry-msg ok';
    $('#entryForm').reset();
    loadEntryList(); loadInsights();  // 同步刷新列表与看板
  }catch(err){ $('#entryMsg').textContent=t('dyn.errorPrefix')+err.message; $('#entryMsg').className='entry-msg err'; }
  finally{ btn.disabled=false; btn.textContent=t('ent.submit'); }
}


// 文件导入（数据集 xlsx/csv）→ 按 case_id 去重 upsert 到「当前数据源」

export async function submitImport(){
  const btn=$('#importBtn'); const f=$('#importFile'); const msg=$('#importMsg'); const res=$('#importResult');
  msg.textContent=''; msg.className='entry-msg'; res.innerHTML='';
  if(!f.files || !f.files.length){ msg.textContent=t('imp.pickFile'); msg.className='entry-msg err'; return; }
  btn.disabled=true; btn.textContent=t('imp.importing');
  try{
    const fd=new FormData();
    fd.append('file', f.files[0]);
    const r=await apiFetch('/api/import_file',{method:'POST',body:fd});
    const d=await r.json();
    // 匿名写入 -> 401：弹登录框而不是只抛一行错误，避免演示卡在"点了没反应"
    if(r.status===401){ openAuthModal(); throw new Error(t('imp.needLogin')); }
    if(!r.ok || !d.ok) throw new Error(d.error||d.detail||t('imp.fail'));
    res.innerHTML =
      '<div>'+t('imp.detected')+'<span class="v">'+esc(d.detected||t('imp.unknown'))+'</span></div>'+
      '<div><span class="k">'+t('imp.added')+'</span> <span class="v">'+d.imported+'</span>　'+
      '<span class="k">'+t('imp.updated')+'</span> <span class="v upd">'+d.updated+'</span>　'+
      '<span class="k">'+t('imp.skipped')+'</span> <span class="v skip">'+d.skipped+'</span>　'+
      '<span class="k">'+t('imp.dupInFile')+'</span> <span class="v skip">'+d.file_duplicates+'</span></div>';
    if(d.errors && d.errors.length){ res.innerHTML += '<div class="k">'+t('imp.hint')+esc(d.errors.slice(0,5).join('；'))+'</div>'; }
    msg.textContent='✓ '+t('imp.done'); msg.className='entry-msg ok';
    loadInsights(); loadEntryList();
  }catch(err){
    msg.textContent=t('dyn.errorPrefix')+err.message; msg.className='entry-msg err';
  }
  finally{ btn.disabled=false; btn.textContent=t('imp.submit'); }
}


// CSV 文本粘贴导入 → POST /api/import_csv（与文件导入并列的第二个数据回流入口）

export async function submitCsvImport(){
  const btn=$('#importCsvBtn'); const ta=$('#importCsvText'); const msg=$('#importMsg'); const res=$('#importResult');
  msg.textContent=''; msg.className='entry-msg'; res.innerHTML='';
  const csv=(ta.value||'').trim();
  if(!csv){ msg.textContent=t('imp.pasteCsv'); msg.className='entry-msg err'; return; }
  btn.disabled=true; btn.textContent=t('imp.parsing');
  try{
    const fd=new FormData();
    fd.append('csv_text', csv);
    const r=await apiFetch('/api/import_csv',{method:'POST',body:fd});
    const d=await r.json();
    if(!r.ok){
      // 匿名 -> 401：直接弹出登录框，而不是只留一行错误（否则演示链路断在这里）
      if(r.status===401){ openAuthModal(); throw new Error(t('imp.needLogin')); }
      throw new Error(d.detail||d.error||t('imp.fail'));
    }
    const skipped=d.skipped||0, errs=d.errors||[];
    res.innerHTML =
      '<div><span class="k">'+t('imp.added')+'</span> <span class="v">'+d.imported+'</span>　'+
      '<span class="k">'+t('imp.skippedCsv')+'</span> <span class="v skip">'+skipped+'</span></div>'+
      (errs.length ? '<div class="k">'+t('imp.hint')+esc(errs.slice(0,5).join('；'))+'</div>' : '');
    msg.textContent = d.imported>0
      ? '✓ '+t('imp.importedN').replace('{n}', d.imported)
      : t('imp.nothingImported');
    msg.className = d.imported>0 ? 'entry-msg ok' : 'entry-msg err';
    if(d.imported>0){ ta.value=''; loadInsights(); loadEntryList(); }
  }catch(err){
    msg.textContent=t('dyn.errorPrefix')+err.message; msg.className='entry-msg err';
  }
  finally{ btn.disabled=false; btn.textContent=t('imp.submitCsv'); }
}


// 导入方式分段切换：上传文件 / 粘贴 CSV

export function switchImportPane(which){
  document.querySelectorAll('.imp-tab').forEach(b=>b.classList.toggle('active', b.dataset.imp===which));
  $('#impPaneFile').classList.toggle('hide', which!=='file');
  $('#impPaneText').classList.toggle('hide', which!=='text');
}


// 初始化：拉取后端常量（P2-4）→ 设定数据源 UI → 加载看板/筛选/举证包

(async function init(){
  try{
    const cfg=await fetch('/api/config'); const c=await cfg.json();
    state.cfg=c;  // 首启引导第 4 步要展示「当前 AI 平台 + 真实可用能力」，故整份配置留存
    if(typeof c.same_item_threshold==='number' && isFinite(c.same_item_threshold)) state.threshold=c.same_item_threshold;
    if(c.version) $('#appVer').textContent='V'+String(c.version).replace(/^v/i,'');
    // P1-15：供应商花名册由后端 /api/config 单一来源下发，前端不再内嵌硬编码副本
    if(c.suppliers && typeof c.suppliers==='object') state.supplierNames=c.suppliers;
    // 母语语音：可选语言清单（语言→展示名/音色）由后端下发，前端不硬编码
    if(Array.isArray(c.languages) && c.languages.length) state.languages=c.languages;
    if(c.default_language) state.defaultLanguage=c.default_language;
  }catch(e){ /* 网络异常则用默认 0.82 兜底 */ }

  // 清理旧版手动数据源开关的 localStorage 残留；source 现由登录态自动推导。
  localStorage.removeItem('rg_source');

  // P2-7 i18n：恢复上次语言偏好并应用到可见标签
  try {
    setLang(currentLang());
    const langSel = document.getElementById('langSel');
    if (langSel) langSel.value = currentLang();
    applyI18n();
  } catch (e) { /* i18n 失败不阻断主流程 */ }

  // 首启引导：首次访问自动展示（语言与配置已就绪，文案不会出现裸 key）
  maybeAutoOpenOnboard();

  // 数据录入页提示：登录后写入租户真实案件库；未登录则提示需登录。
  $('#entryTarget').textContent=t('ent.willWrite')+(state.source==='real'?t('ent.realDb'):t('ent.needLoginToAdd'));
  const banner=$('#entryBanner');
  if(state.source==='real'){
    banner.querySelector('.sb-body').textContent=t('ent.loggedInBanner');
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

// P2-7 i18n：切换界面语言（zh / en），持久化偏好并即时刷新可见标签
(function initI18nSwitch(){
  const sel=document.getElementById('langSel');
  if(!sel) return;
  sel.addEventListener('change',()=>{
    setLang(sel.value);
    applyI18n();
    // 看板/供应商/平台举证包/筛选下拉均由 JS 动态渲染（文案走 t()），
    // 切语言后必须重渲染，否则动态区块仍是旧语言。
    populateFilters();
    loadInsights();
    loadPlatforms();
    // 单案取证结果的模式徽标与编排链路也重渲染（dossier/语音文本为后端数据，不随语言变）
    if(state.lastAnalyze){ renderBadge(state.lastAnalyze.mode); renderOrchestration(state.lastAnalyze); }
    // 首启引导若正开着，步骤标题/正文/按钮/页码都要跟着换语言
    renderOnboardStep();
  });
})();

$('#ovClose').addEventListener('click',closeOverlay);

$('#overlay').addEventListener('click',e=>{if(e.target.id==='overlay')closeOverlay();});

document.addEventListener('keydown',e=>{if(e.key==='Escape')closeOverlay();});

// 切换到「数据录入」页时加载列表

document.querySelectorAll('.tabs button').forEach(b=>b.addEventListener('click',()=>{ if(b.dataset.tab==='entry') loadEntryList(); }));

// 列表内删除（事件委托）

$('#entryTableWrap').addEventListener('click',async e=>{
  const btn=e.target.closest('.entry-del'); if(!btn) return;
  const id=btn.dataset.id;
  if(!confirm(t('ent.confirmDel').replace('{id}', id))) return;
  btn.disabled=true; btn.textContent=t('ent.deleting');
  try{
    const r=await apiFetch('/api/cases/'+encodeURIComponent(id),{method:'DELETE'});
    if(r.ok){
      loadEntryList(); loadInsights();
    } else {
      if(r.status===401){ openAuthModal(); }
      const d=await r.json().catch(()=>({}));
      btn.textContent=t('ent.delFail');
      if($('#entryErr')) $('#entryErr').textContent=t('ent.delFail')+'：'+(d.detail||r.status);
      setTimeout(()=>{ btn.textContent=t('ent.delete'); },2000);
    }
  }catch(err){
    btn.textContent=t('ent.delFail');
    if($('#entryErr')) $('#entryErr').textContent=t('ent.delFail')+'：'+((err&&err.message)||t('dyn.netErr'));
    setTimeout(()=>{ btn.textContent=t('ent.delete'); },2000);
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
        tag.textContent=t('ent.tenant')+d.user.username; tag.style.display='inline-block';
        btn.textContent=t('btn.logout'); btn.classList.add('authed');
      } else {
        localStorage.removeItem('rg_token'); tag.style.display='none'; btn.textContent=t('btn.login'); btn.classList.remove('authed');
      }
      updateAuthBtnVisibility();
    }).catch(()=>{ updateAuthBtnVisibility(); });
  } else {
    tag.style.display='none'; btn.textContent=t('btn.login'); btn.classList.remove('authed');
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
  const isReg = el.dataset.mode==='register';
  // 按钮文案随「要切换到的模式」而变：当前在注册态 → 显示「登录」入口；反之显示「注册」入口。
  el.textContent = isReg ? t('auth.login') : t('auth.register');
  $('#authSubmit').textContent = isReg ? t('auth.register') : t('auth.login');
  $('#authTenantWrap').style.display = isReg ? 'flex' : 'none';
  $('#authHint').textContent = isReg ? t('auth.hintReg') : t('auth.hintLogin');
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
    document.getElementById('roiSave').textContent='¥'+Math.round(save).toLocaleString(t('locale'));
    document.getElementById('roiTime').textContent='¥'+Math.round(wageSave).toLocaleString(t('locale'));
  }
  ['roiQty','roiPrice','roiDisp','roiGain','roiWage'].forEach(function(id){
    var el=document.getElementById(id); if(el) el.addEventListener('input', calcROI);
  });
  calcROI();

  // ROI 面板接入真实看板数据（N6）：把「平均客单价（退款/案件数）/ 争议占比（代理嫌疑率）」
  // 按当前看板真实值填入并标注来源；「年退货量 / 胜诉率提升 / 时薪」保留为可调假设
  // （无历史基线可填）。由 loadInsights 成功后调用，保证测算与看板同源。
  // ROI 真实回测区间：后端 roi_backtest 基于已沉淀案件的真实聚合值算出三档情景。
  // 与上方「交互式测算」的区别：这里是**真实案件量 × 真实争议占比**，只把胜诉率提升当假设；
  // 上方是全假设的what-if。两者并列展示，避免把假设值说成实测收益。
  function syncRoiBacktest(d){
    const wrap=document.getElementById('roiBacktest');
    if(!wrap) return;
    const bt=d && d.roi_backtest;
    if(!bt || !bt.available){ wrap.style.display='none'; return; }
    wrap.style.display='';
    const body=document.getElementById('roiBtBody');
    const money=v=>'¥'+Math.round(v||0).toLocaleString('zh-CN');
    body.innerHTML=(bt.scenarios||[]).map(s=>`<tr>`
      +`<td>${esc(s.label)}</td>`
      +`<td class="num">+${Math.round((s.effective_delta||0)*100)}pp</td>`
      +`<td class="num">${s.cases_won_back} ${t('dyn.unitCases')}</td>`
      +`<td class="num">${money(s.recover_refund)}</td>`
      +`<td class="num">${money(s.recover_logistics)}</td>`
      +`<td class="num">${s.labor_hours_saved} h</td>`
      +`</tr>`).join('');
    const b=bt.basis||{}, sens=bt.sensitivity||{};
    document.getElementById('roiBtFoot').innerHTML=
      `${t('roi.btBasis')}${Number(b.total_cases||0).toLocaleString(t('locale'))} ${t('dyn.unitCases')}`
      +` · ${t('roi.btDispute')}${b.dispute_cases} ${t('dyn.unitCases')}`
      +` · ${t('roi.btWinRate')}${Math.round((b.win_rate||0)*100)}%`
      +` · ${t('roi.btAvgRefund')}${money(b.avg_refund)}<br>`
      +`${t('roi.btSens')}${money(sens['cases_-20%'])} ~ ${money(sens['cases_+20%'])}（${t('roi.btSensNote')}）<br>`
      +`${esc(bt.disclaimer||'')}`;
  }

  function syncRoi(d){
    if(!d) return;
    const total=Number(d.total_cases||0);
    const priceEl=document.getElementById('roiPrice');
    const dispEl=document.getElementById('roiDisp');
    if(total>0){
      const avg=Number(d.total_refund||0)/total;
      if(priceEl&&avg>0) priceEl.value=Math.round(avg);
      if(dispEl) dispEl.value=Math.round(Number(d.avg_dispute_rate||0)*100);
    }
    const src=document.getElementById('roiSrc');
    if(src){
      const wr=Math.round(Number(d.win_rate||0)*100);
      const srcName=d.source==='real'?t('rep.live'):t('rep.mock');
      src.textContent=t('roi.realSrc')
        .replace('{n}', total.toLocaleString(t('locale')))
        .replace('{src}', srcName)
        .replace('{wr}', String(wr));
    }
    calcROI();
  }
