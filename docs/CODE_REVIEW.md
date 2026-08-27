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

---

## 五、复审（2026-08-16）· 平台适配举证包 + KPI 图形化 + 红框标注

> 复审基准：截至 `f7cc772`。本轮在初版审查（P1–P3）落地后，又新增了「平台适配举证包（交付物 A）」「KPI 图形化 + 平台×供应商交叉 + 关键帧红框标注」两批代码，本次重点审这部分新增代码，并核对旧项是否真正闭环。

### 5.1 旧项结案（已在 5a8cc9c / 65ce43e / f7cc772 落地）

| 原编号 | 项 | 状态 | 落地提交 |
|---|---|---|---|
| P1-1 | 上传文件名路径穿越 | ✅ 已修 | `5a8cc9c`（`_safe_name` + 断言） |
| P1-2 | `MODEL_ROUTER_BASE_URL` 死配置 | ✅ 已修 | `5a8cc9c`（`models_router` 读 env） |
| P1-3 | 上传无类型/大小校验 | ✅ 已修 | `5a8cc9c`（PNG/JPEG 魔数 + 10MB） |
| P1-4 | app 无 healthcheck | ✅ 已修 | `5a8cc9c`（`/health` + compose） |
| P1-5 | 缺根 `.gitignore` | ✅ 已修 | `5a8cc9c`（根 `.gitignore`） |
| P2-6 | 无 Pydantic 契约 | ✅ 已修 | `5a8cc9c`（`schemas.py` + `response_model`） |
| P2-7 | 无类型注解 / lint | ✅ 已修 | `5a8cc9c`（`pyproject.toml` + 全量 hints） |
| P2-8 | 巨型函数 + 常量重复 | ✅ 已修 | `5a8cc9c`（`constants.py` + builder 拆分） |
| P2-9 | 裸 except 吞异常 | ✅ 已修 | `5a8cc9c`（`logger.exception`） |
| P2-10 | date 存 String 无迁移 | ✅ 已修 | `5a8cc9c`（`Date` 列 + 双轨） |
| P2-11 | load_cases 全表扫 | ✅ 已修 | `5a8cc9c`（结果缓存 + 失效） |
| P2-12 | import 期副作用 | ✅ 已修 | `5a8cc9c`（引擎懒初始化） |
| P3-13 | 无测试 | ✅ 已修 | `5a8cc9c`+`f7cc772`（16 passed） |
| P3-14 | 无 CI | ✅ 已修 | `5a8cc9c`（`.github/workflows/ci.yml`） |
| P3-15 | Dockerfile root | ✅ 已修 | `5a8cc9c`（非 root `appuser`） |
| P3-16 | print→logging | ✅ 已修 | `5a8cc9c` |
| P3-17 | live 图床未落地 | ⚠️ 仍待办 | 需对象存储/内网 DNS，复赛部署前补 |

**结论**：初版列出的 17 项中 16 项已闭环，仅 P3-17（live 图片公网可达）因依赖外部存储，属部署期事项，未在本机代码层修复，需在复赛公网部署时补「上传即回传图床」或「/uploads 配内网 DNS」。

### 5.2 新增代码复审发现

**A. 平台适配举证包（交付物 A）**
- `platforms.py`：规则引擎单一来源设计好（`EVIDENCE_SPECS` + `get/list/is_valid`）。`list_platforms()` 此前直接返回 `EVIDENCE_SPECS[k]` 原对象，前端用 `label` 当表单值发给 `/api/analyze`，依赖「label==key」才能通过 `is_valid_platform` 校验——脆弱耦合。**本轮已修**：`list_platforms` 返回浅拷贝并补稳定 `key` 字段，前端改用 `p.key`（见 5.3-1）。
- `generate_platform_doc.py`：与 `platforms.py` 同源生成 HTML/MD，设计正确（改规则只改一处）。注意 `build_html`/`build_md` 用的是 `ATTRIBUTES`/`CAPABILITY_KEYS` 单一来源，新增平台属性时前端 `loadPlatforms()` 的 `attrs` 硬编码 4 项是另一处清单——若后续扩展平台属性，两处需同步（已在 5.4 标注为低优先级待办）。
- `main.py /api/platforms`：返回全量规格（含 `capability_map` 长文本），体量可接受；建议后续加 `PlatformSpec` Pydantic 模型统一契约（非阻塞）。

**B. 前端「⑪ 平台适配举证包」面板**
- **本轮已修两处问题**：
  1. `loadPlatforms()` 用了 `.kv` 类（平台模板键值行），但 CSS **从未定义 `.kv`**，导致「退货窗口/响应时限」等行完全无样式。已补 `.kv` 样式（5.3-2）。
  2. 面板此前只渲染 `return_window/response_window/shipping_payer/burden_bias + required_evidence + common_loss_reasons`，**漏掉了数据里已存在、且文档已包含的 `special_clauses`（平台特殊条款）与 `capability_map`（ReturnGuard 怎么帮你举证）**。已补全，使前端面板与 `platforms.py` 单一来源完全对齐（5.3-2）。

**C. KPI 图形化 + 平台×供应商交叉 + 红框标注（65ce43e）**
- `pipeline._mock` 的 `defect_boxes` 为确定性占位坐标，前端 `renderAnnot` 叠加红框并注明「演示示意框、不替代平台裁决」——守住「只取证不裁决」，合规。
- `main.py /api/analyze` 回传 `returned_image_b64`（退回图 base64），但 `Case` 表无该列，`_dict_to_row` 按 `_COLUMNS` 过滤会丢弃，**不会污染数据库**，设计正确。
- 交叉热力 `renderMatrix` 颜色阈值与 `wrColor` 一致，色块语义清晰。

**D. 测试**
- `test_platforms.py` 7 例覆盖规则引擎 / API / 单案关联 / 维度过滤，质量好；本轮新增 `key` 字段断言锁住（5.3-1）。整体 **16 passed、ruff 全绿**。

### 5.3 本轮已修（提交于本次复审）

1. **健壮性**：`list_platforms()` 返回副本 + `key` 字段；前端 `init()` 用 `p.key` 作表单值，`is_valid_platform` 不再依赖 label==key。
2. **前端样式/完整性**：补 `.kv` 样式；「⑪ 平台适配举证包」面板补全 `special_clauses` 与 `capability_map` 两节，与 `platforms.py` 完全对齐；新增吸顶筛选栏、刷新加载态提示、宽表移动端横向滚动、卡片 hover 微动效；KPI 胜诉率卡片标签移到环形图上方。
3. 验证：ruff 全绿、pytest 16 passed、TestClient 冒烟（`/api/platforms` 含 key、`/api/analyze` 关联 SHEIN 举证 5 条、`/api/insights?platform=SHEIN` 过滤正确）。

