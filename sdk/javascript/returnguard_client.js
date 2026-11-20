/**
 * ReturnGuard 退货情报站 · JavaScript SDK
 *
 * 零依赖（基于 Fetch API），Node.js 18+ / 现代浏览器均可用。
 * 与 Python SDK (sdk/python/returnguard_client.py) 方法对齐。
 *
 * 用法（Node.js ESM）：
 *   import { ReturnGuardClient } from './returnguard_client.js'
 *   const client = new ReturnGuardClient('http://127.0.0.1:58080')
 *   await client.login('demo', 'demo123')
 *   const insights = await client.insights({ mode: 'mock' })
 *
 * 浏览器环境：直接 <script type="module"> import 即可；注意 CORS 与凭据存放安全。
 */

export class ReturnGuardError extends Error {
  constructor(status, detail) {
    super(`HTTP ${status}${detail ? ': ' + detail : ''}`)
    this.name = 'ReturnGuardError'
    this.status = status
    this.detail = detail
  }
}

export class ReturnGuardClient {
  constructor(baseUrl = 'http://127.0.0.1:58080', timeout = 30000) {
    this.baseUrl = baseUrl.replace(/\/$/, '')
    this.timeout = timeout
    this.token = ''
    this.refreshToken = ''
  }

  /** 底层请求：返回解析后的 JSON，失败抛 ReturnGuardError。 */
  async _request(method, path, body = null, auth = true) {
    const headers = { Accept: 'application/json' }
    if (body !== null) headers['Content-Type'] = 'application/json'
    if (auth && this.token) headers['Authorization'] = 'Bearer ' + this.token

    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.timeout)
    let resp
    try {
      resp = await fetch(this.baseUrl + path, {
        method,
        headers,
        body: body !== null ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      })
    } catch (e) {
      clearTimeout(timer)
      throw new ReturnGuardError(0, 'network error: ' + (e?.message || String(e)))
    }
    clearTimeout(timer)

    if (!resp.ok) {
      let detail = ''
      try {
        const j = await resp.json()
        detail = j.detail || j.error || ''
      } catch (_) {
        /* 非 JSON 错误体，忽略 */
      }
      throw new ReturnGuardError(resp.status, detail)
    }
    const text = await resp.text()
    return text ? JSON.parse(text) : {}
  }

  /** 二进制请求：返回 { bytes: Uint8Array, contentType: string }。 */
  async _requestBytes(path) {
    const headers = {}
    if (this.token) headers['Authorization'] = 'Bearer ' + this.token
    const resp = await fetch(this.baseUrl + path, { method: 'GET', headers })
    if (!resp.ok) throw new ReturnGuardError(resp.status, await resp.text().catch(() => ''))
    return {
      bytes: new Uint8Array(await resp.arrayBuffer()),
      contentType: resp.headers.get('Content-Type') || '',
    }
  }

  // ---------- 系统 ----------
  health() { return this._request('GET', '/health', null, false) }
  config() { return this._request('GET', '/api/config', null, false) }
  async platforms() { return (await this._request('GET', '/api/platforms', null, false)).platforms }
  aiProviders() { return this._request('GET', '/api/ai/providers', null, false) }

  // ---------- 认证 ----------
  async login(username, password) {
    const r = await this._request('POST', '/api/auth/login', { username, password }, false)
    this.token = r.token
    this.refreshToken = r.refresh_token || ''
    return this.token
  }

  /** 一次性轮换；重放检测会撤销该用户全部会话，失败时清空本地令牌。 */
  async refresh() {
    try {
      const r = await this._request('POST', '/api/auth/refresh', { refresh_token: this.refreshToken }, false)
      this.token = r.token
      this.refreshToken = r.refresh_token || ''
      return this.token
    } catch (e) {
      this.token = ''
      this.refreshToken = ''
      throw e
    }
  }

  register(username, password, tenantName = '', sm3 = false) {
    const path = sm3 ? '/api/auth/register-sm3' : '/api/auth/register'
    return this._request('POST', path, { username, password, tenant_name: tenantName }, false)
  }

  me() { return this._request('GET', '/api/auth/me') }
  logout() { return this._request('POST', '/api/auth/logout') }

  // ---------- 洞察 ----------
  /** filters: { mode, category, platform, region, season } */
  insights(filters = {}) {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(filters)) if (v) q.set(k, String(v))
    const s = q.toString()
    return this._request('GET', '/api/insights' + (s ? '?' + s : ''))
  }

  analyze({ mode = 'mock', sku = '', platform = '', listingText = '', returnedImageUrl = '' } = {}) {
    return this._request('POST', '/api/analyze', {
      mode, sku, platform,
      listing_text: listingText,
      returned_image_url: returnedImageUrl,
    })
  }

  async exportPdfBase64() {
    return (await this._request('GET', '/api/export_pdf')).content_base64
  }

  /** 返回 { bytes: Uint8Array, contentType }；Node 可用 fs.writeFileSync(path, bytes)。 */
  exportPdfBytes() { return this._requestBytes('/api/export_pdf?format=binary') }

  // ---------- 案件 ----------
  cases() { return this._request('GET', '/api/cases') }
  async addCase(data) { return (await this._request('POST', '/api/cases', data)).case_id }
  async deleteCase(caseId) {
    return !!(await this._request('DELETE', '/api/cases/' + encodeURIComponent(caseId))).ok
  }
  importCsv(csvText) {
    return this._request('POST', '/api/cases/import', { csv: csvText, source: 'csv' })
  }
  /** 浏览器：传 ArrayBuffer/Uint8Array；Node：传 Buffer。 */
  async importXlsx(bytes) {
    const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes)
    let bin = ''
    for (const b of u8) bin += String.fromCharCode(b)
    return this._request('POST', '/api/cases/import', {
      content: btoa(bin), source: 'xlsx',
    })
  }

  // ---------- 审计 ----------
  auditVerify() { return this._request('GET', '/api/audit/verify') }
  auditList(limit = 50) { return this._request('GET', '/api/audit/list?limit=' + limit) }

  // ---------- OAuth2 开放平台 ----------
  oauthRegister(name, scope = 'insights:read') {
    return this._request('POST', '/api/oauth/register', { name, scope })
  }
  oauthToken(clientId, clientSecret) {
    return this._request('POST', '/api/oauth/token', {
      grant_type: 'client_credentials', client_id: clientId, client_secret: clientSecret,
    }, false)
  }
  oauthClients() { return this._request('GET', '/api/oauth/clients') }
}

export default ReturnGuardClient
