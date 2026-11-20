// Package returnguard 提供 ReturnGuard 退货情报站 API 的轻量 Go 客户端。
// 零第三方依赖，仅使用标准库 net/http。
//
// 用法：
//
//	c := returnguard.NewClient("http://127.0.0.1:58080", 30*time.Second)
//	if err := c.Login("demo", "demo123"); err != nil { ... }
//	insights, err := c.Insights(map[string]string{"mode": "mock"})
package returnguard

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// Error 表示 API 返回的非 2xx 响应。
type Error struct {
	Status int
	Detail string
}

func (e *Error) Error() string {
	return fmt.Sprintf("HTTP %d: %s", e.Status, e.Detail)
}

// Client 是 ReturnGuard API 客户端。
type Client struct {
	BaseURL      string
	Timeout      time.Duration
	Token        string
	RefreshToken string
	http         *http.Client
}

// NewClient 创建客户端。
func NewClient(baseURL string, timeout time.Duration) *Client {
	return &Client{
		BaseURL: strings.TrimRight(baseURL, "/"),
		Timeout: timeout,
		http:    &http.Client{Timeout: timeout},
	}
}

// request 执行 JSON 请求并解析响应到 out（out 可为 nil）。
func (c *Client) request(method, path string, body interface{}, auth bool, out interface{}) error {
	var reader io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, c.BaseURL+path, reader)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if auth && c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		var e struct {
			Detail string `json:"detail"`
			Error  string `json:"error"`
		}
		_ = json.Unmarshal(raw, &e)
		detail := e.Detail
		if detail == "" {
			detail = e.Error
		}
		if detail == "" {
			detail = string(raw)
		}
		return &Error{Status: resp.StatusCode, Detail: detail}
	}
	if out != nil && len(raw) > 0 {
		return json.Unmarshal(raw, out)
	}
	return nil
}

// requestBytes 返回原始字节与 Content-Type（用于 PDF 二进制流）。
func (c *Client) requestBytes(path string) ([]byte, string, error) {
	req, err := http.NewRequest("GET", c.BaseURL+path, nil)
	if err != nil {
		return nil, "", err
	}
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, "", err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, "", err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, "", &Error{Status: resp.StatusCode, Detail: string(raw)}
	}
	return raw, resp.Header.Get("Content-Type"), nil
}

// ---------- 系统 ----------

func (c *Client) Health(out interface{}) error      { return c.request("GET", "/health", nil, false, out) }
func (c *Client) Config(out interface{}) error      { return c.request("GET", "/api/config", nil, false, out) }
func (c *Client) AIModels(out interface{}) error    { return c.request("GET", "/api/ai/providers", nil, false, out) }
func (c *Client) AuditVerify(out interface{}) error { return c.request("GET", "/api/audit/verify", nil, true, out) }

// ---------- 认证 ----------

// Login 登录并保存 access + refresh 令牌。
func (c *Client) Login(username, password string) error {
	var r struct {
		Token        string `json:"token"`
		RefreshToken string `json:"refresh_token"`
	}
	if err := c.request("POST", "/api/auth/login", map[string]string{
		"username": username, "password": password,
	}, false, &r); err != nil {
		return err
	}
	c.Token = r.Token
	c.RefreshToken = r.RefreshToken
	return nil
}

// Refresh 一次性轮换令牌；重放检测失败时清空本地令牌。
func (c *Client) Refresh() error {
	var r struct {
		Token        string `json:"token"`
		RefreshToken string `json:"refresh_token"`
	}
	err := c.request("POST", "/api/auth/refresh", map[string]string{
		"refresh_token": c.RefreshToken,
	}, false, &r)
	if err != nil {
		c.Token, c.RefreshToken = "", ""
		return err
	}
	c.Token, c.RefreshToken = r.Token, r.RefreshToken
	return nil
}

func (c *Client) Logout() error { return c.request("POST", "/api/auth/logout", nil, true, nil) }
func (c *Client) Me(out interface{}) error {
	return c.request("GET", "/api/auth/me", nil, true, out)
}

// ---------- 洞察 ----------

// Insights 获取群体洞察；filters 支持 mode/category/platform/region/season。
func (c *Client) Insights(filters map[string]string, out interface{}) error {
	q := url.Values{}
	for k, v := range filters {
		if v != "" {
			q.Set(k, v)
		}
	}
	p := "/api/insights"
	if s := q.Encode(); s != "" {
		p += "?" + s
	}
	return c.request("GET", p, nil, true, out)
}

func (c *Client) Analyze(payload map[string]interface{}, out interface{}) error {
	return c.request("POST", "/api/analyze", payload, true, out)
}

// ExportPDFBase64 返回 base64 字符串。
func (c *Client) ExportPDFBase64() (string, error) {
	var r struct {
		ContentBase64 string `json:"content_base64"`
	}
	err := c.request("GET", "/api/export_pdf", nil, true, &r)
	return r.ContentBase64, err
}

// ExportPDFBytes 返回原始 PDF 字节与 Content-Type。
func (c *Client) ExportPDFBytes() ([]byte, string, error) {
	return c.requestBytes("/api/export_pdf?format=binary")
}

// ---------- 案件 ----------

func (c *Client) Cases(out interface{}) error { return c.request("GET", "/api/cases", nil, true, out) }

func (c *Client) AddCase(data map[string]interface{}) (string, error) {
	var r struct {
		CaseID string `json:"case_id"`
	}
	err := c.request("POST", "/api/cases", data, true, &r)
	return r.CaseID, err
}

func (c *Client) DeleteCase(caseID string) error {
	return c.request("DELETE", "/api/cases/"+url.PathEscape(caseID), nil, true, nil)
}

func (c *Client) ImportCSV(csvText string, out interface{}) error {
	return c.request("POST", "/api/cases/import", map[string]string{
		"csv": csvText, "source": "csv",
	}, true, out)
}

// ImportXLSX 批量导入 XLSX（base64 上传，读首个 sheet）。
func (c *Client) ImportXLSX(xlsxBytes []byte, out interface{}) error {
	return c.request("POST", "/api/cases/import", map[string]string{
		"content": base64.StdEncoding.EncodeToString(xlsxBytes), "source": "xlsx",
	}, true, out)
}

// ---------- 审计 ----------

func (c *Client) AuditList(limit int, out interface{}) error {
	return c.request("GET", "/api/audit/list?limit="+strconv.Itoa(limit), nil, true, out)
}

// ---------- OAuth2 开放平台 ----------

// OAuthRegister 注册客户端（需先 Login；secret 仅返回一次）。
func (c *Client) OAuthRegister(name, scope string, out interface{}) error {
	if scope == "" {
		scope = "insights:read"
	}
	return c.request("POST", "/api/oauth/register", map[string]string{
		"name": name, "scope": scope,
	}, true, out)
}

// OAuthToken 用 client_credentials 换取 access_token（公开端点）。
func (c *Client) OAuthToken(clientID, clientSecret string, out interface{}) error {
	return c.request("POST", "/api/oauth/token", map[string]string{
		"grant_type": "client_credentials", "client_id": clientID, "client_secret": clientSecret,
	}, false, out)
}

// OAuthClients 列出已注册客户端（脱敏，需登录）。
func (c *Client) OAuthClients(out interface{}) error {
	return c.request("GET", "/api/oauth/clients", nil, true, out)
}
