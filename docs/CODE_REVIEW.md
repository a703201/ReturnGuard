# ReturnGuard 代码与工程化审查（大厂对标）

> 审查基准：大厂后端服务工程标准（分层清晰、强契约、类型安全、测试门禁、安全加固、配置单一来源、可观测、CI/CD、容器加固）。
> 审查范围：`demo/`（main/pipeline/db/models_router/generate_dataset/requirements）、`docker/`（Dockerfile/compose/entrypoint/.env.example/.dockerignore）、`verify_api.py`、`README.md`。
> 结论基调：架构分层合理、文档较完整、mock/live 双轨设计好；差距集中在**契约与类型、测试与质量门禁、安全加固、配置中心化、可观测性、CI/CD**——均为「可补强项」，无阻断性逻辑错误（无 P0）。

---

## 一、分层评分（当前 → 大厂目标）

| 维度 | 当前 | 目标 | 差距 |
|---|---|---|---|
| 架构分层（路由/业务/数据/模型） | B+ | A | 基本到位，依赖在 import 期耦合 |
| 接口契约与类型（Pydantic / response_model） | C | A | 返回裸 dict，无校验 |
| 代码质量（type hints / lint / 重复） | C | A | 几乎无类型；常量与阈值重复；巨型函数 |
| 测试（单测/集成测） | D | B | 零测试，仅人工连通脚本 |
| 安全（上传/配置/鉴权） | C | B | 文件名路径穿越；无文件校验；配置漂移 |
| 配置管理（12-factor 单一来源） | C | A | 三处散读 env；存在死配置 |
| 数据建模（类型/迁移） | B | A | date 存 String；无 Alembic 迁移 |
| 可观测性（logging/metrics） | C | B | 用 print 而非 logging；无结构化日志/指标 |
| CI/CD | D | B | 无 GitHub Actions |
| Docker 加固 | B | A | root 运行；app 无 healthcheck；无资源限制 |
| 文档（README/PRD/API） | B+ | A | 良好，README 引用的方案文件需确认在仓库 |

**总评**：初赛 demo 可过关；复赛/对外演示前，建议优先补齐 P1（安全+配置）与 P2（契约+类型），再补 P3（测试+CI）。

---

## 二、问题清单（按严重度）

### P1 — 安全与配置（应必修）
1. **上传文件名路径穿越（高危）**
   - 位置：`demo/main.py:67-68`
   - 现状：`os.path.join(UPLOAD_DIR, f"{rid}_ret_{returned_image.filename}")`，客户端文件名未经清洗直接拼路径。若上传 `../../etc/cron.d/x`，文件可写至 `UPLOAD_DIR` 之外。
   - 修复：用 `os.path.basename()` + 白名单清洗，并断言结果仍在 `UPLOAD_DIR` 内。
     ```python
     import re
     _SAFE = re.compile(r"[^A-Za-z0-9._-]")
     def _safe_name(name: str) -> str:
         return _SAFE.sub("_", os.path.basename(name or "file"))
     fn = _safe_name(returned_image.filename)
     rp = os.path.join(UPLOAD_DIR, f"{rid}_ret_{fn}")
     assert os.path.dirname(os.path.abspath(rp)) == UPLOAD_DIR, "路径越界"
     ```

2. **`MODEL_ROUTER_BASE_URL` 死配置**
   - 位置：`docker/.env.example`/`docker-compose.yml` 暴露该变量，但 `demo/models_router.py:30` 硬编码 `API_BASE = "https://model-router.edu-aliyun.com/v1"`，全代码未读取该变量。
   - 影响：用户配了 `MODEL_ROUTER_BASE_URL` 不生效，文档与实际行为不一致。
   - 修复：`API_BASE = os.environ.get("MODEL_ROUTER_BASE_URL", "https://model-router.edu-aliyun.com/v1")`。

3. **上传无文件类型/大小校验**
   - 位置：`demo/main.py` `/api/analyze`
   - 现状：接受任意类型、任意大小文件；非图片也会被当退货图落盘，有存储滥用/DoS 风险。
   - 修复：校验 `content-type` 与魔数（PNG/JPEG 头），限制单文件大小（如 ≤10MB）。

4. **app 容器无 healthcheck**
   - 位置：`docker/docker-compose.yml` 仅 `db` 有 healthcheck，`app` 无。
   - 影响：编排依赖仅 `service_healthy` 针对 db；app 自身挂了编排无法感知重启。
   - 修复：为 app 增加 `healthcheck: ["CMD-SHELL", "curl -fsS http://localhost:8000/health || exit 1"]`，并新增 `GET /health` 轻量探针。

5. **缺少根 `.gitignore`，`.env` 漏跟踪风险**
   - 现状：`demo/.gitignore` 已忽略 `cases.db`/`uploads`/`.env`，但**仓库根无 `.gitignore`**。若在 `docker/` 创建 `.env`，会被 git 跟踪，存在密钥泄露风险。
   - 修复：根目录补 `.gitignore`，忽略 `.env`、`__pycache__/`、`*.db`、`uploads/`（保留 `.gitkeep`）。

### P2 — 代码质量与可维护性
6. **无 Pydantic 请求/响应契约**
   - 现状：端点入参用 `Form`/`Query` 裸收，返回 `JSONResponse(result)`（裸 dict）。无 `response_model` → OpenAPI 文档无结构、前端无类型、无自动校验。
   - 修复：定义 `AnalyzeRequest`/`AnalyzeResult`/`Insights` 等 Pydantic 模型；`/api/analyze` 用 `File`+`Form` 仍可行，但返回 `AnalyzeResult`；`/api/insights` 返回 `Insights`。

