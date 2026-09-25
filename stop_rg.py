#!/usr/bin/env python3
# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""ReturnGuard 一键停止：停止本地容器。

用法：
    python stop_rg.py          # 交互确认后停止
    python stop_rg.py --yes    # 跳过确认直接停止
    python stop_rg.py --down   # 停容器并移除（docker-compose down，保留数据卷）

要点：
- 默认用 `docker stop` 而非 `docker rm`：保留容器，下次 `start_rg.py` 可用 `docker start` 恢复。
- `--down` 走 compose down：移除容器与网络，但 named volume（ogdata / rg_uploads / rg_state）
  默认保留，数据不丢；需要彻底清库时才显式 `docker volume rm`。
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMPOSE_FILE = os.environ.get("RG_COMPOSE_FILE", os.path.join(HERE, "docker", "docker-compose.yml"))
APP_CONTAINER = "rg_app"
DB_CONTAINER = "rg_opengauss"
INIT_CONTAINER = "rg_realdb_init"
CONTAINERS = [APP_CONTAINER, DB_CONTAINER, INIT_CONTAINER]


def _run(cmd, **kw):
    print("▶ " + " ".join(cmd))
    return subprocess.run(cmd, **kw)


def _docker_compose_bin():
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


def stop_containers() -> None:
    print("[容器] 停止 ReturnGuard 容器…")
    _run(["docker", "stop"] + CONTAINERS, check=False)
    print("    容器已停止（保留容器，start_rg.py 可用 docker start 恢复）。")


def down_stack() -> None:
    print("[容器] docker-compose down（移除容器与网络，保留数据卷）…")
    _run(_docker_compose_bin() + ["-f", COMPOSE_FILE, "down"], check=False)
    print("    已清理容器与网络；ogdata / rg_uploads / rg_state 数据卷保留。")


def main() -> int:
    ap = argparse.ArgumentParser(description="ReturnGuard 停止（容器）")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认直接停止")
    ap.add_argument("--down", action="store_true", help="停容器并移除（保留数据卷）")
    args = ap.parse_args()

    if not args.yes:
        ans = input("确认停止 ReturnGuard 容器？[y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("已取消。")
            return 0

    print("===== ReturnGuard 停止 =====")
    if args.down:
        down_stack()
    else:
        stop_containers()
    print("\n===== 完成 =====")
    print("如需重新启动：python start_rg.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
