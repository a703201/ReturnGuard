import { state } from './store.js';

export function apiUrl(path){
  const u = new URL(path, location.href);
  u.searchParams.set('source', state.source);
  return u.pathname + u.search;
}

export function apiFetch(path, opts){
  opts = opts || {};
  opts.headers = Object.assign({}, opts.headers || {});
  const tok = localStorage.getItem('rg_token');
  if(tok) opts.headers['Authorization'] = 'Bearer ' + tok;
  return fetch(apiUrl(path), opts);
}


export async function copyText(text){
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


export function authToken(){ return localStorage.getItem('rg_token') || ''; }