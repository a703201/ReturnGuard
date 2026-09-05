#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ReturnGuard 一键启动脚本：拉起本地容器 + 开启 Cloudflare 隧道。

用法：
    python start_rg.py            # 启动项目 + 隧道，并打开公网页面
    python start_rg.py --no-open  # 不自动打开浏览器

要点：
- 用 `docker start` 而非 `docker-compose up -d` 恢复容器：保留容器内已被热补丁的代码，
  避免从旧镜像重建而丢失 P1/P0 修复。容器不存在时才退化为 `docker-compose up -d`。
- cloudflared 是原生 Windows 程序，参数必须用 `D:/` 风格绝对路径（不能用 `/d/...`）。
- 隧道配置已复制到 ASCII 路径 `D:/rg-tunnel.yml`，避免中文路径在参数里被误读。
"""
import argparse
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

# ---- 路径（Python 字符串，UTF-8 无碍，cloudflared 参数用 D:/ 风格）----
HERE = os.path.dirname(os.path.abspath(__file__))
COMPOSE_FILE = os.path.join(HERE, "docker", "docker-compose.yml")
CLOUDFLARED = r"D:\cloudflared.exe"
TUNNEL_CONFIG = r"D:\rg-tunnel.yml"          # ASCII 路径，避免中文
TUNNEL_NAME = "rg"
PUBLIC_URL = "https://rg.a703201sworld.top"
LOCAL_HEALTH = "http://127.0.0.1:65432/health"
TUNNEL_METRICS = "http://127.0.0.1:4559/metrics"
APP_CONTAINER = "rg_app"
DB_CONTAINER = "rg_opengauss"
INIT_CONTAINER = "rg_realdb_init"

CONTAINERS = [APP_CONTAINER, DB_CONTAINER, INIT_CONTAINER]


def _run(cmd, **kw):
    print("▶ " + " ".join(cmd) if isinstance(cmd, list) else cmd)
    return subprocess.run(cmd, **kw)


def _docker_compose_bin():
    # 优先 docker compose（插件），退化到独立 docker-compose。
    from shutil import which
    if which("docker") and _run(["docker", "compose", "version"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        return ["docker", "compose"]
    if which("docker-compose"):
        return ["docker-compose"]
    return ["docker", "compose"]  # 兜底


def container_exists(name):
    r = _run(["docker", "ps", "-a", "--filter", f"name=^{name}$",
              "--format", "{{.Names}}"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return name in (r.stdout or b"").decode().split()


def start_containers():
    if container_exists(APP_CONTAINER):
        print("[容器] 已存在，使用 docker start 恢复（保留热补丁代码）…")
        _run(["docker", "start"] + CONTAINERS, check=False)
    else:
        print("[容器] 不存在，首次 docker-compose up -d 创建…")
        _run(_docker_compose_bin() + ["-f", COMPOSE_FILE, "up", "-d"],
             check=False)


def wait_health(timeout=120):
    print(f"[等待] 探测 {LOCAL_HEALTH} …")
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(LOCAL_HEALTH, timeout=3) as r:
                if r.status == 200:
                    print(f"    本地服务就绪（{time.time()-t0:.0f}s）")
                    return True
        except Exception:
            pass
        time.sleep(2)
    print("    ⚠️ 本地服务未在超时内就绪，请检查 `docker logs rg_app`")
    return False


def tunnel_running():
    try:
        with urllib.request.urlopen(TUNNEL_METRICS, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def start_tunnel():
    if tunnel_running():
        print("[隧道] 已在运行（metrics 端口 4559 响应），跳过。")
        return True
    if not os.path.exists(CLOUDFLARED):
        print(f"    ⚠️ 未找到 {CLOUDFLARED}，跳过隧道启动。")
        return False
    if not os.path.exists(TUNNEL_CONFIG):
        print(f"    ⚠️ 未找到 {TUNNEL_CONFIG}，跳过隧道启动。")
        return False
    # DETACHED_PROCESS：独立于本脚本生命周期，关机才停。
    print(f"[隧道] 启动 cloudflared tunnel --config {TUNNEL_CONFIG} run {TUNNEL_NAME} …")
    try:
        subprocess.Popen(
            [CLOUDFLARED, "tunnel", "--config", TUNNEL_CONFIG, "run", TUNNEL_NAME],
            creationflags=0x00000008,  # DETACHED_PROCESS
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"    ⚠️ 隧道启动失败：{e}")
        return False
    # 等隧道连通
    for _ in range(20):
        try:
            with urllib.request.urlopen(PUBLIC_URL + "/health", timeout=5) as r:
                if r.status == 200:
                    print("    公网隧道已连通。")
                    return True
        except Exception:
            pass
        time.sleep(2)
    print("    ⚠️ 隧道进程已起，但公网探测超时（可能边缘节点仍在建立）。")
    return True


def main():
    ap = argparse.ArgumentParser(description="ReturnGuard 启动（容器 + 隧道）")
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    print("===== ReturnGuard 启动 =====")
    start_containers()
    ok = wait_health()
    start_tunnel()

    print("\n===== 完成 =====")
    print(f"本地  : {LOCAL_HEALTH}")
    print(f"公网  : {PUBLIC_URL}  （评委登录用 demo / demo123）")
    if not args.no_open and ok:
        try:
            webbrowser.open(PUBLIC_URL)
            print("已打开公网页面。")
        except Exception:
            pass


if __name__ == "__main__":
    main()
