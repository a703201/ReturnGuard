"""审查报告 P1 收口：补两条此前零覆盖的关键链路用例。

- PDF 导出（/api/export_pdf）：路演演示项，崩了无人知，需断言落盘为合法 PDF。
- CSV 回流（/api/import_csv）：真实数据回流主入口，需断言能落库并返回结构。

鉴权：import_csv 为写接口，需 demo 会话（conftest.auth_headers）。
数据库：继承 conftest 的临时库隔离，不污染真实演示库。
"""

from fastapi.testclient import TestClient
from main import app

# 最小可用退货 CSV（列名大小写/中文不敏感，见 importer._COL_MAP）。
# 仅需 sku 即可落库；其余字段覆盖类型转换分支。
_SAMPLE_CSV = (
    "sku,sku_name,category,supplier,platform,region,amount,date,similarity,outcome,defect_tags\n"
    "RG-TEST-001,测试商品,Electronics,SupA,Amazon,US,19.99,2026-01-15,0.5,won,尺寸不符\n"
    "RG-TEST-002,测试商品二,Home,SupB,Temu,DE,9.90,2026-02-20,0.2,lost,材质瑕疵\n"
)


def test_export_pdf_returns_valid_pdf():
    """PDF 导出路由应返回 application/pdf 且字节以 %PDF- 开头。"""
    with TestClient(app) as c:
        r = c.get("/api/export_pdf", params={"mode": "mock"})
        assert r.status_code == 200, r.text[:200]
        assert r.headers.get("content-type") == "application/pdf"
        body = r.content
        assert body[:5] == b"%PDF-", "导出内容不是合法 PDF"
        assert len(body) > 100, "PDF 体积异常（可能生成失败）"


def test_import_csv_basic(auth_headers):
    """CSV 回流应落库 real 源并返回 {ok, imported} 结构。"""
    with TestClient(app) as c:
        r = c.post(
            "/api/import_csv",
            data={"csv_text": _SAMPLE_CSV},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        assert d.get("ok") is True
        # 至少一条成功导入（行级校验失败也应计入 errors 而非整体 500）
        assert d.get("imported", 0) >= 1, f"导入断言失败：{d}"
        assert "source" in d and "tenant" in d