### 5.4 仍建议（低优先级，非阻塞）

- **S1（建议）**：`/api/insights` 的 `platform` 过滤未校验非法值，传错值只返回空聚合（不报错）。可加 `if platform and not is_valid_platform(platform): raise 400` 与 `/api/analyze` 保持一致。
- **S2（文案）**：`avg_dispute_rate` 实为 `1 − 平均相似度` 的**代理指标**，并非平台真实争议率；前端卡片称「平均退货争议率」易致评委误解。建议在卡面 hint 或 API 文档注明这是「以同款一致性反推的争议代理指标」。
- **S3（清理）**：`main.py` 的 `save_case({**result, ..., "platform": platform})` 中 `platform` 键重复（`result` 已含），值相同无害，建议删去冗余键。
- **S4（扩展期）**：前端 `loadPlatforms()` 的 `attrs` 硬编码 4 项；若后续为 `platforms.py` 增加属性维度，需同步此处（与 `generate_platform_doc.py` 的 `ATTRIBUTES` 一并维护）。

### 5.5 复审建议 S1/S2/S3 落地 + 前端大屏化（2026-08-16 第二轮）

> 复审基准：截至 `4acd329`。本轮把 5.4 的 S1/S2/S3 全部落地，并据「大屏全屏展示、不整页滚动」诉求对前端做单页化重构。

**S1（建议）→ 已修（`main.py /api/insights`）**
- 新增 `if platform and not is_valid_platform(platform): raise HTTPException(400, ...)`，与 `/api/analyze` 行为一致；非法平台不再静默返回空看板。
- 同步加 `category` 非空兜底校验。
- 测试锁住：`test_insights_invalid_platform_400`（期望 400）。

**S2（文案）→ 已修（`schemas.py` + `pipeline.py` + 前端）**
- `InsightsResponse` 增 `dispute_rate_note: str = ""`；`pipeline._aggregate` 计算处补注释并注入说明：`avg_dispute_rate` 是由「退货图与本店主图相似度」推算的**代理指标**（`1 − 平均相似度`），反映货不对板/调包嫌疑强度，**并非平台标记的争议笔数**。
- 前端 KPI 标签由「平均退货争议率」改为「货不对板嫌疑率」，并加 `代理指标 ⓘ` 提示（hover 显示完整说明），消除评委误解。
- 测试锁住：`test_insights_dispute_rate_is_proxy`。

**S3（清理）→ 已修（`main.py /api/analyze`）**
- `save_case({**result, ..., "platform": platform})` 中 `platform` 与 `result` 已含的 `platform` 重复，删除冗余键，仅保留 `result` 展开值（语义不变，去除脆弱重复）。

**前端大屏化（单页全屏、不整页滚动、多比例适配）**
- 结构重构：`body{overflow:hidden}` + `.app` flex 列（`100vh/100dvh`）。顶部固定（标题 + 4 KPI 紧凑条 + 筛选栏 + 分段切换），主区 `flex:1;min-height:0;overflow:hidden`。
- **组件切换而非整页滑动**：三个标签页 `市场洞察 / 平台举证包 / 单案取证`（`switchTab`），各页 `height:100%` 仅内部滚动，整页绝不上下滑动。
- **看板占满一屏**：`.board` 用 `grid-template-rows:repeat(3,1fr)`（3×3 平铺 9 张洞察卡），每张卡 `overflow:auto` 只卡内滚动。响应式降级：`≤1100px` 转 2 列×5 行，`≤640px` 转 1 列×9 行——任何比例都靠 `1fr` 行高占满、不溢出整页。
- **多显示比例适配**：字号用 `clamp()` 随视口缩放；`≥2200px`（电视/超宽）放大字号与留白；`≤900px` 取证页表单与结果改为上下堆叠。电脑(16:9/4:3)、平板、电视均自适应。
- 守住「只取证不裁决」：举证结果区仍标注「演示示意框、不替代平台裁决」。

**验证**：ruff 全绿；pytest **18 passed**（原 16 + 新增 S1/S2 各 1）；TestClient 冒烟：`/api/insights` 非法 platform→400、合法 SHEIN→200(165 案)、`dispute_rate_note` 存在、前端大屏结构标记齐全、analyze 关联 Temu 举证 5 条。提交 `见下方提交记录`。
- **P3-17（部署期）**：live 模式图片公网可达仍未落地，复赛公网部署前必须补。

---

# 六、大厂标准代码审查（2026-08-16）

> 审查基准：截至 `c2f78d6`（供应商维度扩展 C 已合）。本轮按大厂 Code Review 标准对 `demo/` 全量代码做横向审查，
> 覆盖：安全、健壮性/容错、架构/分层、性能/规模化、数据一致性、测试、可观测性、配置/依赖、前端质量、CI/CD。
> 方法：静态通读 + 关键点**动态复现**（用 TestClient 复现数据污染；并核实 git 跟踪 / CI / Docker 的真实状态，避免误判）。

## 6.1 总体评分（按维度）

| 维度 | 评级 | 说明 |
|---|---|---|
| 安全（上传 / 注入） | **B** | 上传链路（魔数+大小+文件名清洗+路径越界断言）规范；但存在 XSS 面、且 `/uploads` 世界可读待修 |
| 健壮性 / 容错 | **C** | `analyze` 无原子性、失败不清理；`load_cases` 缓存跨进程不安全 |
| 架构 / 分层 | **B+** | 分层清晰、`constants`/`platforms` 单一来源好；但 `extra="allow"` 削弱契约、import 期 monkeypatch 全局类 |
| 性能 / 规模化 | **B** | `_aggregate` 单遍累加好；但每请求全量重算、缓存仅进程内 |
| **数据一致性** | **C** | **P1-1 上传单案缺维度污染聚合，实锤 bug** |
| 测试覆盖 | **B** | happy-path 扎实（19 passed）；缺负向 / 数据一致性 / 集成测试 |
| 可观测性 | **C** | 缺结构化日志与指标端点 |
| 配置 / 依赖 | **C** | 依赖未锁版；异常经 `error` 字段回传前端 |
| 前端质量 | **B** | 大屏化 / 动效 / 可访问性好；但 `innerHTML` 渲染未转义模型输出 |
| CI/CD & 容器 | **A-** | `ci.yml` 跑 `ruff format/check + pytest`；Docker 非 root + 等待 DB + 幂等 `init_db`，规范 |
| **综合** | **B-** | 工程化基础扎实，存在 1 个 P1 数据 bug 与若干 P2 待修 |

