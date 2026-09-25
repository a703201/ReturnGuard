"""ReturnGuard Demo 后端（FastAPI 装配入口）。

本文件现在只负责「装配」，不再承载业务逻辑：
    - 创建 app、定义 lifespan（启动期建库 / 预置账号 / WAL 巡检）
    - 注册中间件（缓存 / 可观测 / 安全响应头），顺序与原实现一致
    - 挂载 /static 静态资源
    - 聚合各业务路由（routers/*）

原先 1180 行的「上帝文件」已按 P1-9 拆分为：
    common.py        —— 共享配置 / 依赖 / 限流 / 中间件 / 聚合辅助
    routers/frontend.py   —— 页面 / 签名文件 / 配置 / 指标 / 平台举证包
    routers/forensic.py   —— 单案取证 / 案件库增删
    routers/insights.py   —— 群体洞察 / PDF 导出
    routers/auth.py        —— 账户 / 多租户隔离
    routers/calibration.py —— 阈值自标定
    routers/import_.py     —— 真实数据回流
所有端点的路径、方法、契约与行为保持与原实现逐行一致。
"""

from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager

import auth  # C组：账户体系 + 多租户隔离
from common import (
    _CORS_ALLOW_ORIGINS,
    _WAL_CHECKPOINT_INTERVAL,
    APP_VERSION,
    BASE,
    UPLOAD_DIR,  # 向后兼容：测试仍 `from main import UPLOAD_DIR`
    _cleanup_old_uploads,
    _start_wal_watcher,
    _wal_checkpoint_all,
    backend_name,
    import_csv_text,
    init_db,
    is_public_ready,
    logger,
    no_cache_middleware,
    observe_middleware,
    security_headers,
)
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# 业务路由（P1-9 从 main.py 拆出到 routers/*，在此聚合）：
#   frontend / forensic / insights / auth / calibration / import_
from routers import (
    auth as auth_router,
)
from routers import (
    calibration,
    forensic,
    frontend,
    insights,
)
from routers import (
    import_ as import_router,
)
from starlette.responses import Response

# 向后兼容再导出：测试与旧调用方仍 `from main import UPLOAD_DIR, app`。
# 显式列入 __all__，避免 `ruff --fix` 将仅用于重导出的 import 误判 F401 而删除。
__all__ = ["UPLOAD_DIR", "app"]

# 后端业务入口说明（保留顶层 docstring 中的产品叙事）：
# 阶段A 个案举证  → POST /api/analyze
# 阶段B 群体洞察  → GET  /api/insights
# 数据沉淀        → GET  /api/cases
# 健康检查        → GET  /health


@asynccontextmanager
async def lifespan(app):
    """服务启动时：初始化双源数据库（demo 播种 / real 空库）+ 清理过期上传图。

    支持 FORCE_RESEED=1 仅重置 demo 种子库（real 实际库始终保留，避免误清真实数据）。
    """
    if os.environ.get("FORCE_RESEED") == "1":
        init_db("demo", force=True)
    else:
        init_db("demo")
    init_db("real")  # 实际数据库：确保表存在，初始空库待录入
    # C组：账户/用户表（多租户隔离的租户目录）
    auth.init_auth_db()
    # 交付：预置演示测试账号（可直接登录 real 源体验多租户隔离 + 实际数据洞察）
    try:
        auth.register("demo", "demo123", "ReturnGuard 演示租户")
        logger.info("已预置演示测试账号 demo/demo123")
    except Exception:
        logger.exception("预置演示账号失败（不影响启动）")
    # 安全自检：生产必须固化 AUTH_SECRET，否则令牌重启即失效且不利于统一轮换
    if not os.environ.get("AUTH_SECRET"):
        logger.critical(
            "AUTH_SECRET 未设置：使用进程内随机密钥，重启将令所有令牌失效，且不利于统一轮换；生产环境务必固化 AUTH_SECRET"
        )
    # C组 openGauss 自动导入：部署期设 RG_AUTO_IMPORT_CSV=<路径>，real 源（可指向 openGauss）
    # 启动即批量回流真实退货数据，使洞察看板开箱即用真实业务数据（B组 importer 主链路）。
    auto_csv = os.environ.get("RG_AUTO_IMPORT_CSV", "")
    if auto_csv and os.path.exists(auto_csv):
        try:
            # dedupe=True：按自然键幂等导入，容器重启重复挂载同一份 CSV 不重复堆积
            res = import_csv_text(open(auto_csv, encoding="utf-8-sig").read(), "real", dedupe=True)
            logger.info("启动自动导入 CSV 完成 source=real: %s", res)
        except Exception:
            logger.exception("启动自动导入 CSV 失败（不影响服务启动）")
    _cleanup_old_uploads(max_age_hours=float(os.environ.get("UPLOAD_MAX_AGE_HOURS", "24")))
    # 图床后端自检日志：方便现场确认「当前用本地还是远端」，避免文档与运行态不一致。
    logger.info(
        "图床后端已就绪 backend=%s public_ready=%s（演示用本地/自托管；qiniu 为预留远端接口）",
        backend_name(),
        is_public_ready(),
    )
    # 启动时先截断一次历史 WAL，再起巡检线程，关闭前最后截断一次
    _wal_checkpoint_all()
    _wal_stop = _start_wal_watcher(_WAL_CHECKPOINT_INTERVAL)
    try:
        yield
    finally:
        if _wal_stop is not None:
            _wal_stop.set()
        _wal_checkpoint_all()


