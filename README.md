# ReturnGuard（退件法医）· 跨境退货举证官

> 参赛赛道：**AI 市场洞察 · AI 智能选品引擎**（退货纠纷数据驱动的选品避坑与品控洞察）
> 赛事：AI+跨境黑客松巅峰赛 · 复赛
> 核心 AI 能力全部经 **阿里云百炼 Model Router** 调用

## 一分钟速览（评委 / 体验入口）

- **公网体验地址**：https://rg.a703201sworld.top （Cloudflare Tunnel 固定域名）
- **测试账号**：`demo` / `demo123`
- **代码仓库**：GitHub `a703201/ReturnGuard`（Gitea 镜像同步）；GitCode 镜像见 `docs/复赛交付物总览.md`
- **当前版本**：v1.1.1（安全复审 SEC-1~12 全清零；live 多模态取证 + 群体洞察看板）
- **Live 合规**：默认 `tokenplan` 网关（文本洞察真实）；切赛事指定 Model Router 见 `docs/LIVE_COMPLIANCE.md`
- **定位**：退货纠纷「只取证不裁决」——客观取证 + 群体退货数据 → 选品避坑 / 品控洞察

## 系统架构一览

![系统架构](assets/arch.png)

- **前端层**：单页应用（上传/卷宗/洞察看板/数据录入），demo-real 双源切换
- **后端编排层**：FastAPI DAG（并行取证 + 洞察聚合 + 多租户）
- **模型能力层**：阿里云百炼 Model Router（7 能力，live/mock 韧性切换）
- **洞察层（产品核心）**：聚类归因 / 预测预警 / 选品避坑 / 供应商品控
- **数据层**：demo 库（演示种子）+ real 库（真实·隔离），双源物理隔离

## 项目里程碑时间线（P0-3）

| 阶段 | 时间 | 关键产出 |
|---|---|---|
| 立项 & 数据集 | 2026-07 | 确定「退货法医 + 退货反推选品避坑」空白定位；固定种子生成 ~686 条多维合成退货案件（胜诉率约 30%） |
| 单案取证 live 化 | 2026-08-19 | 阿里云百炼 Token Plan 网关真接入图向量同款比对 / VL 瑕疵识别（真实红框）/ OCR / rerank，逐能力回退 mock |
| 群体洞察看板 | 2026-08 | 聚类归因 / 预测预警 / 选品避坑清单 / 供应商品控，洞察层成型（产品核心） |
| 进入复赛 | 2026-08-25 | 确认 AI+跨境黑客松巅峰赛复赛资格（场景三 · AI 市场洞察） |
| 公网可体验 | 2026-08-27 | Cloudflare Tunnel 固定域名 https://rg.a703201sworld.top（测试账号 demo/demo123） |
| 复赛交付 | 2026-09-01 ~ 09-13 | 可运行 Demo + 演示视频 + 技术说明 + GitCode 镜像仓库 + 测试账号 + 阶段成果 |
| 决赛路演 | 2026-09-25 | 数贸会现场路演（完成度 / 业务价值 / 技术创新 / 用户体验 / 商业落地） |

> 时间线同步置顶架构图，便于评委一眼看清「从创意到复赛」的推进节奏。

## 项目简介
ReturnGuard 用多模态 AI 对跨境退货纠纷做**客观取证**（同款一致性比对、瑕疵识别、listing 承诺核验、一键证据卷宗 + 母语语音），并把沉淀的退货数据聚合成**「选品 / 品控洞察」**，反哺选品决策。把售后成本中心变成市场洞察数据源——用已成交的真实退货负面信号驱动选品，比公开评论更可信。

## 核心能力 → 模型映射（阿里云百炼 Model Router）
| 能力 | 模型 |
|---|---|
| 多模态图像向量（同款一致性） | `qwen/tongyi-embedding-vision-plus` |
| 视觉理解（瑕疵识别 / 一致性） | `qwen/qwen3-vl-plus` |
| OCR（提取 listing 承诺） | `qwen/qwen-vl-ocr` |
| 文本生成 / 多语（卷宗 / 陈述） | `qwen/qwen3-max` |
| 排序（案件优先级） | `qwen/qwen3-rerank` |
| 语音合成（母语陈述） | `qwen/qwen3-tts-instruct-flash` |
| 推理 / 聚类（洞察层） | `qwen/deepseek-r1` |

## 取证工作流（双闭环）
```mermaid
flowchart LR
  A[①上传与预处理] --> B[②并行取证 图向量+VL+OCR]
  B --> C[③一致性核验]
  C --> D[④卷宗+母语语音]
  D --> E[⑤优先级排序输出]
  E --> F[(案件结构化沉淀)]
  F --> G[⑥群体洞察层 聚类归因+选品建议]
  G -.反哺.-> A
```

## 系统架构
```mermaid
flowchart TB
  FE[前端层 上传/卷宗/洞察看板] --> BE[后端编排层 FastAPI 工作流]
  BE --> IN[洞察层 聚类归因/选品建议]
  BE --> M[模型能力层 Model Router 图向量/VL/OCR/LLM/Rerank/TTS/推理]
  BE <--> D[数据层 对象存储+案例库+阈值样本]
```

