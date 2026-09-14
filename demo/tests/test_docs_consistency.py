"""文档一致性守护测试。

背景：本项目文档较多（README / API / SCHEMA / PRD / CODE_REVIEW），且用户明确要求
「文档内容与代码实现保持一致」。靠人工对账多次出现漂移（实测曾发生：SCHEMA.md 把 real
源库名写成 `returnguard`、字段数写 27 而实际 28 且漏掉 `tenant_id`；`schema.sql` 与 ORM
脱节 2 列；API.md 漏记 8 个已上线端点；多份文档测试数停留在 88）。

本模块把这些「可机检的事实」固化为断言，任何一侧改动而另一侧未同步即 CI 失败：
  1. `demo/schema.sql` 的列名与顺序必须与 `db.Case` ORM 完全一致；
  2. `docs/SCHEMA.md` 声明的字段数与索引数必须与 ORM 实际一致；
  3. 全部已注册路由必须出现在 `docs/API.md` 中（不允许有端点未入档）；
  4. 各文档标注的版本号必须与仓库根 `VERSION` 一致；
  5. `docs/API.md` 提到的语种集合必须与前端 i18n 实际语言块一致。

纯静态校验，不依赖模型 Key、不需要外网。
"""

from __future__ import annotations

import re
from pathlib import Path

from db import Case

ROOT = Path(__file__).resolve().parent.parent.parent  # 仓库根
DEMO = ROOT / "demo"
DOCS = ROOT / "docs"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_schema_sql_matches_orm_columns():
    """schema.sql 与 ORM 必须列名、顺序完全一致（否则离线建表会缺列）。"""
    orm_names = [c.name for c in Case.__table__.columns]
    sql = _read(DEMO / "schema.sql")
    body = sql[sql.index("CREATE TABLE cases (") : sql.index("PRIMARY KEY")]
    sql_names = re.findall(r"^\s{4}(\w+)\s+[A-Z]", body, re.M)
    assert sql_names == orm_names, (
        f"schema.sql 与 ORM 列不一致：\n  仅 ORM 有={[n for n in orm_names if n not in sql_names]}\n"
        f"  仅 SQL 有={[n for n in sql_names if n not in orm_names]}\n  顺序一致={sql_names == orm_names}"
    )


def test_schema_sql_indexes_cover_indexed_columns():
    """ORM 中 index=True 的列，schema.sql 必须建对应索引。"""
    indexed = [c.name for c in Case.__table__.columns if c.index]
    sql = _read(DEMO / "schema.sql")
    declared = set(re.findall(r"CREATE INDEX \w+ ON cases \((\w+)\)", sql))
    missing = [n for n in indexed if n not in declared]
    assert not missing, f"schema.sql 缺少索引：{missing}"


def test_schema_md_field_count_matches_orm():
    """docs/SCHEMA.md 的字段数声明必须等于 ORM 实际列数（含 tenant_id）。"""
    md = _read(DOCS / "SCHEMA.md")
    m = re.search(r"\|\s*字段数\s*\|\s*\*{0,2}(\d+)\*{0,2}\s*", md)
    assert m, "docs/SCHEMA.md 未找到「字段数」声明行"
    assert int(m.group(1)) == len(Case.__table__.columns), (
        f"SCHEMA.md 声明 {m.group(1)} 字段，ORM 实际 {len(Case.__table__.columns)}"
    )


def test_schema_md_lists_every_orm_column():
    """每个 ORM 列都必须在 SCHEMA.md 的字段表中出现（防漏记 tenant_id 这类关键列）。"""
    md = _read(DOCS / "SCHEMA.md")
    listed = set(re.findall(r"^\|\s*\d+\s*\|\s*`(\w+)`", md, re.M))
    missing = [c.name for c in Case.__table__.columns if c.name not in listed]
    assert not missing, f"docs/SCHEMA.md 字段表漏记：{missing}"