app = FastAPI(title="ReturnGuard Demo", lifespan=lifespan)


class VersionedStaticFiles(StaticFiles):
    """静态资源「版本化 + 禁止中间层缓存」。

    背景（2026-09-14 公网实测）：前端是无构建的 ESM，`app.js` 用**相对路径** import
    `./i18n.js` 等子模块，子模块 URL 无法天然带版本号。origin 侧即便下发 `no-cache`，
    只要中间还有一层 CDN，就可能被改写并长期缓存——实测 Cloudflare 把 origin 的
    `no-cache` 覆写成 `max-age=14400`（4 小时）下发给浏览器，导致「升级后公网前端不生效」
    而本机直连正常（典型撕裂：HTML 已更新有法语选项，JS 仍是旧版 → 切语言无效、显示裸 key）。

    对策：把版本号写进 **每一个模块的 URL**，使发版必然产生全新 URL——任何层级的缓存
    （浏览器 / CDN）都不可能命中旧副本，从根本上不依赖对方是否尊重 Cache-Control。
      - 入口由 routers/frontend.py 把 index.html 的 `__ASSET_VER__` 替换为 APP_VERSION；
      - 子模块的相对 import 由本类在响应时批量追加 `?v=<APP_VERSION>`（覆盖整条依赖链）。
    同时下发 `no-store`，让 CDN 无机会缓存这些文件。
    """

    # 只匹配静态相对 import：`from './x.js'` / `from "./x.js"`；已带 ?v= 的不重复追加。
    _IMPORT_RE = re.compile(r"""(from\s*['"])(\./[A-Za-z0-9_.\-]+\.js)(?!\?)(['"])""")

    async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-store"
        if not path.endswith(".js") or getattr(resp, "status_code", 200) != 200:
            return resp
        src_path = getattr(resp, "path", None)
        if not src_path:
            return resp
        try:
            src = open(src_path, encoding="utf-8").read()
        except OSError:
            return resp
        stamped = self._IMPORT_RE.sub(rf"\1\2?v={APP_VERSION}\3", src)
        if stamped == src:
            return resp
        return Response(
            stamped,
            media_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )


# 把 static 目录挂成 /static；版本化逻辑见 VersionedStaticFiles 文档字符串。
app.mount("/static", VersionedStaticFiles(directory=os.path.join(BASE, "static")), name="static")
# 上传目录不再公开静态挂载（SEC-8）：图片经签名 + 短期过期的 /api/file/{sig} 提供，
# 杜绝退货图（PII）被匿名长期拉取。live 模式仍由 PUBLIC_IMAGE_BASE / 对象存储公网回源。

# 公网部署跨域白名单（可选）：仅当设置 CORS_ALLOW_ORIGINS 才挂，禁止 "*"
if _CORS_ALLOW_ORIGINS:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ALLOW_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

# 中间件注册顺序与原 main.py 的 @app.middleware("http") 装饰顺序一致：
#   no_cache → observe → security（security 最外层，最先处理请求 / 最后回填安全响应头）。
app.middleware("http")(no_cache_middleware)
app.middleware("http")(observe_middleware)
app.middleware("http")(security_headers)


app.include_router(frontend.router)
app.include_router(forensic.router)
app.include_router(insights.router)
app.include_router(auth_router.router)
app.include_router(calibration.router)
app.include_router(import_router.router)


if __name__ == "__main__":
    import uvicorn

    # 0.0.0.0 便于容器化/公网部署；本地访问 http://localhost:8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
