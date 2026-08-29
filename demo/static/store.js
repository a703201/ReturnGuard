// store.js — 单一状态源（数据源 / 最近洞察 / 分页 / 阈值）
// 所有模块共享同一份 state，消除此前全局命名污染与多份状态不一致的隐患。
export const state = {
  source: (localStorage.getItem('rg_source') || 'demo'), // 当前数据源 demo / real
  ins: null,            // 最近一次 insights 响应，供供应商下钻本地计算
  entryPage: 1,         // 数据录入列表当前页（A23 后端分页信封）
  pageSize: 20,         // 每页条数
  threshold: 0.82,      // 同款一致性阈值（运行时从 /api/config 拉取单一来源值，兜底 0.82）
};

export function setState(patch) {
  Object.assign(state, patch);
}