## 复赛冲刺能力（v1.1.1）

> 安全复审全量闭环（v1.1.1）：公网部署语境下安全发现项 **SEC-1 ~ SEC-12 全部清零**——写接口鉴权、签名短链收敛 PII、CSP nonce 硬化、多 worker 共享状态外置、KDF 提至 60 万轮、API Key 常量时间比较。测试 65 → 85，安全面达 A 区间。
- **A 组 · 假能力变真**：live 模式真实接入图向量同款比对 / VL 瑕疵识别（真实红框）/ OCR / rerank，统一**图床抽象**（OSS / `PUBLIC_IMAGE_BASE` / 本地回退）供模型服务端回源；未开通的模型**逐能力自动回退** mock 并标记，gateway 渐进开通即生效。
- **B 组 · 数据闭环**：时间序列 + 次月预测预警；CSV 批量导入真实退货数据（`POST /api/import_csv`）+ 平台连接器位；相似度阈值**自标定**（Youden J 最优切点）；选品避坑**可执行清单**。
- **C 组 · 多租户 + 合规 + 国产化**：注册/登录/令牌（一个用户=一个租户），real 源案件按租户隔离（私有严格隔离 + `public` 公共基准）；XSS 全量转义 + CSP 防御纵深；负向/一致性测试补齐；region/season 维度下钻；**openGauss 部署 + 启动自动导入**（`RG_AUTO_IMPORT_CSV`，幂等）。

## 快速开始
```bash
cd returnguard/demo
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://localhost:8000
```
- 开发期默认 SQLite（demo 种子 + real 空库），零配置起跑。
- 部署 openGauss：设 `REAL_DATABASE_URL` 指向 openGauss + `RG_AUTO_IMPORT_CSV=<csv>` 启动自动导入，详见 [`openGauss部署指南.md`](openGauss部署指南.md)。
- 可选环境变量：`ANALYZE_API_KEY`（写接口鉴权）、`AUTH_SECRET`（令牌签名，生产必设）、`FORCE_RESEED=1`（重置 demo 种子）。
- 安全相关环境变量（公网部署必设）：
  - `AUTH_SECRET`：令牌 HMAC 签名密钥（`secrets.token_hex(32)` 生成，生产必设，否则每次重启令牌失效）。
  - `AUTH_TRUSTED_PROXIES`：可信任的反代网段（Cloudflare Tunnel 部署设 `127.0.0.1`，使限流/防爆破按真实客户端 IP 生效）。
  - `ADMIN_API_KEY`：`/api/calibrate`、`/metrics` 管理端点密钥（不设置则仅登录会话可访问）。
  - `REGISTRATION_ENABLED`：公网演示设 `false`（用内置 demo/demo123）；可选 `REGISTRATION_INVITE_CODE` 邀请制。
  - `LOGIN_MAX_FAILS` / `LOGIN_LOCK_MIN`：登录防爆破阈值与锁定时长（分钟）。
  - `UPLOAD_URL_TTL`：上传图签名短链有效期（秒，默认 3600）。
- 上传图不再经 `/uploads` 公开挂载，改为 HMAC 签名短链 `/api/file/{sig}`（PII 收敛，详见 `docs/API.md` §3.6 与 `CHANGELOG.md` v1.1.1 / SEC-8）。

## 验证脚本
`verify_api.py`：纯标准库、零依赖，验证两项关键能力是否真能跑通：
- **图向量比对**（核心）：`tongyi-embedding-vision-plus` 嵌入两张图 → 余弦相似度。
- **TTS → ASR 闭环**：用 API 自身 TTS 合成语音 → `qwen3-asr-flash` 转写回来，验证语音端点。

运行：
```bash
export MODEL_ROUTER_API_KEY=sk-xxx   # Windows: set MODEL_ROUTER_API_KEY=sk-xxx
python verify_api.py
```

## 提交状态
- **初赛**：创意方案已通过官方在线表单提交（完整版见 `ReturnGuard_方案.md`，表单精简版见 `ReturnGuard_表单提交文案.md`）。
- **复赛规划**：可运行 Web Demo（上传退件图 → 相似度 / 瑕疵 / 卷宗 / 语音 + 洞察看板）+ GitCode 仓库 + 3 分钟演示视频 + 容器化体验地址（详见方案 4.5 节）。

## 目录
- `verify_api.py` — 关键 API 验证脚本
- `README.md` — 本文件
- `CHANGELOG.md` — 版本变更记录（v1.0.0 → v1.1.1）
- `openGauss部署指南.md` — openGauss 真实部署 + 真实数据自动导入
- `demo/` — FastAPI 应用：`main.py`（入口）、`pipeline.py`（取证/洞察）、`models_router.py`（真实模型 + 逐能力回退）、`auth.py`（账户/多租户）、`calibration.py`（阈值自标定）、`importer.py`（CSV 回流）、`storage.py`（图床）、`seed_real.csv`（自动导入样例）
- （完整方案 / 表单文案在项目根目录 `ReturnGuard_方案.md`、`ReturnGuard_表单提交文案.md`）