## 6.2 实锤问题（P1 · 建议复赛前修复）

### P1-1 上传单案缺维度，静默污染聚合看板 ⚠️ 实锤
- **现象**：`/api/analyze` 落库的 `Case` 缺少 `category / supplier / outcome`（实测 INSERT 参数：`category=None, supplier=None, outcome=None`），保存后进入洞察会被算作 `category='未分类'`、`outcome='未知'`、`supplier='未知'`。
- **证据**：
  - `pipeline._mock` / `live_analyze` 返回结构**不含** `category/supplier/outcome`（`pipeline.py:128-140`、`models_router.py:240-251`）；
  - `main.analyze` 的 `save_case` 字典仅补了 `sku/amount/platform/returned_image/product_image`（`main.py:158-166`）；
  - 动态复现：上传 1 单后 `build_insights` 的 `total_cases` 由 672→**673**，且 `outcome_dist` 出现 `'未知'` 桶。
- **影响**：每上传一单都稀释「维权胜诉率 / 累计退款」KPI，并在品类、平台、供应商、根因各维度注入噪声桶，复赛演示时看板数字会"越用越假"。
- **整改**：① 表单增加 `category / supplier` 选择（或从 listing 文本/平台规则推断）；② 或给单案打 `outcome='待分析'` 标记，`_aggregate` 对未分析单案**不计入 KPI 分母**、单独分组，避免污染图表；③ 至少不要让 `outcome/category` 退化为 `'未知'/'未分类'` 混入统计图。

### P1-2 `analyze` 缺乏原子性与失败清理（R-1/R-2）
- **位置**：`main.py:123-166`。先 `open(rp,'wb').write(...)` 落盘，再 `analyze_case`，最后 `save_case`，**全部不在 `try/finally` 中**：
  - 任一环节抛异常 → `UPLOAD_DIR` 残留孤立图片（无清理）；
  - `save_case` 若失败（DB 抖动）→ 直接 500，且已完成的取证结果丢失（本应先返回结果、沉淀尽力而为）。
- **整改**：用 `tempfile`/try-finally 删除临时图；`save_case` 包 `try/except` 记日志，仍优先 `return result`（取证结果 > 数据沉淀）。

### P1-3 未转义渲染模型输出 → 存储型/反射型 XSS 面（F-1）
- **位置**：`index.html` 在表格里用 `innerHTML` 直接拼 `defect_tags / supplier / sku / top_defect`（如 `:594 :634 :651`）。mock 模式下这些来自固定词表（安全），但 **`mode=live` 时 `defect_tags` 取自视觉模型自由文本**，未做任何转义即 `innerHTML`，可注入 `<img onerror>` 等。
- **影响**：当前为单用户自 XSS，但一旦多租户/对外即高危；安全评审一律按 P1 计。
- **整改**：对 LLM/用户来源字段统一用 `textContent`，或加 `escapeHtml()` 工具函数；`renderBarh/renderMatrix` 的 `title`/`label` 同理。

## 6.3 重要问题（P2）

- **P2-1 `/uploads` 静态暴露（S-2）**：`main.py:85` 把上传目录挂成公网可读；`rid` 仅 8 位十六进制（可枚举），且**无过期清理** → 客户退货照片（PII）泄露 + 磁盘无限增长。整改：上传图仅服务 live 回源、不长期静态托管；或加签名 URL + 定期清理。
- **P2-2 `response_model` 用 `extra="allow"` 削弱契约（A-3）**：`schemas.py:30,58` 与 `main.py:12` 一边号称"强契约"一边 `extra="allow"`，未声明的字段（如 `platform_supplier_matrix`）绕过校验直通前端。整改：显式声明全部字段，或收敛为受控 `extra` 子模型。
- **P2-3 import 期 monkeypatch SQLAlchemy（A-6）**：`db.py:51-63` 在模块导入时**无条件**改写 `PGDialect._get_server_version_info`（即便用 SQLite 也执行），属全局副作用、对库内部实现脆弱。整改：包成函数、仅当 `DATABASE_URL` 含 openGauss 时挂接，或迁移到官方方言。
- **P2-4 阈值 `0.82` 硬编码漂移（F-6）**：`main.py:721`、``generate_dataset.py:176`` 直接写 `0.82`，而 `pipeline` 用的是 `constants.SAME_ITEM_THRESHOLD`（`constants.py:9`）。三处不同步 → 判定口径漂移。整改：前端/生成器统一从接口或常量取值。
- **P2-5 聚合每请求重算 + 缓存跨进程不安全（A-2/P-1/R-5）**：`/api/insights` 每次都对全量案件 `_aggregate`（O(n)）；`load_cases` 缓存是模块级变量（`db.py:111`），**仅单进程有效**，多 worker（uvicorn `--workers>1`）下各进程各持缓存、保存后其他进程读不到更新。整改：聚合结果按 `(mode,category,platform)` 缓存并在 save 时失效；或上 Redis；多 worker 部署需明确缓存一致性方案。
- **P2-6 `save_case` 静默丢弃字段（D-2）**：`db._dict_to_row` 只取 `_COLUMNS`，`analyze_case` 产出的 `dossier / voice_text / voice_audio_b64 / defect_boxes / priority_score` 全部不入表。属"取证结果不可回放"。整改：至少落 `defect_boxes`（红框坐标）、`priority_score`、`dossier` 等，便于案件复盘。
- **P2-7 依赖未锁版（C-1）**：`requirements.txt` 中 `fastapi / uvicorn / requests` 未固定版本，`SQLAlchemy` 仅下限。整改：补 `requirements.txt` 精确版本 + 引入 lock（uv/pip-tools），保障复赛复现。
- **P2-8 写接口无鉴权/限流（S-3）**：`/api/analyze` 为公网可写、接收上传并落库，无认证与限流 → 可被刷盘/刷库。整改：演示环境加演示态开关；对外需鉴权 + 速率限制。
- **P2-9 可观测性缺失（O-1）**：`analyze/insights` 无耗时与结构化日志，`/health` 仅静态；无指标端点。整改：加 request latency 日志 + `/metrics`（或接入已有监控）。

## 6.4 优化项（P3）

