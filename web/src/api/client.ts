/** 同源 /api 客户端：开发期由 Vite proxy 转发到后端，生产期后端同端口托管。 */
import { token } from '../composables/useAuth'

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export async function apiGet<T = unknown>(path: string): Promise<T> {
  return request<T>('GET', path)
}
export async function apiPost<T = unknown>(path: string, body?: unknown): Promise<T> {
  return request<T>('POST', path, body)
}
export async function apiPut<T = unknown>(path: string, body?: unknown): Promise<T> {
  return request<T>('PUT', path, body)
}
export async function apiDelete<T = unknown>(path: string): Promise<T> {
  return request<T>('DELETE', path)
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token.value) headers.Authorization = `Bearer ${token.value}`
  let res: Response
  try {
    res = await fetch(`/api/${path.replace(/^\//, '')}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  } catch {
    throw new ApiError(0, 'Network unavailable')
  }
  if (!res.ok) {
    let detail = ''
    try { detail = (await res.json()).detail || '' } catch { /* ignore */ }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}
