#!/usr/bin/env python3
"""ReturnGuard 一键启动脚本：拉起本地容器并等待服务就绪。

用法：
    python start_rg.py            # 启动容器并打开本地页面
    python start_rg.py --no-open  # 不自动打开浏览器
    python start_rg.py --build    # 强制重新构建镜像后再启动（改代码后用）

要点：
- 用 `docker start` 而非 `docker-compose up -d` 恢复已有容器：保留容器内的运行态，
  避免从旧镜像重建而丢失改动。容器不存在时才退化为 `docker-compose up -d --build`。
- 本地端口固定 `127.0.0.1:65432`（compose 把容器 8000 映射到宿主机回环）：
  Windows 上非提权进程绑定 0.0.0.0 低端口会报 `winerror 10013`。
- 若要用 systemd 常驻部署，见 `docker/returnguard.service` 与 `docs/DEPLOYMENT.md`。
"""

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

# ---- 路径（项目已整体迁移至 E 盘，路径全部由脚本自身位置推导，不写死盘符）----
HERE = os.path.dirname(os.path.abspath(__file__))
COMPOSE_FILE = os.environ.get("RG_COMPOSE_FILE", os.path.join(HERE, "docker", "docker-compose.yml"))
LOCAL_URL = os.environ.get("RG_LOCAL_URL", "http://127.0.0.1:65432")
LOCAL_HEALTH = LOCAL_URL.rstrip("/") + "/health"
APP_CONTAINER = "rg_app"
DB_CONTAINER = "rg_opengauss"
INIT_CONTAINER = "rg_realdb_init"

CONTAINERS = [APP_CONTAINER, DB_CONTAINER, INIT_CONTAINER]


def _run(cmd, **kw):
    print("▶ " + " ".join(cmd) if isinstance(cmd, list) else cmd)
    return subprocess.run(cmd, **kw)


def _docker_compose_bin():
    """优先 docker compose（插件），退化到独立 docker-compose，最后兜底。"""
    from shutil import which

    if which("docker"):
        probe = subprocess.run(
            ["docker", "compose", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if probe.returncode == 0:
            return ["docker", "compose"]
    if which("docker-compose"):
        return ["docker-compose"]
    return ["docker", "compose"]


def container_exists(name: str) -> bool:
    r = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return name in (r.stdout or b"").decode().split()


def start_containers(rebuild: bool = False) -> None:
    if not rebuild and container_exists(APP_CONTAINER):
        print("[容器] 已存在，使用 docker start 恢复（保留容器内改动）…")
        _run(["docker", "start"] + CONTAINERS, check=False)
        return
    print("[容器] 首次创建 / 强制重建：docker-compose up -d --build …")
    _run(_docker_compose_bin() + ["-f", COMPOSE_FILE, "up", "-d", "--build"], check=False)


def wait_health(timeout: int = 180) -> bool:
    """轮询 /health 直到 200 或超时。首次启动含 openGauss 初始化，故默认给足 3 分钟。"""
    print(f"[等待] 探测 {LOCAL_HEALTH} …")
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(LOCAL_HEALTH, timeout=3) as r:
                if r.status == 200:
                    print(f"    服务就绪（{time.time() - t0:.0f}s）")
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(2)
    print("    ⚠️ 服务未在超时内就绪，请检查 `docker logs rg_app`")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="ReturnGuard 本地启动（容器）")
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--build", action="store_true", help="强制重新构建镜像后再启动")
    args = ap.parse_args()

    print("===== ReturnGuard 启动 =====")
    start_containers(rebuild=args.build)
    ok = wait_health()

    print("\n===== 完成 =====")
    print(f"本地访问: {LOCAL_URL}")
    print("测试账号: demo / demo123")
    if not args.no_open and ok:
        try:
            webbrowser.open(LOCAL_URL)
            print("已打开本地页面。")
        except Exception:
            pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