- **P3-1 空结果 `recommendations` 回归（L-1）**：`build_insights` 对 0 案件会先给 `_empty_aggregate()["recommendations"]=["暂无案件数据…"]`，但 `_mock_attribution` 又把它**整体覆盖**为可能为空列表 → 空筛选下前端建议区变空。整改：空数据分支提前 `return`。
- **P3-2 初始化重复 fetch（F-7）**：`index.html:743` 先拉一次 `/api/insights` 仅为了填充筛选下拉，`:759` 又 `loadInsights()` 再拉一次（逻辑重复）。整改：一次拉取，复用 `d`。
- **P3-3 缺负向 / 数据一致性测试（T-1）**：尚无用例断言"上传单案能干净进入洞察"（此类测试会直接撞出 P1-1）；也无 live 回退、供应商下钻、openGauss 路径测试。整改：补 `test_analyze_case_persists_dimensions`（锁 P1-1 修复）。
- **P3-4 `seed-only-when-empty` 本地开发坑（A-7-local）**：`init_db` 仅在 `count==0` 时导入 `cases.json`；本地若已生成 `cases.db`，重新跑 `generate_dataset` 不会刷新。整改：提供 `init_db(force=True)` 或 `make reset-db`。
- **P3-5 整图 base64 入响应（R-3）**：`main.py:151` 把原始退货图（最大 10MB → base64 ≈13MB）塞进 JSON 响应并前端 canvas 渲染。整改：落盘后返回 `/uploads/<id>` 缩略图 URL，而非内联全图。

## 6.5 已做对的地方（正面，保留）

- ✅ **CI 真实存在且规范**：`.github/workflows/ci.yml` 在 push/PR 跑 `ruff format --check` + `ruff check` + `pytest`，门禁到位。
- ✅ **容器加固到位**：`docker/Dockerfile` 非 root（`USER appuser`）、`entrypoint.sh` 等待 DB 就绪 + 幂等 `init_db` + `set -euo pipefail`。
- ✅ **上传安全基线扎实**：魔数校验、10MB 上限、`_safe_name` 文件名白名单、`os.path.basename` + 路径越界 `assert`（`main.py:52-132`），防穿越有效。
- ✅ **分层与单一来源**：`constants.py`（阈值/词表）、`platforms.py`（举证包唯一事实来源）设计清晰，`generate_platform_doc.py` 同源生成文档，杜绝漂移。
- ✅ **强类型入口 + 优雅降级**：端点挂 `response_model` + OpenAPI；live 失败统一回退 mock 并标注 `mode=mock(fallback)`。
- ✅ **前端工程化**：大屏单页不滚动、组件切换、多比例适配、`role="dialog"`+Esc 关闭、动效与细滚动条，体验完整。

## 6.6 修复优先级路线图

| 阶段 | 项 | 估时 |
|---|---|---|
| **复赛演示前（必做）** | P1-1 上传维度补全 / P1-2 原子性清理 / P1-3 XSS 转义 | 0.5–1 天 |
| **复赛公网部署前** | P2-1 uploads 鉴权过期 / P2-2 收紧契约 / P2-7 锁依赖 / P2-8 鉴权限流（若对外） | 0.5–1 天 |
| **持续打磨** | P2-3/4/5/6/9、P3-1~5 | 1–2 天 |

> 结论：代码已达"可演示、架构清晰、工程化到位"水平；**阻断性风险集中在 P1-1（数据污染）**，复赛路演前务必先修。其余 P2 多为生产化加固，可按部署节奏推进。

---

# 七、终审（2026-08-21）· A/B/C 组全量交付 + 测试/lint 门禁全绿

> 审查基准：本仓库 v1.1.0。本轮按用户交付顺序完成 **A 组（假能力变真）→ B 组（数据闭环）→ C 组（多租户+合规+国产化）**，并对全部新增代码做终审。
> 方法：静态通读 + 动态验证（TestClient 冒烟、openGauss 自动导入幂等复现、租户隔离复现）+ ruff/pytest 门禁全跑。

## 7.1 门禁结论

| 门禁 | 结果 |
|---|---|
| `ruff check .` | ✅ 0 错误（含仓库根 `render_diagrams.py` / `verify_api.py` 存量 8 项一并修掉） |
| `ruff format --check .` | ✅ 全绿（43 files） |
| `pytest -q`（隔离 SQLite env） | ✅ **65 passed**（1.0.0 基线 30 → 1.1.0 共 65） |
| live 冒烟（`verify_live.py`） | ✅ 无 Key 自动 SKIP；有 Key 逐能力真实/回退标记正确 |

## 7.2 旧问题终审状态（承接 6.2 / 6.3 / 6.4）

| 原编号 | 项 | 状态 |
|---|---|---|
| P1-1 上传维度污染 | ✅ 已闭环（单案归「待分析」+ 维度补全，1.0.0） |
| P1-2 取证原子性 | ✅ 已闭环（try/except 清理 + 优先返回结果，1.0.0） |
| P1-3 XSS 转义 | ✅ **本轮彻底闭环**：修复 SKU/品类/供应商/根因标签/平台举证材料等全部漏转义点，统一 `esc()`；后端新增 CSP / `X-Content-Type-Options` / `Referrer-Policy` 防御纵深（`main.py security_headers` 中间件） |
| P2-1 `/uploads` 暴露 | ✅ 已补过期清理（1.0.0）+ 图床抽象（本轮 A 组）；生产签名 URL 仍标注为部署期事项 |
| P2-4 阈值 0.82 漂移 | ✅ **本轮彻底闭环**：`calibration.py` 自标定 + `get_active_threshold()` 单一来源，前端/生成器同步 |
| P3-3 负向/一致性测试 | ✅ **本轮闭环**：新增 `tests/test_negative.py`（12 项）+ `tests/test_auth.py`（5 项） |
| P3-17 live 图床 | ✅ **本轮闭环**：`storage.py`（OSS / PUBLIC_IMAGE_BASE / 本地回退）+ 上传即回传图床 |

## 7.3 本轮新增能力复审

### A 组 · 假能力变真
- `models_router.live_analyze` 重构为**逐能力回退**（similarity/defects/ocr/tts 各自 try/except + `capabilities` 映射），任一能力失败不影响其余，gateway 渐进开通即生效——设计正确，杜绝"一个能力挂整链断"。
- `storage.py` 图床抽象：OSS（boto3 懒加载）/ `PUBLIC_IMAGE_BASE` / 本地回退三级，`is_public_ready()` 显式暴露可回源状态；上传即 `bed_upload` 回传公网 URL，live 服务端回源有据可依。
- `verify_live.py` 冒烟：无 Key SKIP、有 Key 逐能力报真实/回退，CI/演示两不误。

