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
