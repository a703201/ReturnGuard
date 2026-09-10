// i18n.js — 前端国际化（跨境场景，覆盖顶栏 / KPI / 15 张卡片标题 / 关键按钮）
// 抽表范围：**可见静态标签**（Tab、KPI 标签、卡片标题、按钮、指引标题）。
// 动态数据（KPI 数值、表格内容、洞察报告正文等）由后端/渲染负责，不在此翻译。
// 默认 zh（与现有中文界面完全一致）；en 为对照译本，满足跨境评审/海外卖家场景。
//
// 用法：
//   import { t, setLang, applyI18n, currentLang } from './i18n.js';
//   <span data-i18n="kpi.total">已分析退货</span>
//   applyI18n();  // 把页面上所有 [data-i18n] 文案替换为当前语言
//
// 注意：data-i18n 只加在「纯文本、无子元素」的节点上——applyI18n 用 textContent 覆盖，
// 若节点内含 <span class="badge"> 等子元素会被清空。

const DICT = {
  zh: {
    // 顶栏 / Tab
    'tab.dash': '市场洞察',
    'tab.plat': '平台举证包',
    'tab.supplier': '供应商透视',
    'tab.forensic': '单案取证',
    'tab.entry': '数据录入',
    // KPI
    'kpi.total': '已分析退货',
    'kpi.refund': '累计退款¥',
    'kpi.win': '维权胜诉率',
    'kpi.disp': '货不对板嫌疑率',
    // 工具栏 / 按钮 / 指引
    'toolbar.note': '看板随顶部「品类 / 平台 / 洞察模式」筛选实时刷新 · 一键导出本期洞察',
    'btn.refresh': '刷新看板',
    'btn.report': '导出洞察报告',
    'btn.login': '登录',
    'btn.loginGate': '登录 / 注册',
    'judge.title': '📋 评委体验指引',
    'lang.label': '语言',
    'lang.zh': '中文',
    'lang.en': 'English',
    // 洞察看板卡片标题（15 张）
    'card.c11': '钱都亏在哪些品类',
    'card.c12': '各平台维权难度',
    'card.c13': '给老板的洞察总结',
    'card.c14': '退货地区分布',
    'card.c15': '退货时间序列趋势',
    'card.c21': '退货预测预警',
    'card.c22': '退货为什么发生',
    'card.c23': '最近暴增的退货',
    'card.c24': '下一步怎么做',
    'card.c25': '退货季节趋势',
    'card.c31': '选品避坑闭环 · 可执行清单',
    'card.c32': '哪些供应商最该换',
    'card.c33': '最烧钱的退货商品',
    'card.c34': '平台 × 供应商 维权交叉',
    'card.c35': '退货成本 & 供应商黑名单',
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
    'btn.loginGate': 'Login / Sign up',
    'judge.title': '📋 Reviewer Guide',
    'lang.label': 'Language',
    'lang.zh': '中文',
    'lang.en': 'English',
    'card.c11': 'Where the Money Bleeds (Categories)',
    'card.c12': 'Win Difficulty by Platform',
    'card.c13': 'Executive Summary',
    'card.c14': 'Returns by Region',
    'card.c15': 'Return Volume Trend',
    'card.c21': 'Return Forecast & Alerts',
    'card.c22': 'Why Returns Happen',
    'card.c23': 'Recently Surging Returns',
    'card.c24': 'What to Do Next',
    'card.c25': 'Seasonal Return Trend',
    'card.c31': 'Sourcing-Avoidance Checklist',
    'card.c32': 'Suppliers to Replace',
    'card.c33': 'Costliest Returned SKUs',
    'card.c34': 'Platform × Supplier Win Rate',
    'card.c35': 'Return Cost & Supplier Blacklist',
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
