# ReturnGuard 复赛 Demo（最小可运行版）

单笔退货**取证** → 多案聚合**洞察**的双闭环最小实现。前端单页 + FastAPI 后端，`mock` 模式零依赖即可演示，`live` 模式接真实阿里云百炼 Model Router。

## 目录
```
demo/
  main.py            # FastAPI 入口（/ 首页, /api/analyze, /api/insights, /api/cases, /api/auth/*, /api/calibrate, /api/import_csv, /api/file/{sig}, /metrics, /api/config）
  pipeline.py        # 取证+洞察流水线（mock / live 双模式）
  models_router.py   # Model Router 实时调用（live 模式）
  auth.py            # 账户/多租户（pbkdf2 60 万轮 + HMAC 签名令牌）
  shared_state.py    # 限流/登录锁外置 SQLite（多 worker 安全，SEC-12）
  storage.py         # 图床抽象 + 上传图签名短链（SEC-8）
  requirements.txt
  cases.json         # 案例库（运行时写入）
  uploads/           # 上传图片落盘（经 HMAC 签名短链 /api/file/{sig} 访问，不再公开挂载）
  static/index.html  # 单页前端（取证 + 洞察看板）
```

## 快速开始（mock 模式，无需 Key）
```bash
cd demo
pip install -r requirements.txt
python main.py
# 浏览器打开 http://localhost:8000
```
- 上传「退回商品图」+「本店主图」→ 点「开始取证」：输出相似度、瑕疵标签、一致性、举证报告、母语语音（占位音）、优先级。
- 点「刷新洞察」：聚合历史案件，展示高纠纷 SKU 排行、缺陷分布、选品/品控建议。
- mock 相似度由文件名哈希决定，**同一对图结果可复现**，便于演示与录屏。

## live 模式（接真实 Model Router）
需先准备：
1. 可公网访问的图片地址（生产用对象存储，如阿里云 OSS），把 `uploads/` 同步到该 base URL（live 回源用；本地回退图经签名短链 `/api/file/{sig}` 访问，详见 `docs/API.md` §3.7）。
2. 环境变量：
```bash
export MODEL_ROUTER_API_KEY=sk-xxx
export PUBLIC_IMAGE_BASE=https://your-oss-bucket.example.com/returnguard/uploads
```
前端模式选 `live` 即可走真实 `tongyi-embedding-vision-plus` / `qwen3-vl-plus` / `qwen-vl-ocr` / `qwen3-max` / `qwen3-tts-instruct-flash` 链路。
（若 live 调用失败，自动回退 mock，保证演示不中断。）

## 复赛交付映射
- **可运行 Demo**：本服务即最小 Demo，可容器化部署为公开体验地址。
- **代码仓库**：本目录已纳入 `https://github.com/a703201/ReturnGuard`。
- **演示视频**：录屏覆盖「单案举证 + 群体洞察」双闭环即可。