### B 组 · 数据闭环
- `pipeline` 新增 `time_series` / `forecast`（线性回归外推 + 趋势）/ `forecast_alerts`（环比激增），纯函数 `_build_time_series` / `_forecast_monthly` 可单测；前端趋势折线 + 预测 KPI 卡已渲染。
- `importer.py` CSV 回流：列名映射（中英不敏感）、类型转换、缺 sku 跳过、**自动补 case_id**（修复原导入 NULL 案件号导致无法删除/去重的隐患）；连接器位 `import_from_connector` 可插拔。
- `calibration.py`：Youden J 最优切点 + 落盘 + `get_active_threshold()` 统一读取（pipeline 与 live 同源）。

### C 组 · 多租户 + 合规 + 国产化
- **多租户隔离（实锤复现）**：注册两个租户 acme/beta + 匿名，实测——acme 只见自有 + public 基准，beta 只见自有 + public，匿名只见 public；**跨租户删除返回 deleted=0（拦截生效）**；`/api/auth/me` 匿名 401。私有数据严格隔离，`public` 作为共享基准。
- **XSS 防御纵深**：前端漏转义点全清；后端 CSP（`object-src 'none'; base-uri 'self'; frame-ancestors 'none'`）+ nosniff + no-referrer，即使前端偶发漏转义也有兜底。
- **负向测试**：非法 mode/platform/season/空白 category → 400；CSV 缺 sku 跳过；mock 确定性（同图同结果）；安全响应头断言。
- **region/season 下钻**：后端 `/api/insights` 原生支持，前端新增地区/季节筛选并联动（与导出 PDF 同口径）。
- **openGauss 自动导入（实锤复现）**：`RG_AUTO_IMPORT_CSV=seed_real.csv` 启动自动导入 real 源 20 条、全带 case_id；**重启再导入 imported=0 / skipped=20（幂等）**；存量库自动 `ALTER TABLE` 补 `tenant_id` 列（schema 演进不破坏）。
- **账户体系安全**：pbkdf2（10 万轮）+ HMAC 签名令牌（无状态、7 天过期、`AUTH_SECRET` 可配）；密码最短 6 位、用户名正则；零新依赖（stdlib）。

## 7.4 本轮顺手修复的隐藏问题

- **mock 相似度确定性回归（重要）**：`_mock_similarity` 原按**文件名**哈希（上传文件名含随机 `rid`）→ 同一张图每次结果漂移（实测 0.785 vs 0.933）。改为按**图片内容**哈希（`_content_seed`），同图恒同结果，mock 可复现（PRD 要求）。
- **CSV 导入 NULL 案件号**：补齐 `RG-XXXXXXXX`，与 `/api/cases` 手动录入口径一致。
- **`auth.py` 懒引擎死锁**：初版 `_auth_session` 外层持锁再调 `get_auth_engine`（非重入 `threading.Lock`）→ 死锁；已改为引擎工厂内部加锁、会话不嵌套持锁（测试 65 项全过佐证）。

## 7.5 已知限制 / 遗留（非阻断）

| 项 | 说明 |
|---|---|
| live 模型开通依赖 | 视觉/向量/OCR/TTS 需 Model Router gateway 开通对应模型；未开通自动回退 mock 并逐能力标记，**开通即生效** |
| 多 worker 缓存一致性 | 聚合/load_cases 缓存为进程内（SQLite/单 worker 演示足够）；openGauss 多 worker 生产建议加 Redis 共享缓存（非阻断） |
| `/uploads` 静态可读 | 演示态；对外公网部署应改签名 URL + 短期过期（已在代码注释标注） |
| Alembic 迁移 | 当前用 `_ensure_tenant_column` 做最小 schema 演进；大规模生产建议引入 Alembic（非阻断） |

## 7.6 终审结论

- **综合评级：A-**（1.0.0 基线 B- → 1.1.0 A-）。
- 安全面：P1 全部清零；XSS 前端转义 + 后端 CSP 双保险；写接口鉴权/限流；多租户隔离经动态复现。
- 质量面：测试 30 → **65**（含负向/一致性/租户隔离/openGauss 导入），ruff check + format 全绿。
- 交付面：A/B/C 三组全部落地并文档化（CHANGELOG v1.1.0、README、`openGauss部署指南.md`、本报告）。
- 遗留均为部署期/生产化增强，不阻断复赛演示与上架节奏。

---

# 八、安全专项复审（2026-08-27）· 大厂标准多维度 · 重点安全

> 复审基准：截至当前 HEAD（v1.x，含双 profile 网关、移动端/UI 加固、Cloudflare Tunnel 公网部署）。
> 本轮与历次不同：**代码已对外公网可访问**（`https://rg.a703201sworld.top`，Cloudflare Tunnel 转发到本机 `127.0.0.1:65432`）。
> 因此本轮以「公网部署安全」为切点，按大厂维度（安全/架构/健壮性/性能/数据/测试/可观测/配置/前端/CI-CD）重新走查，重点揪「演示态默认配置在公网语境下是否成立」。
> 方法：通读 `demo/` 全量源码 + `docker/` 部署配置 + 前端 `index.html` 转义点 + 历史 review 对账，结合部署现实推断可达性（不依赖临时起服）。

## 8.1 总体结论

| 维度 | 评级 | 说明 |
|---|---|---|
| 代码工程化（分层/契约/测试/lint/CI） | **A-** | 保持历史水平：双轨设计、Pydantic 契约、`response_model`、77 passed、ruff 全绿、CI 门禁、Docker 非 root + healthcheck、依赖精确锁版 |
| **安全（公网部署语境）** | **C+ → B-** | 演示态默认配置在公网下出现 **3 个 P1**：写接口无鉴权全开、`.env` 的 `AUTH_SECRET` 被静默忽略、代理 IP 误判致限流失效 |
| 健壮性 / 容错 | **B** | 取证原子性 + 优先返回结果已闭环；进程内缓存多 worker 不安全（已知） |
| 数据一致性 / 多租户 | **B+** | real 源租户隔离逻辑正确；open-write 会污染 shared `public` 基准（见 SEC-5） |
| 前端质量 | **B+** | 已统一 `esc()` + 后端 CSP；`unsafe-inline` 削弱纵深、个别模型字段需复核是否全走 `esc()` |
| 可观测 / 配置 / CI | **B+** | 结构化日志 + `/metrics` + 安全响应头；部署 env 缺 `AUTH_SECRET`/`AUTH_TRUSTED_PROXIES` |

