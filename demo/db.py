"""ReturnGuard · 数据持久层（仓储层）

职责：把「案件」这一核心数据从 JSON 文件升级为**数据库**，解决原 cases.json 全量读写
带来的并发覆盖、无数据模型、无事务等问题，并为复赛切换到国产数据库 openGauss 预留
同构接口。

双轨设计（开发期 / 部署期**零代码改动**切换）：
    - 开发期（默认）：SQLite 文件库，零部署、随起随用，不卡初赛进度。
    - 部署期（复赛）：设置环境变量 DATABASE_URL 指向 openGauss 即可，业务代码不变。
      openGauss 是华为开源的国产关系型数据库（兼容 PostgreSQL 协议）；其向量能力还可
      进一步把「图向量比对」做成真实落库的相似度检索，替代当前 mock 相似度。

数据来源双库隔离（演示 / 实际）：
    - demo 源：来自种子 cases.json（cases.db），用于复赛演示，绝不混入真实业务数据。
    - real 源：初始为空（cases_real.db），由网页「数据录入」添加实际退货案件。
    - 两源各自独立库文件/实例，物理隔离；通过 ?source=demo|real 或前端顶栏开关切换，
      切换零代码。所有仓储函数均带 source 参数（默认 demo），向后兼容。

工程化（大厂对标）：
    - 引擎**懒初始化**（get_engine），去除 import 期副作用，便于测试注入内存库；
    - 日志走 logging 而非 print，便于容器采集与分级；
    - date 列用 Date 类型（而非 String），保留日期可查询/可索引能力；
    - load_cases 加结果缓存，save/delete 时失效，避免每次洞察请求全表重扫。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger("returnguard.db")

# ---- 兼容性补丁：让 SQLAlchemy 识别 openGauss 版本号（懒挂接，去除 import 期副作用）----
# openGauss 兼容 PG 协议，但其 `SELECT version()` 返回 "(openGauss 5.0.0 ...)"，导致 SQLAlchemy
# 的 PG 方言抛 AssertionError。这里在连接初始化时拦截版本字符串抽出主版本号。
# 原实现会在 import 期无条件改写 PGDialect（即便用 SQLite 也执行，属全局副作用、对库内部实现脆弱）；
# 现改为仅当 DATABASE_URL 指向 openGauss / PostgreSQL 时才挂接（见 get_engine）。
_original_get_server_version_info = PGDialect._get_server_version_info


def _get_server_version_info_for_opengauss(self, connection):
    raw = connection.exec_driver_sql("SELECT version()").scalar()
    if raw and "openGauss" in raw:
        match = re.search(r"openGauss\s+(\d+)\.(\d+)(?:\.(\d+))?", raw)
        if match:
            return tuple(int(g) for g in match.groups() if g is not None)
    return _original_get_server_version_info(self, connection)


def _patch_opengauss_dialect(url: str) -> None:
    """仅在连接 openGauss / PostgreSQL 时改写方言版本探测，避免 import 期全局副作用。"""
    if "opengauss" in url or url.startswith("postgresql"):
        PGDialect._get_server_version_info = _get_server_version_info_for_opengauss
        logger.info("已挂接 openGauss 版本探测补丁")


# ---- 连接配置：默认 SQLite 双源隔离；部署期改环境变量即可切 openGauss ----
# 演示数据（demo）：来自种子 cases.json；实际数据（real）：用户在网页「数据录入」添加，初始为空。
# 两源各自独立库文件，物理隔离，互不污染；切换零代码（env 或前端 source 参数）。
BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SQLITE = "sqlite:///" + os.path.join(BASE, "cases.db")
REAL_SQLITE = "sqlite:///" + os.path.join(BASE, "cases_real.db")
# 兼容旧部署：若设置了 DATABASE_URL 则作为 demo 源（保持原有行为）
DEMO_DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_SQLITE)
REAL_DATABASE_URL = os.environ.get("REAL_DATABASE_URL", REAL_SQLITE)
SOURCES = {"demo": DEMO_DATABASE_URL, "real": REAL_DATABASE_URL}
DEFAULT_SOURCE = "demo"
VALID_SOURCES = ("demo", "real")
# 多租户（C组）：real 源案件按 tenant_id 隔离。
# "public" 为公共基准数据（匿名录入 / 启动自动导入），所有租户可见；私有租户数据严格隔离。
PUBLIC_TENANT = "public"


def _normalize_source(source) -> str:
    """把请求/调用里的 source 归一化为合法值，非法或缺失一律回退 demo。"""
    if source in VALID_SOURCES:
        return source
    return DEFAULT_SOURCE


# 切换 openGauss 示例（部署期设置环境变量，无需改代码）：
#   DATABASE_URL=postgresql+psycopg2://gaussdb:你的密码@数据库主机:5432/returnguard
#   REAL_DATABASE_URL=postgresql+psycopg2://gaussdb:你的密码@数据库主机:5432/returnguard_real
# 进阶：想用 openGauss 官方方言时改为 opengauss+psycopg2://...（需 pip install opengauss-sqlalchemy）

# ---- 懒初始化：每个 source 独立引擎与 session 工厂（首次使用时创建，去除 import 期副作用）----
_engines: dict = {}
_sessions: dict = {}
# 线程安全锁（P3-⑧）：uvicorn 默认以线程池跑同步端点，多并发读写这些模块级可变结构需加锁，
# 避免 dict 并发读写竞态（同一进程内线程安全；多 worker 跨进程仍需 Redis 共享缓存）。
_engine_lock = threading.Lock()


def get_engine(source: str = DEFAULT_SOURCE):
    """返回（必要时创建）指定 source 的数据库引擎。便于测试时替换 DATABASE_URL 后重新获取。"""
    source = _normalize_source(source)
    with _engine_lock:
        if source in _engines:
            return _engines[source]
        url = SOURCES[source]
        _patch_opengauss_dialect(url)
        logger.info(
            "初始化数据库引擎[%s]: %s",
            source,
            url.split("@")[-1] if "://" in url else url,
        )
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engines[source] = create_engine(
            url,
            connect_args=connect_args,
            future=True,
            pool_pre_ping=True,
        )
        return _engines[source]


def get_session(source: str = DEFAULT_SOURCE):
    """返回一个短生命周期 Session（用 with 管理）。"""
    source = _normalize_source(source)
    engine = get_engine(source)  # 内部已加锁并返回
    with _engine_lock:
        if source not in _sessions:
            _sessions[source] = sessionmaker(bind=engine, expire_on_commit=False)
        return _sessions[source]()


Base = declarative_base()

# ---- 结果缓存：load_cases 全表扫描较重，按 source 缓存；写入时失效 ----
_cache: dict = {"demo": None, "real": None}

# 洞察聚合缓存失效用的「代际」计数器（按 source 独立）：每次写库自增；pipeline.build_insights 据此判断缓存是否过期
_generations: dict = {"demo": 0, "real": 0}
# 缓存/代际的线程安全锁（P3-⑧）
_cache_lock = threading.Lock()


def _invalidate_cache(source: str = DEFAULT_SOURCE) -> None:
    source = _normalize_source(source)
    with _cache_lock:
        _cache[source] = None


def bump_generation(source: str = DEFAULT_SOURCE) -> None:
    """写库后自增代际，使依赖聚合结果的缓存失效。"""
    source = _normalize_source(source)
    with _cache_lock:
        _generations[source] += 1


def get_generation(source: str = DEFAULT_SOURCE) -> int:
    with _cache_lock:
        return _generations[_normalize_source(source)]


class Case(Base):
    """案件表：一条跨境退货/纠纷取证记录。

    字段与 cases.json 完全对齐；defect_tags 用 JSON 列兼容 list[str]；
    date 用 Date 类型（保留可查询性），仓储层做 str↔date 双向转换，业务层仍见字符串。
    """

    __tablename__ = "cases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(64), index=True)  # RG-000001 / 上传时的临时 rid
    sku = Column(String(64), index=True)
    sku_name = Column(String(128))
    category = Column(String(64), index=True)  # 3C数码/饰品配件/小家电/服饰鞋包
    supplier = Column(String(32), index=True)  # 供应商编号 S1~S8
    supplier_name = Column(String(128))
    platform = Column(String(32), index=True)  # Amazon/AliExpress/Temu/SHEIN
    language = Column(String(16))  # 举证语种
    region = Column(String(32))  # 销售地区
    amount = Column(Float, default=0.0)  # 退款/争议金额(¥)
    date = Column(Date)  # 案件日期 YYYY-MM-DD（Date 类型）
    similarity = Column(Float, default=0.0)  # 与本店主图相似度
    same_item = Column(Boolean, default=True)  # 是否同一件商品
    defect_tags = Column(JSON)  # 瑕疵标签 list[str]
    defect_description = Column(Text)  # 瑕疵文字描述
    consistency = Column(Text)  # 与 listing 承诺一致性判定
    outcome = Column(String(32))  # 赢/部分退款/输/未知
    mode = Column(String(32))  # synthetic/mock/live
    # 以下为单案上传(/api/analyze)时附带，种子数据可能为空
    listing_text = Column(Text)
    priority_score = Column(Float)
    returned_image = Column(String(256))
    product_image = Column(String(256))
    # 单案取证完整留存（便于案件复盘 / 红框回放；规模部署建议音频/大图改对象存储 URL）
    dossier = Column(Text)  # 举证报告正文
    voice_text = Column(Text)  # 母语语音陈述文本
    voice_audio_b64 = Column(Text)  # 语音 base64（演示用）
    defect_boxes = Column(JSON)  # 关键帧缺陷示意框（归一化坐标 0~1）
    # 多租户隔离（C组）：real 源按 tenant_id 隔离；demo 源为共享演示库，恒为 "demo"，不参与隔离。
    # 历史/匿名数据 tenant_id 为 NULL，查询时按 "public" 处理（见 load_cases 等）。
    tenant_id = Column(String(64), index=True)


_COLUMNS = {c.name for c in Case.__table__.columns}


def _norm_date(v):
    """把任意来源的 date（None / str / date / datetime）规整为 date 或 None。"""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return datetime.strptime(v.strip(), "%Y-%m-%d").date()
        except Exception:
            logger.warning("非法日期格式，忽略: %r", v)
            return None
    return None


def _row_to_dict(row) -> dict:
    """ORM 行 → dict（JSON 列自动还原为 list；date 转回 ISO 字符串供业务层使用）。"""
    d = {c.name: getattr(row, c.name) for c in Case.__table__.columns}
    if isinstance(d.get("date"), (datetime, date)):
        d["date"] = d["date"].isoformat()
    return d


def _dict_to_row(d: dict) -> Case:
    """dict → ORM 行（只取表中存在的列，忽略 dossier/voice 等临时字段）。"""
    data = {k: v for k, v in d.items() if k in _COLUMNS}
    # JSON 列若为空给默认，避免后续聚合索引报错
    if data.get("defect_tags") is None:
        data["defect_tags"] = ["无明显瑕疵"]
    # date 统一规整为 date 对象，适配 Date 列
    if "date" in data:
        data["date"] = _norm_date(data["date"])
    return Case(**data)


# 录入列表所需的轻量字段投影：避免把每条案件的 base64 语音 / 举证长文一并拉回前端。
# demo 库 674 条若含 voice_audio_b64，整库响应体可达约 25MB；列表接口只投影看板与删除
# 所需字段，从源头消除大响应体（P3-①）。
_LIST_FIELDS = (
    Case.case_id,
    Case.sku,
    Case.sku_name,
    Case.category,
    Case.supplier,
    Case.supplier_name,
    Case.amount,
    Case.outcome,
    Case.date,
    Case.platform,
)


def _row_to_slim_dict(r) -> dict:
    """仅取列表展示字段，date 转 ISO 字符串。"""
    d = dict(r._mapping)
    if isinstance(d.get("date"), (datetime, date)):
        d["date"] = d["date"].isoformat()
    return d


def list_cases(source: str = DEFAULT_SOURCE, tenant_id: str | None = None) -> list[dict]:
    """读取指定 source 的案件「列表投影」（仅关键字段），用于数据录入页列表展示与删除。

    与 load_cases 的区别：用 ORM 列投影只取列表所需字段，不返回 voice_audio_b64 /
    dossier / listing_text 等大字段，从源头避免整库 25MB 级响应体（P3-①）。
    tenant_id：仅 real 源生效（多租户隔离），NULL 视为 "public" 一并返回。
    """
    source = _normalize_source(source)
    with get_session(source) as s:
        q = s.query(*_LIST_FIELDS)
        if source == "real" and tenant_id is not None:
            q = q.filter(
                (Case.tenant_id == tenant_id)
                | (Case.tenant_id.is_(None))
                | (Case.tenant_id == PUBLIC_TENANT)
            )
        rows = q.all()
    return [_row_to_slim_dict(r) for r in rows]


def _migrate_case_columns(engine) -> None:
    """Schema 演进（彻底解决「漂移坑」）：已存在的 cases 表可能缺若干列（部署期/开发期
    Schema 演进，例如 dossier / voice_text / voice_audio_b64 / defect_boxes / tenant_id），
    用 inspect 探测后逐列 ALTER TABLE 追加，避免存量库因缺列而查询失败。

    关键点：SQLAlchemy 的 ``create_all`` **只会建缺失的表、不会 ALTER 已有表补列**，所以
    任何后来新增的模型列都不会自动落到存量库上——这正是 openGauss 部署报
    ``column cases.dossier does not exist`` 的根因。本函数对所有 ``Case`` 模型列做通用补列，
    今后新增列也无需再手动维护迁移逻辑（不再靠删表重建）。

    SQLite 与 openGauss/PostgreSQL 均适用：所有列均 nullable、无 NOT NULL 约束，
    ``ALTER TABLE ... ADD COLUMN`` 在两类库均可直接执行；列类型用当前模型 DDL（按目标方言
    compile）与 ``create_all`` 新建表时保持一致。索引在 ALTER 路径下不会被自动重建，故对
    带 ``index=True`` 的缺列一并兜底补建。
    """
    from sqlalchemy import inspect

    try:
        existing = {c["name"] for c in inspect(engine).get_columns("cases")}
    except Exception:  # noqa: BLE001
        return  # 表尚不存在，交给 create_all
    if not existing:
        return

    dialect = engine.dialect
    missing = []
    for col in Case.__table__.columns:
        if col.name in existing:
            continue  # 已存在，跳过（主键 id 因已存在也会在此被跳过）
        try:
            col_type = col.type.compile(dialect=dialect)
        except Exception:  # noqa: BLE001
            col_type = "TEXT"  # 兜底：SQLite 下可正常落库
        missing.append((col.name, col_type, col.index and not col.primary_key))

    if not missing:
        return

    logger.info(
        "[migrate] cases 表缺失 %d 列，执行 ALTER TABLE 追加: %s",
        len(missing),
        [m[0] for m in missing],
    )
    # 逐列独立事务：某一列在目标库不支持（如特殊类型）时只告警、不中断其他列的补列，
    # 避免整段回滚导致所有缺列都没补上（生产保真部署更稳健；create_all 失败也不致命）。
    added, failed = [], []
    for name, col_type, need_idx in missing:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE cases ADD COLUMN {name} {col_type}"))
                if need_idx:  # 兜底补索引（create_all 在 ALTER 路径下不会重建索引）
                    idx_name = f"ix_cases_{name}"
                    conn.execute(
                        text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON cases ({name})")
                    )
            added.append(name)
        except Exception:  # noqa: BLE001
            logger.warning("[migrate] 补列失败（已跳过，不影响其余列）: %s %s", name, col_type)
            failed.append(name)

    if added:
        logger.info("[migrate] 已补列 %d 个: %s", len(added), added)
    if failed:
        logger.warning("[migrate] 仍有 %d 列补列失败（需人工介入）: %s", len(failed), failed)


def init_db(
    source: str = DEFAULT_SOURCE, seed_json: str | None = None, force: bool = False
) -> None:
    """建表；若库为空（或 force=True）且为 demo 源，则导入种子 JSON，保证克隆/部署后演示数据一致。

    force=True 会先 drop 全部表再重建并重新导入——用于本地重新生成了 cases.json 后刷新库
    （解决「seed-only-when-empty」：旧库已存在时改了 schema/数据不会自动刷新）。
    real 源不播种，初始为空，待用户在网页「数据录入」添加实际退货案件。
    """
    source = _normalize_source(source)
    engine = get_engine(source)
    if force:
        logger.info("[%s] force=True：重置案件库（drop_all + 重建 + 重新导入）", source)
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    _migrate_case_columns(engine)  # 通用 Schema 演进：存量库补缺失列（含多租户 tenant_id）
    if source == "demo":
        if seed_json is None:
            seed_json = os.path.join(BASE, "cases.json")
        with get_session(source) as s:
            count = s.query(Case).count()
            if (force or count == 0) and os.path.exists(seed_json):
                with open(seed_json, encoding="utf-8") as f:
                    rows = json.load(f)
                for c in rows:
                    s.add(_dict_to_row(c))
                s.commit()
                logger.info("[%s] 已从 %s 导入 %d 条案件", source, seed_json, len(rows))
            else:
                logger.info("[%s] 案件库已存在 %d 条，跳过种子导入", source, count)
    else:
        logger.info("[%s] 实际数据库就绪（空库，待录入）", source)


def load_cases(source: str = DEFAULT_SOURCE, tenant_id: str | None = None) -> list[dict]:
    """读取指定 source 的案件，返回 list[dict]。带按 source 的结果缓存（仅 tenant_id=None 时缓存共享视图）。

    tenant_id：仅 real 源生效（多租户隔离）。demo 源忽略（共享演示库）。
    历史/匿名数据 tenant_id 为 NULL，按 "public" 一并返回，保证向后兼容。
    """
    source = _normalize_source(source)
    if tenant_id is None:
        with _cache_lock:
            if _cache[source] is not None:
                return _cache[source]
    with get_session(source) as s:
        q = s.query(Case)
        if source == "real" and tenant_id is not None:
            q = q.filter(
                (Case.tenant_id == tenant_id)
                | (Case.tenant_id.is_(None))
                | (Case.tenant_id == PUBLIC_TENANT)
            )
        data = [_row_to_dict(r) for r in q.all()]
    if tenant_id is None:
        with _cache_lock:
            _cache[source] = data
    return data


def save_case(
    source: str = DEFAULT_SOURCE, case: dict | None = None, tenant_id: str | None = None
) -> None:
    """追加一条案件到指定 source（替代原 save_case(path, case)），并失效对应缓存。

    tenant_id：仅 real 源生效（多租户隔离）。demo 源恒为共享演示库（"demo"），不参与隔离；
    real 源缺省归 "public"（匿名/启动自动导入的数据），认证用户的数据归其自身租户。
    """
    source = _normalize_source(source)
    if case is None:
        return
    data = dict(case)
    data["tenant_id"] = "demo" if source == "demo" else (tenant_id or "public")
    with get_session(source) as s:
        s.add(_dict_to_row(data))
        s.commit()
    _invalidate_cache(source)
    bump_generation(source)
    # 聚合洞察结果可能已变，失效 pipeline 层缓存（懒导入避免循环依赖）
    try:
        from pipeline import invalidate_insights_cache

        invalidate_insights_cache()
    except Exception:  # 缓存失效失败不应影响主流程
        logger.warning("洞察缓存失效失败（可忽略）", exc_info=True)


def get_case(
    source: str = DEFAULT_SOURCE, case_id: str = "", tenant_id: str | None = None
) -> dict | None:
    """按 case_id 查指定 source 的单条案件。real 源按 tenant_id 隔离（NULL 视为 public）。"""
    source = _normalize_source(source)
    with get_session(source) as s:
        q = s.query(Case).filter_by(case_id=case_id)
        if source == "real" and tenant_id is not None:
            q = q.filter(
                (Case.tenant_id == tenant_id)
                | (Case.tenant_id.is_(None))
                | (Case.tenant_id == PUBLIC_TENANT)
            )
        r = q.first()
        return _row_to_dict(r) if r else None


def delete_case(
    source: str = DEFAULT_SOURCE, case_id: str = "", tenant_id: str | None = None
) -> int:
    """按 case_id 删除指定 source 的一条案件，返回删除条数，并失效对应缓存。
    real 源按 tenant_id 隔离：仅能删除本租户（或 public 匿名）的案件。"""
    source = _normalize_source(source)
    with get_session(source) as s:
        q = s.query(Case).filter_by(case_id=case_id)
        if source == "real" and tenant_id is not None:
            q = q.filter(
                (Case.tenant_id == tenant_id)
                | (Case.tenant_id.is_(None))
                | (Case.tenant_id == PUBLIC_TENANT)
            )
        n = q.delete()
        s.commit()
    _invalidate_cache(source)
    bump_generation(source)
    try:
        from pipeline import invalidate_insights_cache

        invalidate_insights_cache()
    except Exception:
        logger.warning("洞察缓存失效失败（可忽略）", exc_info=True)
    return n
