// store.js — 单一状态源（最近洞察 / 分页 / 阈值）
// 所有模块共享同一份 state，消除此前全局命名污染与多份状态不一致的隐患。
//
// 数据源（source）不再由用户手动切换，而是由登录态自动推导：
//   - 未登录 → demo（演示布局，使用预置种子数据）
//   - 已登录（含 demo/demo123 演示账户）→ real（AI 实算，数据按租户隔离）
// 顶部的「演示数据 / 实际数据」切换开关已移除，改用 demo 账户替代演示数据体验。
export const state = {
  ins: null,            // 最近一次 insights 响应，供供应商下钻本地计算
  entryPage: 1,         // 数据录入列表当前页（A23 后端分页信封）
  pageSize: 20,         // 每页条数
  threshold: 0.82,      // 同款一致性阈值（运行时从 /api/config 拉取单一来源值，兜底 0.82）
};

// source 为派生属性：登录即 real，未登录即 demo。注销旧 localStorage rg_source 避免残留。
Object.defineProperty(state, 'source', {
  get() {
    return localStorage.getItem('rg_token') ? 'real' : 'demo';
  },
  enumerable: true,
  configurable: true,
});

export function setState(patch) {
  Object.assign(state, patch);
}
