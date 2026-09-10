// i18n.js — P2-7 前端国际化（跨境场景打底）
// 仅抽取「可见标签」文案，所有动态数据（KPI 数值、表格、报告正文等）由后端/渲染负责，不在此翻译。
// 默认 zh（与现有中文界面完全一致）；en 为对照译本，满足跨境评审/海外卖家场景。
//
// 用法：
//   import { t, setLang, applyI18n, currentLang } from './i18n.js';
//   <span data-i18n="kpi.total">已分析退货</span>
//   applyI18n();  // 把页面上所有 [data-i18n] 文案替换为当前语言

const DICT = {
  zh: {
    'tab.dash': '市场洞察',
    'tab.plat': '平台举证包',
    'tab.supplier': '供应商透视',
    'tab.forensic': '单案取证',
    'tab.entry': '数据录入',
    'kpi.total': '已分析退货',
    'kpi.refund': '累计退款¥',
    'kpi.win': '维权胜诉率',
    'kpi.disp': '货不对板嫌疑率',
    'toolbar.note': '看板随顶部「品类 / 平台 / 洞察模式」筛选实时刷新 · 一键导出本期洞察',
    'btn.refresh': '刷新看板',
    'btn.report': '导出洞察报告',
    'btn.login': '登录',
    'judge.title': '📋 评委体验指引',
    'lang.label': '语言',
    'lang.zh': '中文',
    'lang.en': 'English',
  },
  en: {
    'tab.dash': 'Market Insights',
    'tab.plat': 'Platform Evidence Kit',
    'tab.supplier': 'Supplier View',
    'tab.forensic': 'Forensic Tool',
    'tab.entry': 'Data Entry',
    'kpi.total': 'Returns Analyzed',
    'kpi.refund': 'Total Refund ¥',
    'kpi.win': 'Win Rate',
    'kpi.disp': 'Mismatch Suspicion',
    'toolbar.note': 'Dashboard refreshes live with the top filters (category / platform / mode) · one-click export',
    'btn.refresh': 'Refresh',
    'btn.report': 'Export Report',
    'btn.login': 'Login',
    'judge.title': '📋 Reviewer Guide',
    'lang.label': 'Language',
    'lang.zh': '中文',
    'lang.en': 'English',
  },
};

let _lang = (typeof localStorage !== 'undefined' && localStorage.getItem('rg_lang')) || 'zh';
if (!DICT[_lang]) _lang = 'zh';

export const currentLang = () => _lang;

export function setLang(lang) {
  if (!DICT[lang]) lang = 'zh';
  _lang = lang;
  try { localStorage.setItem('rg_lang', lang); } catch (_) { /* 隐私模式忽略 */ }
  document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
}

export function t(key) {
  const table = DICT[_lang] || DICT.zh;
  return Object.prototype.hasOwnProperty.call(table, key) ? table[key] : key;
}

// 把页面上所有 [data-i18n] 元素的文本替换为当前语言对应文案；
// 同时刷新语言选择器自身选项（zh/en 标签不随语言变化，保持可读）。
export function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (key) el.textContent = t(key);
  });
  const sel = document.getElementById('langSel');
  if (sel) {
    Array.from(sel.options).forEach(o => {
      const lk = o.getAttribute('data-lang-label');
      if (lk) o.textContent = t(lk);
    });
  }
}