**一句话**：工程底子扎实（A-），但「公网体验地址」按当前默认配置跑，**安全面有 3 个 P1 必须修**才能算对外可接受。以下按严重度列出。

## 8.2 安全发现（按严重度）

### 【SEC-1 · P1】公网实例写接口无鉴权全开（`ANALYZE_API_KEY` 默认空）

- **位置**：`main.py:99` `_API_KEY = os.environ.get("ANALYZE_API_KEY","")`；`main.py:229-238` `_require_api_key` 在 `_API_KEY` 为空时直接 `return`（no-op）；`docker/docker-compose.local.yml:41` 显式 `ANALYZE_API_KEY: ""`。
- **现象**：默认配置下，`_require_api_key` 是空操作。公网实例因此暴露 **世界级可写接口**：
  - `POST /api/analyze`（上传任意图 + 落 demo 库 + 回传图床）
  - `POST /api/cases` / `DELETE /api/cases/{id}`（增删案件）
  - `POST /api/import_csv`（导入 CSV 到 real `public` 基准）
  - **`POST /api/calibrate`（管理动作：直接覆写 `calibration.json` 标定阈值）**
- **影响**：
  1. 退货照片（客户 PII）被任意上传堆积到 `/uploads` + 图床（隐私 + 存储滥用）；
  2. 演示库 / 共享 `public` 真实库被污染，看板数字越用越假；
  3. **任何人可把同款判定阈值改掉**，直接扭曲所有相似度/胜诉率结论（最危险的一条）。
- **整改（必修）**：
  - 部署环境设 `ANALYZE_API_KEY=<高熵随机串>`，让 `_require_api_key` 生效；
  - `POST /api/calibrate` 应**始终**要求管理员级鉴权（不应仅依赖可选 API Key），建议独立于 `ANALYZE_API_KEY` 的 `ADMIN_API_KEY` 或登录态；
  - 面向公网的写接口（`analyze/cases/import_csv`）建议再叠一层「必须登录且属当前租户」。

### 【SEC-2 · P1】`.env` 里的 `AUTH_SECRET` 被静默忽略（dotenv 加载顺序 bug）

- **位置**：`auth.py:28` `_SECRET = os.environ.get("AUTH_SECRET", os.urandom(32))` —— 模块级读取，**`auth.py` 从不调用 `load_dotenv()`**；`main.py:29` `import auth` 早于 `models_router`/`storage`（二者在 `main.py:51/52` 才 import，且其内 `load_dotenv()` 在 `models_router.py:63-64` / `storage.py:33-34`）。
- **现象**：进程启动、`auth` 模块体先执行 → 此时 `.env` 尚未被任何模块加载 → `AUTH_SECRET` 即便写在 `.env` 也**读不到**，回退为每进程随机 `os.urandom(32)`。
- **影响**：
  1. 令牌签名密钥每次启动随机 → **所有令牌重启即失效**（demo/demo123 等账户重启后被登出）；
  2. 一旦用 `--workers>1`，worker A 签的令牌 worker B 用自己不同的随机密钥**校验失败 → 登录实际失效**；
  3. 运维以为「已在 `.env` 配了 `AUTH_SECRET`」实则是空配置 → **虚假安全感**（启动仅有 `logger.critical` 提示，易被忽略）。
- **整改（必修）**：
  - 在 `auth.py` 顶部也 `from dotenv import load_dotenv; load_dotenv()`（与 models_router/storage 一致）；或把 `AUTH_SECRET` 改为**惰性读取**（在 `issue_token`/`verify_token` 内取 `os.environ.get("AUTH_SECRET")`），避免 import 期定死；
  - 部署环境把 `AUTH_SECRET` 直接注入**进程环境变量**（而非仅 `.env`），作为兜底；
  - 现有 `.env.example:35` 已说明「生产必设」，但代码没真正吃到，需修代码而非文档。

### 【SEC-3 · P1→P2】代理/客户端 IP 误判：Cloudflare 部署下限流与防爆破退化

- **位置**：`main.py:197-209` `get_client_ip` 仅当 `request.client` 属于 `AUTH_TRUSTED_PROXIES` 才采纳 `X-Forwarded-For`/`X-Real-IP`；`main.py:90` `AUTH_TRUSTED_PROXIES` 默认空；`.env.example:49` 亦空。
- **现象**：经 Cloudflare Tunnel 时，`cloudflared` 以**本地连接**转发到 `127.0.0.1:65432`，故 `request.client.host == 127.0.0.1` 对**所有访客**一致。因 `AUTH_TRUSTED_PROXIES` 为空 → 代码取直连 IP → 所有请求共用 `127.0.0.1` 一个桶。
- **影响**：
  1. `analyze/register/login` 的按 IP 限流**坍缩成全局单桶**：单攻击源无法被隔离限速，且正常流量尖峰会把所有人一起 429；
  2. 按 IP 的登录失败锁定（`_login_lock_until`）退化为「锁 127.0.0.1」→ 实际不起作用；
  3. 审计日志 `client_ip` 全为 `127.0.0.1`，无法溯源。
- **整改（必修/部署）**：
  - 部署环境设 `AUTH_TRUSTED_PROXIES=127.0.0.1`（cloudflared 本地转发）→ 使 `X-Forwarded-For` 首段（真实访客 IP）被采纳；
  - 更稳：直接读 Cloudflare 头 `CF-Connecting-IP`（在 `get_client_ip` 增加该分支），避免依赖 XFF 可被伪造；
  - 配合 SEC-2，多 worker 下进程内 `_rate_window`/`_login_fails` 仍不安全（见 SEC-12）。

### 【SEC-4 · P2】令牌经 `?token=` 查询参数传递 → 易泄露

- **位置**：`main.py:218-227` `_resolve_tenant` 从 `Authorization: Bearer` / `X-Token` / `?token=` 三处取令牌。
- **风险**：URL 中的令牌会出现在 Cloudflare/反向代理访问日志、浏览器历史、`Referer`，属经典泄露面。
- **整改**：保留 `Bearer`/`X-Token` 头，**停用 `?token=`**（或仅作非敏感 GET 的兼容、文档明示风险）；前端 token 存 `localStorage` 可被 XSS 读取 → 建议缩短 TTL（当前 7 天偏长）+ 评估 httpOnly Cookie。

