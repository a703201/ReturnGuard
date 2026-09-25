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


# ===================== 2.0.0 新增守护：去赛事化 / 无公网演示地址 / 衍生版本一致性 =====================

# 赛事语境词表（含团队名与专用名词）。新增文档时若不小心带回这些词，CI 直接失败。
_COMPETITION_TERMS = (
    "黑客松",
    "复赛",
    "决赛",
    "参赛",
    "赛道",
    "评委",
    "答辩",
    "赛事",
    "hackathon",
    "Hackathon",
    "Lumio",
    "组委会",
)
# 已退役的公网演示域名与隧道配置关键字（该地址已停用，仓内不应再出现）。
_RETIRED_PUBLIC_TERMS = ("a703201sworld", "cloudflared", "rg-tunnel", "trycloudflare")

_SCAN_SUFFIXES = (
    ".md",
    ".py",
    ".js",
    ".mjs",
    ".html",
    ".css",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".txt",
    ".example",
    ".bat",
    ".sh",
)
_SCAN_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "Dataset",
    "dist",
    "uploads",
    "state",
}


def _iter_repo_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if set(rel.parts) & _SCAN_SKIP_DIRS:
            continue
        # 测试自身需要列举这些词作为「禁用词表」，故跳过测试目录（否则守卫会自伤）。
        if rel.parts[:2] == ("demo", "tests"):
            continue
        if path.suffix.lower() not in _SCAN_SUFFIXES:
            continue
        yield path, rel


def test_no_competition_terms_anywhere():
    """全仓不得残留赛事语境（项目已从参赛作品转为常规工程）。

    守护 2.0.0 的「去赛事化」改动，防止后续文档/注释再引入赛事名称、参赛信息、
    评审语境、团队名等。命中即失败并给出文件与行号，便于定位。
    """
    hits: list[str] = []
    for path, rel in _iter_repo_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for term in _COMPETITION_TERMS:
                if term in line:
                    hits.append(f"{rel}:{lineno} 含「{term}」 -> {line.strip()[:80]}")
    assert not hits, "仓内仍存在赛事语境：\n" + "\n".join(hits)


def test_retired_public_demo_address_removed():
    """已停用的公网演示地址与隧道配置不得再出现在仓库中（含链接、注释与配置）。"""
    hits: list[str] = []
    for path, rel in _iter_repo_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for term in _RETIRED_PUBLIC_TERMS:
                if term in line:
                    hits.append(f"{rel}:{lineno} 含「{term}」 -> {line.strip()[:80]}")
    assert not hits, "仍存在已退役的公网演示/隧道引用：\n" + "\n".join(hits)


def test_competition_archive_and_deploy_scripts_removed():
    """初赛归档目录与公网演示脚本应已移除（历史材料不再随仓库分发）。"""
    assert not (DOCS / "legacy").exists(), "docs/legacy 为参赛期历史归档，应已移除"
    assert not (ROOT / "deploy").exists(), "deploy/ 为公网演示（隧道）脚本，应已移除"
    assert not (ROOT / "docker" / "returnguard-tunnel.service").exists(), (
        "隧道 systemd 单元应已移除"
    )
    readme = _read(ROOT / "README.md")
    assert "docs/legacy" not in readme, "README 不应再引用已删除的 docs/legacy"


def test_package_json_version_matches_version_file():
    """前端构建链路的 package.json 版本必须与仓库根 VERSION 一致（曾长期停在 1.1.2）。"""
    import json

    version = _read(ROOT / "VERSION").strip()
    pkg = json.loads(_read(ROOT / "package.json"))
    assert pkg.get("version") == version, (
        f"package.json 版本 {pkg.get('version')} ≠ VERSION {version}"
    )


