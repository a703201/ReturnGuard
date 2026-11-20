# ReturnGuard 多语言 SDK

零第三方依赖的客户端库，与 [`docs/openapi.yaml`](../docs/openapi.yaml) 契约对齐。

| 语言 | 目录 | 依赖 | 环境 |
| --- | --- | --- | --- |
| Python | `python/` | 仅标准库 `urllib` | Python 3.10+ |
| JavaScript | `javascript/` | 仅 Fetch API | Node.js 18+ / 现代浏览器 |
| Go | `go/` | 仅标准库 `net/http` | Go 1.20+ |

## 能力覆盖（三语言一致）

- 系统：`health` / `config` / `aiProviders`
- 认证：`login` / `refresh`（一次性轮换+重放检测）/ `register` / `me` / `logout`
- 洞察：`insights(filters)` / `analyze` / `exportPdfBase64` / `exportPdfBytes`
- 案件：`cases` / `addCase` / `deleteCase` / `importCsv` / `importXlsx`
- PDF 双传输：`exportPdfBase64` 与 `exportPdfBytes`（`application/pdf` 字节流）
- 审计：`auditVerify` / `auditList(limit)`
- OAuth2：`oauthRegister(name, scope)` / `oauthToken(clientId, secret)` / `oauthClients()`

## 快速示例

**Python**（详见 `python/README.md`）：

```python
from returnguard_client import ReturnGuardClient
with ReturnGuardClient("http://127.0.0.1:58080") as c:
    c.login("demo", "demo123")
    print(c.insights(mode="mock")["total_cases"])
```

**JavaScript**（ESM）：

```js
import { ReturnGuardClient } from './returnguard_client.js'
const c = new ReturnGuardClient('http://127.0.0.1:58080')
await c.login('demo', 'demo123')
console.log((await c.insights({ mode: 'mock' })).total_cases)
```

**Go**：

```go
c := returnguard.NewClient("http://127.0.0.1:58080", 30*time.Second)
if err := c.Login("demo", "demo123"); err != nil { panic(err) }
var insights map[string]interface{}
if err := c.Insights(map[string]string{"mode": "mock"}, &insights); err != nil { panic(err) }
```

## 守护

`demo/tests/test_docs_consistency.py` 守护：路由 ↔ openapi.yaml 一致、openapi 版本 = `VERSION`、Python SDK 核心方法齐全。JS/Go SDK 的方法对齐目前靠人工核对，未纳入自动断言。

## 边界

- 令牌存本地内存，不持久化；生产环境需用安全存储。
- 浏览器直连需注意 CORS 与凭据安全；建议经后端代理。
- SDK 不处理 OAuth2（当前服务端未开放 client_credentials 端点）。
