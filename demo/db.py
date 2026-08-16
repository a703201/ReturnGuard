"""ReturnGuard · 数据持久层（仓储层）

职责：把「案件」这一核心数据从 JSON 文件升级为**数据库**，解决原 cases.json 全量读写
带来的并发覆盖、无数据模型、无事务等问题，并为复赛切换到国产数据库 openGauss 预留
同构接口。

双轨设计（开发期 / 部署期**零代码改动**切换）：
    - 开发期（默认）：SQLite 文件库，零部署、随起随用，不卡初赛进度。
    - 部署期（复赛）：设置环境变量 DATABASE_URL 指向 openGauss 即可，业务代码不变。
      openGauss 是华为开源的国产关系型数据库（兼容 PostgreSQL 协议）；其向量能力还可
      进一步把「图向量比对」做成真实落库的相似度检索，替代当前 mock 相似度。

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
)
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger("returnguard.db")

# ---- 兼容性补丁：让 SQLAlchemy 识别 openGauss 版本号 ----
# openGauss 兼容 PG 协议，但 `SELECT version()` 返回的是
#   "(openGauss 5.0.0 build a07d57c3) compiled at ..."
# SQLAlchemy 2.0 的 PG 方言只认 "PostgreSQL XX.X" 格式，会抛
#   AssertionError: Could not determine version from string '(openGauss 5.0.0 ...'
# 这里在连接初始化时拦截版本字符串，抽出 openGauss 主版本号返回，即可正常跑。
# 参考：https://gitee.com/opengauss/opengauss-sqlalchemy（原理相同，但本补丁无额外依赖）
_original_get_server_version_info = PGDialect._get_server_version_info


def _get_server_version_info_for_opengauss(self, connection):
    raw = connection.exec_driver_sql("SELECT version()").scalar()
    if raw and "openGauss" in raw:
        match = re.search(r"openGauss\s+(\d+)\.(\d+)(?:\.(\d+))?", raw)
        if match:
            return tuple(int(g) for g in match.groups() if g is not None)
    return _original_get_server_version_info(self, connection)


PGDialect._get_server_version_info = _get_server_version_info_for_opengauss

# ---- 连接配置：默认 SQLite，部署期改环境变量即可切 openGauss ----
BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SQLITE = "sqlite:///" + os.path.join(BASE, "cases.db")
# 切换 openGauss 示例（部署期设置环境变量，无需改代码）：
#   DATABASE_URL=postgresql+psycopg2://gaussdb:你的密码@数据库主机:5432/returnguard
# 进阶：想用 openGauss 官方方言（识别 openGauss 特有类型/索引）时改为：
#   DATABASE_URL=opengauss+psycopg2://gaussdb:你的密码@数据库主机:5432/returnguard
#   （需 pip install opengauss-sqlalchemy）
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_SQLITE)

# SQLite 需允许多线程复用连接（FastAPI 事件循环会并发访问）；openGauss 不需要
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# ---- 懒初始化：引擎与 session 工厂在首次使用时才创建，去除 import 期副作用 ----
_engine = None
_SessionLocal = None


def get_engine():
    """返回（必要时创建）数据库引擎。便于测试时替换 DATABASE_URL 后重新获取。"""
    global _engine
    if _engine is None:
        logger.info(
            "初始化数据库引擎: %s",
            DATABASE_URL.split("@")[-1] if "://" in DATABASE_URL else DATABASE_URL,
        )
        _engine = create_engine(
            DATABASE_URL,
            connect_args=_connect_args,
            future=True,
            pool_pre_ping=True,
        )
    return _engine


def get_session():
    """返回一个短生命周期 Session（用 with 管理）。"""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal()


Base = declarative_base()

# ---- 结果缓存：load_cases 全表扫描较重，加缓存；写入时失效 ----
_cache: dict[str, list[dict] | None] = {"cases": None}


def _invalidate_cache() -> None:
    _cache["cases"] = None


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
    platform = Column(String(32), index=True)  # AliExpress/Amazon/PayPal/TikTok Shop
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


def init_db(seed_json: str | None = None) -> None:
    """建表；若库为空且存在种子 JSON，则导入，保证克隆/部署后演示数据一致。"""
    Base.metadata.create_all(get_engine())
    if seed_json is None:
        seed_json = os.path.join(BASE, "cases.json")
    with get_session() as s:
        count = s.query(Case).count()
        if count == 0 and os.path.exists(seed_json):
            with open(seed_json, encoding="utf-8") as f:
                rows = json.load(f)
            for c in rows:
                s.add(_dict_to_row(c))
            s.commit()
            logger.info("已从 %s 导入 %d 条案件", seed_json, len(rows))
        else:
            logger.info("案件库已存在 %d 条，跳过种子导入", count)


def load_cases() -> list[dict]:
    """读取全部案件（替代原 load_cases(path)），返回 list[dict]。带结果缓存。"""
    if _cache["cases"] is not None:
        return _cache["cases"]
    with get_session() as s:
        data = [_row_to_dict(r) for r in s.query(Case).all()]
    _cache["cases"] = data
    return data


def save_case(case: dict) -> None:
    """追加一条案件（替代原 save_case(path, case)），并失效缓存。"""
    with get_session() as s:
        s.add(_dict_to_row(case))
        s.commit()
    _invalidate_cache()


def get_case(case_id: str) -> dict | None:
    """按 case_id 查单条案件。"""
    with get_session() as s:
        r = s.query(Case).filter_by(case_id=case_id).first()
        return _row_to_dict(r) if r else None


def delete_case(case_id: str) -> int:
    """按 case_id 删除一条案件，返回删除条数，并失效缓存。"""
    with get_session() as s:
        n = s.query(Case).filter_by(case_id=case_id).delete()
        s.commit()
    _invalidate_cache()
    return n