def test_api_md_quota_env_names_match_code():
    """docs/API.md 记录的 `LIVE_QUOTA_*` 变量名必须与 quota.py 实际读取的一致。

    历史漂移：文档曾写 `LIVE_QUOTA_GLOBAL_DAILY` / `LIVE_QUOTA_ACCOUNT_DAILY` /
    `LIVE_QUOTA_IP_HOURLY`，而代码读的是 `LIVE_QUOTA_GLOBAL_DAY` /
    `LIVE_QUOTA_TENANT_DAY` / `LIVE_QUOTA_IP_HOUR`——照文档配置等于没配。
    """
    code = _read(DEMO / "quota.py")
    names = set(re.findall(r'_env_int\("(LIVE_QUOTA_\w+)"', code))
    assert names, "quota.py 未找到 LIVE_QUOTA_* 读取点"
    api = _read(DOCS / "API.md")
    for name in sorted(names):
        assert f"`{name}`" in api, f"docs/API.md 未记录配额变量 {name}"
    # 反向：文档里不应出现代码不认识的配额变量名
    documented = set(re.findall(r"LIVE_QUOTA_\w+", api))
    unknown = documented - names
    assert not unknown, f"docs/API.md 记录了代码不存在的配额变量：{sorted(unknown)}"


def test_env_examples_document_all_live_quota_names():
    """.env.example 模板必须覆盖全部配额变量名（照模板配置即生效）。"""
    code = _read(DEMO / "quota.py")
    names = set(re.findall(r'_env_int\("(LIVE_QUOTA_\w+)"', code))
    for rel in ("demo/.env.example", "docker/.env.example"):
        text = _read(ROOT / rel)
        missing = [n for n in sorted(names) if n not in text]
        assert not missing, f"{rel} 缺少配额变量说明：{missing}"


# ===================== 2.1.0 新增守护：判定/实现/平台文档与代码同步 =====================

_REQUIRED_DOCS = ("ARCHITECTURE.md", "DECISION_LOGIC.md", "AI_PROVIDERS.md")


def test_required_docs_exist_and_are_linked_from_readme():
    """新增的判定逻辑 / 实现逻辑 / 平台对接文档必须存在，且 README 能索引到。

    文档不挂到 README = 事实上找不到，等于没写。
    """
    readme = _read(ROOT / "README.md")
    for name in _REQUIRED_DOCS:
        assert (DOCS / name).exists(), f"缺少文档 docs/{name}"
        assert f"docs/{name}" in readme, f"README 未索引 docs/{name}"


def test_ai_providers_matrix_matches_code():
    """docs/AI_PROVIDERS.md 的平台矩阵必须与 providers.PROVIDERS 完全一致。

    判定逻辑/平台矩阵是「文档→代码」最容易漂移的地方：新增平台只改代码不改文档，
    读者会以为该平台不可用（或反之）。
    """
    import providers as pv

    doc = _read(DOCS / "AI_PROVIDERS.md")
    # 只取 §3 支持矩阵表（该节内的平台行形如 `| `key` | 展示名 | ...`），
    # 其余小节（能力语义 / URL 形状 / 鉴权风格）也有形似的表格，必须切开以免误匹配。
    start = doc.index("## 3.")
    end = doc.index("## 4.", start)
    section = doc[start:end]
    listed = set(re.findall(r"^\|\s*`([a-z_]+)`\s*\|", section, re.M))
    code_keys = set(pv.PROVIDERS)
    assert listed, "AI_PROVIDERS.md 未解析到平台矩阵（测试前提失效）"
    assert listed == code_keys, (
        f"平台矩阵与代码不一致：文档多出={sorted(listed - code_keys)} 代码多出={sorted(code_keys - listed)}"
    )


def test_decision_logic_doc_covers_key_thresholds():
    """判定逻辑文档必须写明关键阈值与口径，避免文档退化成「泛泛而谈」。

    这些都是代码里的硬事实：同款阈值、already-decided 口径、异常预警倍数、ROI 上限。
    """
    doc = _read(DOCS / "DECISION_LOGIC.md")
    for token in ("0.82", "1.8", "0.95", "decided", "只取证，不裁决"):
        assert token in doc, f"DECISION_LOGIC.md 缺少关键口径：{token}"
