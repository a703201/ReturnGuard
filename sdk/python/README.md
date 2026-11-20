# ReturnGuard Python SDK

轻量 SDK，仅用 Python 标准库（无需 pip 安装第三方依赖）。契约见 `docs/openapi.yaml`。

## 快速开始

```python
from returnguard_client import ReturnGuardClient

with ReturnGuardClient("http://127.0.0.1:58080") as c:
    c.login("demo", "demo123")        # 演示账户；普通用户用自己的凭据
    cfg = c.config()
    print("version:", cfg["version"], "persistence:", cfg["persistence"])

    ins = c.insights()                 # 当前租户的群体洞察
    print("total:", ins["total_cases"], "win_rate:", ins["win_rate"])
    print("建议:", ins["sourcing_advice"])
```

## 常用操作

```python
# 平台举证包与 AI 能力矩阵（无需登录）
platforms = c.platforms()
ai_caps = c.ai_providers()

# 单案取证（无密钥时 mode=mock 诚实回退）
res = c.analyze(mode="mock", sku="SKU-1", platform="Amazon",
                returned_image_url="data:image/png;base64,...")
print(res["similarity"], res["dossier"], res["capabilities"])

# 案件录入 / 删除 / CSV 批量导入
cid = c.add_case({"sku": "SKU-NEW", "amount": 99.5, "outcome": "待分析"})
c.delete_case(cid)
result = c.import_csv("sku,品类,金额,平台\nSKU-1,3C数码,120,Amazon\n")
print(result["imported"], result["skipped"])

# XLSX 批量导入（读首个 sheet，中文表头可用）
result = c.import_xlsx(open("cases.xlsx", "rb").read())

# 导出 PDF：base64 或真二进制流
open("report.pdf", "wb").write(base64.b64decode(c.export_pdf_base64()))
size, ctype = c.export_pdf_bytes("report.bin")   # application/pdf 字节流

# 审计分页
print(c.audit_list(limit=10)["total"])

# OAuth2 开放平台（先登录，注册客户端 secret 仅返回一次）
app = c.oauth_register("我的应用", scope="insights:read")
token = c.oauth_token(app["client_id"], app["client_secret"])["access_token"]
print(c.oauth_clients()["clients"])
```

## 认证说明

- `login()` / `register()` 返回的令牌保存在客户端内存（`self.token`），不落盘。
- 所有 API 调用自动带 `Authorization: Bearer <token>`。
- `logout()` 撤销该用户全部会话；`with` 语句退出时自动调用。
- 令牌为 5 段 HMAC 结构，服务端会话表校验，支持即时吊销。

## 错误处理

```python
from returnguard_client import ReturnGuardError
try:
    c.insights()
except ReturnGuardError as e:
    print(e.status, e.detail)   # 401 未登录 / 404 案件不存在 等
```
