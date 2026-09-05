#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ReturnGuard 一键停止：关 Cloudflare 隧道 + 停本地容器。

用法：
    python stop_rg.py          # 交互确认后停止
    python stop_rg.py --yes    # 跳过确认直接停止

要点：
- 先停隧道（cloudflared）再停容器，避免隧道在容器已停时反复重试连接。
- 优先用 start_rg.py 写入的 `.rg_tunnel.pid` 精确杀进程；
  找不到 PID 文件时回退到按进程名终止（taskkill / pkill），避免误伤其他 cloudflared。
- 容器用 `docker stop` 而非 `docker rm`：保留容器，下次 `start_rg.py` 用
  `docker start` 恢复（保留容器内热补丁代码，不丢失 P1/P0 修复）。
"""
import argparse
import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(HERE, ".rg_tunnel.pid")
APP_CONTAINER = "rg_app"
DB_CONTAINER = "rg_opengauss"
INIT_CONTAINER = "rg_realdb_init"
CONTAINERS = [APP_CONTAINER, DB_CONTAINER, INIT_CONTAINER]


def _run(cmd, **kw):
    print("▶ " + " ".join(cmd))
    return subprocess.run(cmd, **kw)


def is_windows():
    return os.name == "nt" or sys.platform.startswith("win")


def _kill_pid(pid):
    try:
        if is_windows():
            r = subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return r.returncode == 0
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


def _kill_by_name():
    try:
        if is_windows():
            subprocess.run(["taskkill", "/IM", "cloudflared.exe", "/F", "/T"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["pkill", "-f", "cloudflared"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def stop_tunnel():
    print("[隧道] 关闭 Cloudflare 隧道…")
    pid = None
    if os.path.exists(PID_FILE):
        try:
            pid = int(open(PID_FILE, encoding="utf-8").read().strip())
        except Exception:
            pid = None
    if pid:
        if _kill_pid(pid):
            print(f"    已按 PID {pid} 终止隧道进程。")
        else:
            print(f"    PID {pid} 未找到，回退按进程名终止。")
            _kill_by_name()
    else:
        print("    无 PID 记录，按进程名终止 cloudflared。")
        _kill_by_name()
    try:
        os.remove(PID_FILE)
    except Exception:
        pass


def stop_containers():
    print("[容器] 停止 ReturnGuard 容器…")
    _run(["docker", "stop"] + CONTAINERS, check=False)
    print("    容器已停止（保留容器，start_rg.py 可用 docker start 恢复）。")


def main():
    ap = argparse.ArgumentParser(description="ReturnGuard 停止（容器 + 隧道）")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认直接停止")
    args = ap.parse_args()

    if not args.yes:
        ans = input("确认停止 ReturnGuard（容器 + Cloudflare 隧道）？[y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("已取消。")
            return

    print("===== ReturnGuard 停止 =====")
    stop_tunnel()
    stop_containers()
    time.sleep(1)
    print("\n===== 完成 =====")
    print("如需重新启动：python start_rg.py")


if __name__ == "__main__":
    main()