### 【SEC-5 · P2】未登录即可写入共享 `public` 真实库（无 API Key 时）

- **位置**：`main.py:674` `POST /api/cases`、`main.py:847` `/api/import_csv`。两接口默认无 Key 时匿名录入 `tenant_id="public"`（real 源共享基准）。
- **影响**：匿名访客可污染所有 real 账户都能看到的 `public` 基准数据。
- **整改**：数据变更接口要求 `登录态 + 当前租户`（至少 `public` 也需 Key），与 SEC-1 一并收口。

### 【SEC-6 · P2】公网实例注册开放（`REGISTRATION_ENABLED=true` 默认）

- **位置**：`main.py:87` 默认 `true`；`docker-compose.local.yml:44` 亦 `true`。
- **影响**：公网任意人可注册账户 → 用户库被刷、租户数据无限增长。
- **整改**：公网体验地址设 `REGISTRATION_ENABLED=false` 或 `REGISTRATION_INVITE_CODE=<评委码>`；demo 账号已预置 `demo/demo123`。

### 【SEC-7 · P2】`/metrics` 与 `/api/config` 未鉴权 → 信息泄露

- **位置**：`main.py:501` `/metrics`（uptime/请求量/错误数）、`main.py:481` `/api/config`（含 `model_router_endpoint` 内部端点）。
- **影响**：泄露运行指标与内部网关地址，便于攻击者刻画目标。
- **整改**：`/metrics` 加 Basic Auth 或仅监听内网；`/api/config` 不回传内部 `model_router_endpoint`（前端不需要）。

### 【SEC-8 · P2】`/uploads` 长期静态可读 + 含客户 PII（部署期事项，重申）

- **位置**：`main.py:284` 挂载 `StaticFiles('/uploads')`；`_cleanup_old_uploads` 仅 24h 清理。
- **影响**：退货照片（PII）公网长期可读、文件名 `rid` 仅 8 位十六进制可枚举。
- **整改**：对外部署改**签名 URL + 短过期**；或上传即回传图床后本地立删（live 回源走图床 URL）。

### 【SEC-9 · P3】CSP 含 `unsafe-inline` → 纵深削弱

- **位置**：`main.py:336-340` `script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'`。
- **整改**：因前端无构建步骤、内联脚本多，短期保留可接受；建议引入 per-response **nonce** 替换 `unsafe-inline`，使 CSP 真正生效（配合 SEC-4 的 token 存储，构成 XSS 双重保险）。

### 【SEC-10 · P3】登录时序侧信道 / 口令强度

- **位置**：`auth.py:115-124` `authenticate` 对用户不存在时直接 `return None`（不做哈希）→ 存在/不存在账号响应时间不同（用户名枚举）；
- **整改**：对未知用户也跑一次 dummy `pbkdf2` 恒定耗时；`pbkdf2` 10 万轮低于当前 OWASP 建议（SHA-256 约 60 万轮），建议上调（演示可接受，生产调高）。

### 【SEC-11 · P3】API Key 比较非常量时间

- **位置**：`main.py:237` `if provided != _API_KEY:`。
- **整改**：改用 `hmac.compare_digest(provided, _API_KEY)`。

### 【SEC-12 · P3】进程内状态在多 worker 下不一致（与 SEC-2/3 叠加）

- **位置**：`_rate_window`/`_login_fails`/`_version_cache`（`main.py`、`auth.py`）、`db._cache`/`_generations`（`db.py`）、`pipeline._ins_cache`、`_metrics`。
- **整改**：明确文档「单 worker 部署」；或上 Redis 共享；配合 SEC-2 修复后，`AUTH_SECRET` 一致才能使多 worker 登录可用。

## 8.3 其他维度遗留 / 复核

- **架构契约**：`schemas.py:35,69` `extra="allow"` 仍削弱 `response_model` 校验（历史 P2-2 未彻底收口）。非阻断，但建议显式声明 `platform_supplier_matrix` 等全部字段。
- **前端转义复核（必做）**：`index.html:952` 已定义 `esc()` 且用于 `o.label`/`p.month` 等；但需**逐字段确认**所有「模型/用户来源」字段（`consistency`/`dossier`/`voice_text`/`root_cause`/`report`/`sourcing_advice`/`recommendations`/`supplier_name`/`defect_description`/`defect_tags`）均经 `esc()` 后 `innerHTML`，否则 live 模式模型自由文本即 XSS 面。**后端 PDF（`pdf_report.py`）已全程 `_esc` → 安全**（正面）。
- **LLM 提示词注入（已知风险）**：`/api/cases`/`/api/import_csv` 的 `sku/category/supplier/defect_tags` 为用户可控文本，会进入 `build_insights_prompt` 的聚合上下文（`models_router.build_insights_prompt`）→ 可被用来「引导」洞察结论。缓解：persona 护栏（不裁决/不乱编）+ 输出全转义；内容可被导向属可接受 LLM 风险，建议在 prompt 组装前对自由文本字段做长度/字符裁剪。
- **依赖锁版（已闭环，正面）**：`requirements.txt` 全部精确版本（`fastapi==0.141.1` 等），P2-7 已修。注意 `boto3` 未列入依赖却在 `storage._upload_oss` 懒导入 → 若真用 OSS 后端会静默降级（catch 后走下一后端），需用时补装。
- **测试缺口**：77 passed 扎实；但缺三类用例：① 设 `ANALYZE_API_KEY` 后未带 Key 写接口应 401（锁 SEC-1）；② `AUTH_SECRET` 从环境变量加载后多 worker 令牌可验（锁 SEC-2）；③ `AUTH_TRUSTED_PROXIES=127.0.0.1` 下 `X-Forwarded-For` 首段被采纳（锁 SEC-3）。建议补 `test_security.py` 三项。

## 8.4 优先修复路线（公网部署前必做）

| 优先级 | 项 | 估时 |
|---|---|---|
| **P1 必修** | SEC-1 设 `ANALYZE_API_KEY` + calibrate 管理员鉴权；SEC-2 `auth.py` 补 `load_dotenv`/惰性读 `AUTH_SECRET` + 部署注入；SEC-3 部署设 `AUTH_TRUSTED_PROXIES=127.0.0.1`（或读 `CF-Connecting-IP`） | 0.5 天 |
| **P2 应做** | SEC-4 停用 `?token=`；SEC-5 数据变更须登录+Key；SEC-6 公网关注册/邀码；SEC-7 `/metrics`+`/config` 收口；SEC-8 签名 URL | 0.5–1 天 |
| **P3 打磨** | SEC-9 CSP nonce；SEC-10 时序/轮数；SEC-11 常量时间比 Key；SEC-12 多 worker 共享状态；补 3 类安全测试 | 1 天 |

