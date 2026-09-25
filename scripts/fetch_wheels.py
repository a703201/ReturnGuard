#!/usr/bin/env python3
"""预下载依赖 wheel 到 docker/wheels/，供 Docker 构建**离线**解析依赖。

为什么需要它
------------
容器内直连 PyPI（或国内镜像）下载依赖常常很慢甚至中断，表现为构建报
`THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE`
（本质是 wheel 下载损坏）或 `TimeoutError: The read operation timed out`。
把依赖在本机一次性下载好、随构建上下文带进镜像，可让构建变快且可复现。

用法
----
    python scripts/fetch_wheels.py                 # 默认：linux/amd64 + CPython 3.11（对齐 Docker 镜像）
    python scripts/fetch_wheels.py --clean         # 先清空旧 wheel 再下
    python scripts/fetch_wheels.py --platform manylinux2014_x86_64 --python-version 311
    python scripts/fetch_wheels.py --arch arm64    # Apple Silicon / ARM 服务器

⚠️ 关键坑（本脚本已处理）：`uvicorn[standard]` 的 `uvloop` 依赖带环境标记
`sys_platform != "win32"`，在 Windows 上执行 `pip download` 时会被**静默跳过**，
而 Linux 容器里它是必需的 → 离线解析会以 `No matching distribution found for uvloop` 失败。
故脚本在常规下载后**再显式单独下载**这些「被当前平台标记排除、但目标平台需要」的包。

生成物 `docker/wheels/*.whl` 已在 .gitignore 中忽略（体积与平台相关，不入库），
仅保留 `docker/wheels/.gitkeep` 占位，保证 Dockerfile 的 COPY 不会因目录缺失失败。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "demo" / "requirements.txt"
WHEELS_DIR = ROOT / "docker" / "wheels"

# 目标平台的 wheel 标签（默认对齐 docker/Dockerfile 的 python:3.11-slim = linux/amd64）
PLATFORM_TAGS = {
    "amd64": ["manylinux2014_x86_64", "manylinux_2_17_x86_64", "manylinux_2_28_x86_64"],
    "arm64": ["manylinux2014_aarch64", "manylinux_2_17_aarch64", "manylinux_2_28_aarch64"],
}
PLATFORM_ABI = {"amd64": "x86_64", "arm64": "aarch64"}

# 目标平台需要、但因环境标记在当前平台被跳过的包（见模块 docstring）
TARGET_ONLY_PACKAGES = ["uvloop"]


def _run(cmd: list[str]) -> int:
    print("▶ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="预下载 Docker 构建所需的离线 wheel 缓存")
    ap.add_argument("--arch", choices=sorted(PLATFORM_TAGS), default="amd64", help="目标架构")
    ap.add_argument("--python-version", default="311", help="目标 Python 版本（如 311）")
    ap.add_argument("--abi", default=None, help="ABI 标签，默认 cp<python-version>")
    ap.add_argument("--clean", action="store_true", help="先清空 docker/wheels/*.whl")
    ap.add_argument("--index-url", default=None, help="覆盖 pip 源（默认用本机 pip 配置）")
    args = ap.parse_args()

    if not REQUIREMENTS.exists():
        print(f"❌ 未找到依赖清单：{REQUIREMENTS}")
        return 1

    abi = args.abi or f"cp{args.python_version}"
    WHEELS_DIR.mkdir(parents=True, exist_ok=True)
    if args.clean:
        for f in WHEELS_DIR.glob("*.whl"):
            f.unlink()
        print("已清空旧 wheel")

    base = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--only-binary=:all:",
        "--python-version",
        args.python_version,
        "--implementation",
        "cp",
        "--abi",
        abi,
        "--retries",
        "10",
        "--timeout",
        "120",
        "-d",
        str(WHEELS_DIR),
    ]
    for tag in PLATFORM_TAGS[args.arch]:
        base += ["--platform", tag]
    if args.index_url:
        base += ["-i", args.index_url]

    print(f"== 目标平台：linux/{args.arch} · Python {args.python_version} · ABI {abi} ==")
    rc = _run(base + ["-r", str(REQUIREMENTS)])
    if rc != 0:
        print("❌ 主依赖下载失败；若因网络中断，可直接重跑本脚本（已下好的会跳过）")
        return rc

    # 补齐被环境标记排除、但目标平台必需的包（见 docstring 的 uvloop 说明）
    print("== 补齐目标平台专属依赖 ==")
    rc = _run(base + ["--no-deps", *TARGET_ONLY_PACKAGES])
    if rc != 0:
        print(f"❌ 目标平台专属依赖下载失败：{TARGET_ONLY_PACKAGES}")
        return rc

    wheels = sorted(WHEELS_DIR.glob("*.whl"))
    total_mb = sum(w.stat().st_size for w in wheels) / 1024 / 1024
    print(f"\n✅ 就绪：{len(wheels)} 个 wheel · {total_mb:.1f} MB → {WHEELS_DIR}")
    print("   现在 `docker-compose -f docker/docker-compose.yml build app` 会走离线解析。")

    # 目录标记文件：保证空目录也能被 git 跟踪、Dockerfile 的 COPY 不报错
    keep = WHEELS_DIR / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
