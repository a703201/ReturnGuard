# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""ReturnGuard 退货情报站 · 轻量 Python SDK（仅标准库，无第三方依赖）。

用法：
    from returnguard_client import ReturnGuardClient
    with ReturnGuardClient("http://127.0.0.1:58080") as c:
        c.login("demo", "demo123")
        print(c.config()["version"])
        print(c.insights()["total_cases"])
        c.add_case({"sku": "SKU-1", "amount": 99.5})

契约来源：docs/openapi.yaml。令牌只在内存中保存，不落盘。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class ReturnGuardError(Exception):
    """API 返回非 2xx。"""

    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class ReturnGuardClient:
    def __init__(self, base_url: str = "http://127.0.0.1:58080", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token = ""
        self.refresh_token = ""

    def __enter__(self) -> "ReturnGuardClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.logout()

    # ---------- 底层 ----------
    def _request(self, method: str, path: str, body: dict[str, Any] | None = None,
                 auth: bool = True) -> Any:
        url = self.base_url + path
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if auth and self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read().decode("utf-8")).get("detail", "")
            except Exception:
                detail = ""
            raise ReturnGuardError(e.code, detail) from None

    def _request_bytes(self, path: str) -> tuple[bytes, str]:
        """返回 (原始字节, content-type)，用于 PDF 二进制流端点。"""
        req = urllib.request.Request(self.base_url + path, method="GET")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raise ReturnGuardError(e.code, e.read().decode("utf-8", "replace")) from None

    # ---------- 系统 ----------
    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health", auth=False)

    def config(self) -> dict[str, Any]:
        return self._request("GET", "/api/config", auth=False)

    def platforms(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/platforms", auth=False)["platforms"]

    def ai_providers(self) -> dict[str, Any]:
        """14 平台能力矩阵（不含密钥）。"""
        return self._request("GET", "/api/ai/providers", auth=False)

    # ---------- 认证 ----------
    def login(self, username: str, password: str) -> str:
        r = self._request("POST", "/api/auth/login",
                          {"username": username, "password": password}, auth=False)
        self.token = r["token"]
        self.refresh_token = r.get("refresh_token", "")
        return self.token

    def refresh(self) -> str:
        """一次性轮换令牌；重放检测会撤销该用户全部会话。失败时清空本地令牌。"""
        try:
            r = self._request("POST", "/api/auth/refresh",
                              {"refresh_token": self.refresh_token}, auth=False)
        except ReturnGuardError:
            self.token = ""
            self.refresh_token = ""
            raise
        self.token = r["token"]
        self.refresh_token = r.get("refresh_token", "")
        return self.token

    def register(self, username: str, password: str, tenant_name: str = "",
                 sm3: bool = False) -> str:
        path = "/api/auth/register-sm3" if sm3 else "/api/auth/register"
        r = self._request("POST", path,
                          {"username": username, "password": password,
                           "tenant_name": tenant_name}, auth=False)
        self.token = r["token"]
        return self.token

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/api/auth/me")

    def logout(self) -> None:
        if self.token:
            try:
                self._request("POST", "/api/auth/logout")
            except ReturnGuardError:
                pass
            self.token = ""

    # ---------- 洞察 ----------
    def insights(self, **filters: str) -> dict[str, Any]:
        """filters: mode/category/platform/region/season。"""
        q = urllib.parse.urlencode({k: v for k, v in filters.items() if v})
        return self._request("GET", "/api/insights" + ("?" + q if q else ""))

    def analyze(self, mode: str = "mock", sku: str = "", platform: str = "",
                listing_text: str = "", returned_image_url: str = "") -> dict[str, Any]:
        return self._request("POST", "/api/analyze", {
            "mode": mode, "sku": sku, "platform": platform,
            "listing_text": listing_text, "returned_image_url": returned_image_url,
        })

    def export_pdf_base64(self) -> str:
        """返回 base64 字符串；调用方自行解码保存为 .pdf。"""
        return self._request("GET", "/api/export_pdf")["content_base64"]

    def export_pdf_bytes(self, path: str) -> tuple[bytes, str]:
        """二进制流下载 PDF 到 path，返回 (字节数, content-type)。"""
        raw, ct = self._request_bytes("/api/export_pdf?format=binary")
        with open(path, "wb") as f:
            f.write(raw)
        return len(raw), ct

    # ---------- 案件 ----------
    def cases(self) -> dict[str, Any]:
        return self._request("GET", "/api/cases")

    def add_case(self, data: dict[str, Any]) -> str:
        r = self._request("POST", "/api/cases", data)
        return r["case_id"]

    def delete_case(self, case_id: str) -> bool:
        return bool(self._request("DELETE", "/api/cases/" + urllib.parse.quote(case_id, safe=""))["ok"])

    def import_csv(self, csv_text: str) -> dict[str, Any]:
        """批量导入 CSV（SKU 必填，中英文列名兼容）。"""
        return self._request("POST", "/api/cases/import", {"csv": csv_text, "source": "csv"})

    def import_xlsx(self, xlsx_bytes: bytes) -> dict[str, Any]:
        """批量导入 XLSX（base64 上传，读首个 sheet，中文表头可用）。"""
        import base64
        return self._request("POST", "/api/cases/import", {
            "content": base64.b64encode(xlsx_bytes).decode(), "source": "xlsx",
        })

    # ---------- 审计 ----------
    def audit_verify(self) -> dict[str, Any]:
        return self._request("GET", "/api/audit/verify")

    def audit_list(self, limit: int = 50) -> dict[str, Any]:
        """审计事件分页检索（append-only，返回最近 limit 条）。"""
        return self._request("GET", "/api/audit/list?limit=" + str(limit))

    # ---------- OAuth2 开放平台 ----------
    def oauth_register(self, name: str, scope: str = "insights:read") -> dict[str, Any]:
        """注册客户端（需已登录）；client_secret 仅本次返回。"""
        return self._request("POST", "/api/oauth/register", {"name": name, "scope": scope})

    def oauth_token(self, client_id: str, client_secret: str) -> dict[str, Any]:
        """client_credentials 换取 access_token（公开端点）。"""
        return self._request("POST", "/api/oauth/token", {
            "grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret,
        }, auth=False)

    def oauth_clients(self) -> dict[str, Any]:
        """列出已注册客户端（脱敏，需登录）。"""
        return self._request("GET", "/api/oauth/clients")


__all__ = ["ReturnGuardClient", "ReturnGuardError"]