def test_schema_md_real_db_is_separate():
    """real 源使用独立库 returnguard_real —— 防再次写回「三库均 returnguard」的错误口径。

    只校验概述表的「数据库」行（历史勘误段允许引用旧错误表述以便说明问题）。
    """
    md = _read(DOCS / "SCHEMA.md")
    row = next((ln for ln in md.splitlines() if ln.startswith("| 数据库 |")), None)
    assert row, "docs/SCHEMA.md 未找到概述表的「数据库」行"
    assert "returnguard_real" in row, f"概述表未体现 real 源独立库：{row}"
    assert "三库均" not in row, f"概述表仍在用「三库均 returnguard」的错误表述：{row}"


def test_every_route_is_documented():
    """所有已注册路由都必须出现在 docs/API.md，避免端点上线但未入档。"""
    api = _read(DOCS / "API.md")
    routes: set[str] = set()
    for f in (DEMO / "routers").glob("*.py"):
        for m in re.finditer(r'@router\.(?:get|post|delete|put)\("([^"]+)"\)', _read(f)):
            routes.add(m.group(1))
    # `/` 在 API.md 中以 `GET /` 形式出现，其余为完整路径
    missing = sorted(r for r in routes if r not in api)
    assert not missing, f"docs/API.md 未记录的路由：{missing}"


def test_api_md_documents_key_analyze_params():
    """/api/analyze 的参数是前端契约，缺一即文档失准（曾漏 language/platform/category/supplier）。"""
    api = _read(DOCS / "API.md")
    for p in (
        "returned_image",
        "product_image",
        "listing_text",
        "sku",
        "amount",
        "category",
        "supplier",
        "platform",
        "language",
        "mode",
    ):
        assert f"`{p}`" in api, f"docs/API.md 未记录 /api/analyze 参数 {p}"


def test_api_md_documents_insights_dimension_filters():
    api = _read(DOCS / "API.md")
    for p in ("category", "platform", "region", "season"):
        assert f"`{p}`" in api, f"docs/API.md 未记录 /api/insights 下钻维度 {p}"
    assert "roi_backtest" in api, "docs/API.md 未记录 roi_backtest"


def test_docs_version_matches_version_file():
    """各文档标注的版本必须与仓库根 VERSION 一致（单一来源）。"""
    version = _read(ROOT / "VERSION").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"VERSION 格式异常：{version!r}"
    for rel, pattern in (
        ("README.md", r"当前版本\*\*：(\d+\.\d+\.\d+)"),
        ("docs/SCHEMA.md", r"适用版本：(\d+\.\d+\.\d+)"),
        ("docs/CODE_REVIEW.md", r"当前版本\*\*：(\d+\.\d+\.\d+)"),
    ):
        m = re.search(pattern, _read(ROOT / rel))
        assert m, f"{rel} 未找到版本声明（pattern={pattern}）"
        assert m.group(1) == version, f"{rel} 版本 {m.group(1)} ≠ VERSION {version}"


def test_changelog_top_entry_matches_version():
    """CHANGELOG 最新条目必须就是当前版本（发版时别忘记录入）。"""
    version = _read(ROOT / "VERSION").strip()
    m = re.search(r"^## \[(\d+\.\d+\.\d+)\]", _read(ROOT / "CHANGELOG.md"), re.M)
    assert m, "CHANGELOG.md 未找到版本条目"
    assert m.group(1) == version, f"CHANGELOG 最新条目 {m.group(1)} ≠ VERSION {version}"


def test_api_md_language_list_matches_i18n_blocks():
    """docs/API.md 描述的界面语种必须与 i18n.js 实际语言块一致。"""
    i18n = _read(DEMO / "static" / "i18n.js")
    blocks = set(re.findall(r"^  (\w+): \{$", i18n, re.M))
    api = _read(DOCS / "API.md")
    for lang in sorted(blocks):
        assert f"`{lang}`" in api, f"docs/API.md 未提及界面语种 {lang}"


def test_security_range_in_docs_is_current():
    """安全项范围须写 SEC-13（早期文档停在 SEC-12）。"""
    for rel in ("README.md", "docs/API.md"):
        text = _read(ROOT / rel)
        assert "SEC-13" in text, f"{rel} 未体现 SEC-13（live 配额闸）"