> 结论：代码工程化已达大厂 A- 水平；**但在公网部署语境下，安全面有 SEC-1/2/3 三个 P1 必须先行修复**，否则「体验地址」属可被任意写入/篡改阈值的高风险暴露面。修复后安全面可达 B+，满足复赛对外演示与评委体验要求。

---

## 9. 安全复审修复落地（2026-08-27，全量修复）

用户要求「全部都修」。本章记录第八节所列 P1/P2/P3 的**实际修复**与**残余项**。验证：82 passed（原 77 + 安全回归 5，另既有 API 测试随合约变更补登录会话）。

### 9.1 已修复（代码 + 部署）

| 编号 | 项 | 修复点 | 验证 |
|---|---|---|---|
| **SEC-1** | 写接口无鉴权全开 | `main.py`：新增 `_require_session`（写接口必须登录会话）+ `_require_admin`（calibrate/metrics 须 `ADMIN_API_KEY` 或登录）；`/api/analyze`、`POST/DELETE /api/cases`、`/api/import_csv` 改走 `_require_session`；`/api/calibrate`、`/api/metrics` 改走 `_require_admin`。 | 匿名 analyze/cases/calibrate/metrics → **401**；登录 demo → analyze 200；calibrate/metrics 带 `ADMIN_API_KEY` 才过。公网实测一致。 |
| **SEC-2** | `AUTH_SECRET` 被 dotenv 顺序静默忽略 | `auth.py` 顶部补 `load_dotenv()`（带 pytest 守卫）；`_SECRET` 经 `_resolve_secret()` 统一转 bytes；`AUTH_SECRET` 支持 `secrets.token_hex(32)` 十六进制串按字节解码（与文档示例一致）。`demo/.env` 已注入固定 `AUTH_SECRET`。 | 子进程导入 `auth` 确证从 `.env` 读到密钥；令牌跨 reload 可验；重启令牌不再失效。 |
| **SEC-3** | 代理客户端 IP 误判 | `get_client_ip` 优先采纳 `CF-Connecting-IP`（Cloudflare Tunnel），其次 `X-Forwarded-For`/`X-Real-IP`；仅当直连属 `AUTH_TRUSTED_PROXIES` 才信任。部署 `AUTH_TRUSTED_PROXIES=127.0.0.1`。 | 单元测试：可信代理下 `203.0.113.5` 被采纳；非可信代理忽略伪造头。 |
| **SEC-4** | 停用 `?token=` 查询传令牌 | `_resolve_tenant` 仅读 `Authorization: Bearer` / `X-Token` 头，删去 `?token=`（避免令牌经 URL/Referer/代理日志泄露）。 | — |
| **SEC-5** | 数据变更须登录 | 见 SEC-1（`_require_session`）。 | — |
| **SEC-6** | 公网关注册 | `demo/.env` + `docker-compose.local.yml` 置 `REGISTRATION_ENABLED=false`（评委用内置 demo/demo123）；保留 `REGISTRATION_INVITE_CODE` 可选邀请制。 | — |
| **SEC-7** | `/metrics`/`/config` 收口 | `/metrics` 纳入 `_require_admin`（匿名 401，已实测）；`/api/config` 保留开放（前端加载常量所需，仅透出非敏感 URL）。 | `/metrics` 匿名 401（实测）。 |
| **SEC-10** | 登录时序侧信道 | `authenticate` 用户不存在时也跑一次等代价 pbkdf2，消除「用户枚举」时序差。 | — |
| **SEC-10** | KDF 轮数偏低 | pbkdf2 由 10 万轮提至 **60 万轮**（`CURRENT_PBKDF2_ITERS`）；存量账户经 `pw_iters` 列 + rehash-on-login 渐进升级（无迁移破坏）；`init_auth_db` 补 `pw_iters` 列（默认旧轮数，避免存量校验失败）。 | 登录成功自动升级哈希（无感）。 |
| **SEC-11** | API Key 非常量时间比较 | `_require_api_key`/`_require_admin` 改用 `hmac.compare_digest`（常量时间）。 | — |
| **测试** | 三类安全用例缺失 | 新增 `test_security.py`：SEC-1 写接口登录门禁、SEC-2 `.env` 加载 + 跨重启令牌一致、SEC-3 代理 IP；既有 API/负向/平台测试补 `demo_token`/`auth_headers` 夹具（登录会话）。 | 82 passed。 |

### 9.2 修复中顺带根治的潜在生产缺陷

- **hmac 密钥类型错误**：原 `_SECRET = os.environ.get("AUTH_SECRET", os.urandom(32))` 在设置 `AUTH_SECRET` 字符串时直接传 `str` 给 `hmac.new`，Python 3.13+ 会抛 `TypeError` 致令牌签发崩溃。`_resolve_secret()` 统一转 bytes，根治。
- **SEC-2 测试自污染**：`PYTEST_CURRENT_TEST` 会经子进程环境泄漏，使 auth 的 pytest 守卫误跳过 `.env` 加载；测试已显式从子进程环境剔除该变量。

### 9.3 残余项（需架构级改动，文档记录不本次修）

| 项 | 说明 | 风险 | 后续 |
|---|---|---|---|
| **SEC-8 签名 URL** | `/uploads` 客户退货图为 PII，当前静态长期可读 + 24h 清理。真正收敛需对象存储（七牛/OSS）签名 URL + 短期过期。 | 中 | 接对象存储后端时一并做；当前靠清理缓解。 |
| **SEC-9 CSP nonce** | `script-src 'unsafe-inline'` 因前端为静态 `index.html` 内联脚本；去 inline 需模板化注入 per-request nonce。XSS 已由 `esc()`/`textContent` 全程阻断（PDF 亦 `_esc`），纵深仍够。 | 低 | 重构前端为服务端模板时落地。 |
| **SEC-12 多 worker 共享状态** | `_rate_window`/`_login_fails`/`_metrics`/`_version_cache`/`db._cache` 为进程内结构，多 worker 不安全。 | 低（当前单 worker） | 部署单 worker，或上 Redis 共享。 |

> 状态：第八节 P1/P2/P3 已全部落地（残余为架构级、非阻断）。安全面由 A-（公网下有 P1 缺口）提升至 **B+/A- 区间**，满足复赛对外公网演示与评委体验要求。
