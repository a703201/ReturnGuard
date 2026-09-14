# ReturnGuard 复赛 Demo（最小可运行版）

单笔退货**取证** → 多案聚合**洞察**的双闭环最小实现。前端单页（zh/en/fr 三语）+ FastAPI 后端，`mock` 模式零依赖即可演示，`live` 模式接真实阿里云百炼 Model Router。

## 目录
```
demo/
  main.py            # FastAPI 装配层：app 创建 / 中间件注册 / 路由聚合 / lifespan
                     #   + VersionedStaticFiles（静态资源 URL 版本化 + no-store）
  common.py          # 配置 / 依赖 / 限流 / 中间件 / 聚合辅助
  routers/           # 按域拆分（P1-9，替代原 1180 行「上帝文件」）
    frontend.py      #   / 首页 · /health · /api/config · /metrics · /api/platforms
                     #   /api/file/{sig} 签名短链 · /api/img/{key} 自托管取图
    forensic.py      #   /api/analyze 单案取证 · /api/cases 增删查
    insights.py      #   /api/insights 群体洞察 · /api/export_pdf 报告导出
    auth.py          #   /api/auth/{register,login,me,logout}
    calibration.py   #   /api/calibrate 阈值自标定（GET 读 / POST 写）
    import_.py       #   /api/import_csv · /api/import_file 真实数据回流
  pipeline.py        # 取证 + 洞察流水线（mock / live 双模式；含 _roi_backtest）
  models_router.py   # Model Router 实时调用（三 profile；逐能力真实/回退）
  auth.py            # 账户/多租户（pbkdf2 60 万轮 + HMAC 签名令牌）
  quota.py           # SEC-13 live 三层配额闸（全局日 / 账号日 / IP 小时）
  shared_state.py    # 限流/登录锁外置 SQLite（多 worker 安全，SEC-12）
  storage.py         # 可插拔图床（local/self/public_base/qiniu）+ 签名短链（SEC-8）
  platforms.py       # 九平台举证规则引擎（交付物 A 数据源）
  imghash.py         # 图片内容哈希单一口径（mock 与 live 回退共用）
  prompts.py         # 提示词版本 PROMPT_VERSION + 变体注册表（A/B 用）
  ab_experiment.py   # prompt 变体 A/B 台架（可复现对照）
  compare_models.py  # 模型对比实验（非线上链路）
  requirements.txt
  cases.json         # 案件种子库（1206 条演示数据）
  uploads/           # 上传图片落盘（经签名短链 /api/file/{sig} 访问，不再公开挂载）
  static/            # 单页前端（无构建 ESM）
    index.html       #   页面骨架 + i18n 静态接线（data-i18n）
    app.js           #   入口 / 事件编排
    render.js        #   看板渲染（动态文案走 t()）
    store.js         #   全局 state
    api.js           #   fetch 封装（自动带令牌）
    i18n.js          #   zh / en / fr 字典 + t() / setLang() / applyI18n()
    dist/            #   可选压缩产物（SERVE_MINIFIED=1 启用）
  tests/             # 150 passed
```

## 快速开始（mock 模式，无需 Key）
```bash
cd demo
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
# 浏览器打开 http://127.0.0.1:8000
```
> 容器部署见仓库根 README「快速开始 · 方式二」（映射到 `127.0.0.1:65432`）。
- 切到「单案取证」Tab，上传「退回商品图」+「本店主图」→ 点「开始举证」：输出相似度、瑕疵标签、一致性、举证报告、母语语音、优先级，并展示**多模型协同编排链路**（逐能力真实 / 回退）。
- 切到「市场洞察」Tab，或点「刷新看板」：聚合历史案件，展示品类热力、根因归因、供应商红黑榜、平台 × 供应商交叉、预测预警、ROI 回测、选品建议。
- mock 相似度由**图片内容哈希**决定（`imghash.content_seed`），**同一对图结果可复现**，便于演示与录屏。
- 顶栏可切换界面语言（中文 / English / Français）。

## live 模式（接真实 Model Router）
只需一个环境变量即可开跑：
```bash
export MODEL_ROUTER_API_KEY=sk-xxx
```
> **图片无需公网可达**：视觉输入默认由 `models_router._img_source` 转成 **base64 data URI 内联**发送，本机直跑即可。
> `PUBLIC_IMAGE_BASE`（或 `RG_SELF_IMAGE_BASE` / `IMAGE_BED`）为**可选增强**——仅当希望走「公网 URL 回源」时才配置对象存储或自托管隧道。

选定网关 profile（三选一，改 `MODEL_ROUTER_PROFILE` 即可，`base_url` + key + 模型标识三者联动切换）：

| profile | 基地址 | 用途 |
|---|---|---|
| `official` | `https://model-router.edu-aliyun.com/v1` | **赛事指定 Model Router**，提交口径 |
| `tokenplan` | `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` | Token Plan 自测网关 |
| `dashscope` | 阿里云百炼国内站兼容端点 | 自购按量，视觉/向量/OCR 齐全、数据不出境 |

前端模式选 `live` 即可走真实链路。以 **official（赛事指定）** 为准的模型清单：
`qwen/qwen3-vl-plus`（同款判定 + 瑕疵 + 红框）· `qwen/qwen-vl-ocr`（Listing OCR）· `qwen/qwen3.7-max`（卷宗 / 陈述 / 洞察归因）· `qwen/qwen3-rerank`（优先级）· `qwen/qwen3-tts-instruct-flash`（母语语音）· `qwen/tongyi-embedding-vision-plus`（图像向量，备选）。

> ⚠️ 命名差异：tokenplan 下文本为 `qwen3.7-max`、TTS 为 `qwen-audio-3.0-tts-plus`（均无 `qwen/` 前缀）；official 下**必须带 `qwen/` 前缀**。且官方模型名单中 TTS 仅 `qwen/qwen3-tts-instruct-flash` 一个，`qwen-audio-3.0-tts-plus` 不在名单内。
> （live 调用逐能力 try/except 回退；全部失败才整体回退 mock，保证演示不中断。）
> 公网演示另有 SEC-13 三层配额闸（`LIVE_QUOTA_*`），超限返回 `429` 且不静默降级。

## 测试与校验
```bash
pytest tests -p no:cacheprovider -q          # 150 passed
python ../scripts/check_i18n.py              # 三语键完整性（零缺失 / 三语一致 / 无重复键）
```

## 复赛交付映射
- **可运行 Demo**：本服务即最小 Demo，已容器化部署为公开体验地址 `https://rg.a703201sworld.top`（`demo` / `demo123`）。
- **代码仓库**：`https://github.com/a703201/ReturnGuard`（主）；Gitea / GitCode 镜像。
- **演示视频**：录屏覆盖「单案举证 + 群体洞察」双闭环即可。