7. **几乎无类型注解 + 无 lint/format 门禁**
   - 现状：仅 `db.py` 有少量注解；`pipeline.py`/`models_router.py` 函数零注解。无 `ruff`/`black`/`mypy` 配置。
   - 修复：全量加 `type hints`；仓库加 `pyproject.toml`（ruff + black + mypy strict），提交前 pre-commit。

8. **巨型函数 + 常量/阈值重复**
   - 位置：`pipeline._aggregate`（约 190 行单体）；`SEVERITY` 表在 `pipeline` 与 `models_router.live_analyze` 重复；`0.82` 同款阈值在两处各写一份。
   - 影响：难测、易漂移（两处阈值以后会不一致）。
   - 修复：把 `_aggregate` 拆成 `category/supplier/platform/matrix/sku` 若干纯函数；常量抽到 `constants.py`（含 `SAME_ITEM_THRESHOLD=0.82`）。

9. **裸 `except Exception` 吞异常**
   - 位置：`pipeline.analyze_case`(回退)、`build_insights`(回退)、`db._parse_date`、`models_router._extract_json`。
   - 现状：回退逻辑用 `except Exception` 是必要的（保演示不中断），但会一并吞掉编程错误。
   - 修复：至少 `logger.exception(...)` 记录；回退前区分预期异常（网络/超时）与意外异常。

10. **数据建模：`date` 存 String + 无迁移**
    - 位置：`demo/db.py:87` `date = Column(String(32))`；`init_db` 用 `create_all` 无 Alembic。
    - 影响：无法按日期做 SQL 范围查询/索引；schema 变更靠删库重建。
    - 修复：`date = Column(Date)`（聚合层已会 `strptime`，可两端打通）；引入 Alembic 做迁移（demo 阶段可暂缓，但复赛建议加）。

11. **`load_cases` 全表扫描、无缓存/分页**
    - 位置：`db.load_cases` 每次 `/api/insights` 全量 `query(Case).all()`。
    - 影响：数据量大时每次请求 O(N) 拉全表 + 重算聚合。
    - 修复：加结果缓存（如 `functools.lru_cache` 按 `mode+category+platform`）；或聚合下沉到 SQL（`GROUP BY`）。

12. **模块级 import 副作用**
    - 位置：`pipeline.py:152` `from db import load_cases, save_case`（import 时即触发 `db.py` 建 `engine`）；`db.py` 顶部 monkeypatch 在 import 期改全局 `PGDialect._get_server_version_info`。
    - 影响：测试无法隔离；配置必须在 import 前就位。
    - 修复：配置/引擎用懒初始化（`get_engine()` 工厂），测试可注入内存库。

### P3 — 工程化（复赛前补）
13. **无自动化测试**：补 `tests/`——`test_pipeline_mock.py`（校验 `_mock`/`_aggregate`/`_mock_attribution` 字段与单调性）、`test_api.py`（FastAPI `TestClient` 打 `/api/analyze`、`/api/insights` 健康路径）、`test_security.py`（路径穿越被拒）。
14. **无 CI**：加 `.github/workflows/ci.yml`——lint(ruff)+type(mypy)+test(pytest)，PR 必过。
15. **Dockerfile 以 root 运行**：加 `useradd -m appuser && USER appuser`；`uploads/` 属主改 appuser。
16. **`print` → `logging`**：`db.init_db` 的 `print` 改为 `logging.getLogger(__name__)`，结构化日志便于容器采集。
17. **live 模式图片外链未落地**：`live_analyze` 仅拼 `PUBLIC_IMAGE_BASE/basename`，但应用从未把 `uploads/` 同步到对象存储。需补「上传即回传图床 / 起静态服务 + 内网 DNS」任一方案，否则 live 图片端点实际拿不到图。

---

## 三、已做对的地方（保留）
- 分层清晰：路由(`main`) / 业务(`pipeline`) / 数据(`db`) / 外部模型(`models_router`) 职责分明。
- mock/live 双轨 + 失败自动回退，保证演示不中断（设计正确，仅回退粒度可优化）。
- `.dockerignore` 已正确排除 `__pycache__`/`cases.db`/`uploads`/`*.md`（镜像不混运行期产物）。
- `docker/` 与 `demo/` 解耦、build context=仓库根，部署配置与源码分离（大厂惯例）。
- 密钥走 env + `.env.example` 模板，未硬编码（除一处 BASE_URL 硬编码见 P1-2）。
- 文档齐备：README + PRD + API，且 API 文档与真实接口字段已同步。

---

## 四、建议落地顺序（复赛前）
- **Phase 1（必修，约 0.5 天）**：P1-1 路径穿越、P1-2 死配置、P1-3 文件校验、P1-4 app healthcheck、P1-5 根 .gitignore。
- **Phase 2（强契约，约 1 天）**：P2-6 Pydantic 契约、P2-7 类型注解+linter、P2-8 常量/函数拆分、P2-9 异常日志。
- **Phase 3（工程化，约 1 天）**：P2-10/11 数据建模与缓存、P3-13 测试、P3-14 CI、P3-15/16 Docker 非 root + logging、P3-17 live 图床落地。
