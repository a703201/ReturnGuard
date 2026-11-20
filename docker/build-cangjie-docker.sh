#!/bin/bash
# ============================================================
# ReturnGuard · 仓颉后端 Docker 一键构建
# ------------------------------------------------------------
# 两步：
#   ① 借 Linux 仓颉工具链镜像（ams-cj:1.2.0-beta.03）把 backend/ 编译成
#      Linux ELF（backend/build-linux/rg-server + .so）；
#   ② docker build 打运行镜像 returnguard-cj:latest。
#
# 前置：本机需有 ams-cj:1.2.0-beta.03 工具链镜像（内含 Linux cjc + stdx）。
#       首次构建工具链镜像见 AMS deploy/docker/Dockerfile.cjbase。
#
# 用法：
#   bash docker/build-cangjie-docker.sh             # 编译 + 打镜像
#   bash docker/build-cangjie-docker.sh --rebuild   # 强制重编产物
#   IMAGE_TAG=xxx bash docker/build-cangjie-docker.sh
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

IMAGE="${IMAGE_TAG:-returnguard-cj:latest}"
CJ_IMAGE="${AMS_CJ_IMAGE:-ams-cj:1.2.0-beta.03}"
# AMS Linux 备份目录：提供 opensslFFI 动态加载库（cjc runtime 不含）
EXTRA_SO="${RG_EXTRA_SO_HOST:-E:/Codes/Project/Archive_manager/.tmp/build-backup-1794815768/linux}"
REBUILD=0
for a in "$@"; do [ "$a" = "--rebuild" ] && REBUILD=1; done

# 工具链镜像缺失时自动构建（SDK 缓存在 D 盘；下载源见仓库 docs/DEPLOYMENT.md）。
# 这样磁盘故障丢失镜像后可一键恢复，无需手动翻 AMS 目录。
AMS_ROOT="${AMS_ROOT:-E:/Codes/Project/Archive_manager}"
SDK_CACHE="${SDK_CACHE:-D:/cangjie-sdk-cache}"
if ! docker image inspect "$CJ_IMAGE" >/dev/null 2>&1; then
  echo "[INFO] 工具链镜像 $CJ_IMAGE 缺失，尝试自动构建…"
  SDK_CTX="$AMS_ROOT/.tmp/sdk"
  mkdir -p "$SDK_CTX"
  # Dockerfile.cjbase 写死 beta.03 文件名；用 1.2.0 正式版 SDK 兼容填充
  [ -f "$SDK_CTX/cangjie-sdk-linux-x64-1.2.0-beta.03.tar.gz" ] || \
    cp "$SDK_CACHE/cangjie-sdk-linux-x64-1.2.0.tar.gz" "$SDK_CTX/cangjie-sdk-linux-x64-1.2.0-beta.03.tar.gz"
  [ -f "$SDK_CTX/cangjie-stdx-linux-x64-1.2.0-beta.03.1.zip" ] || \
    cp "$SDK_CACHE/cangjie-stdx-linux-x64-1.2.0.1.zip" "$SDK_CTX/cangjie-stdx-linux-x64-1.2.0-beta.03.1.zip"
  if [ ! -f "$SDK_CTX/cangjie-sdk-linux-x64-1.2.0-beta.03.tar.gz" ] || \
     [ ! -f "$SDK_CTX/cangjie-stdx-linux-x64-1.2.0-beta.03.1.zip" ]; then
    echo "[ERROR] SDK 缓存缺失（$SDK_CACHE）。请先下载 cangjie-sdk-linux-x64-1.2.0.tar.gz 与 cangjie-stdx-linux-x64-1.2.0.1.zip"
    exit 1
  fi
  (cd "$AMS_ROOT" && MSYS_NO_PATHCONV=1 docker build --no-cache -t "$CJ_IMAGE" \
      --build-context sdksrc=.tmp/sdk -f deploy/docker/Dockerfile.cjbase .)
  docker image inspect "$CJ_IMAGE" >/dev/null 2>&1 || { echo "[ERROR] 工具链镜像构建失败"; exit 1; }
  echo "[OK] 工具链镜像已自动构建：$CJ_IMAGE"
fi

echo "=== ① 容器内编译 Linux 仓颉产物 ==="
mkdir -p "$ROOT/backend/build-linux"
if [ "$REBUILD" = "1" ]; then
  EXTRA_ARG="--clean"
else
  EXTRA_ARG=""
fi
# 源码只读挂载，产物目录读写挂载；额外 so 目录只读挂载
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$ROOT/backend":/src:ro \
  -v "$ROOT/backend/build-linux":/src/build-linux:rw \
  -v "$EXTRA_SO":/extra-so:ro \
  -w /src \
  -e CANGJIE_HOME=/opt/cangjie \
  -e CANGJIE_STDX=/opt/cangjie-stdx/linux_x86_64_cjnative \
  -e RG_EXTRA_SO_DIR=/extra-so \
  "$CJ_IMAGE" \
  bash -lc "bash build-linux.sh $EXTRA_ARG"

[ -f "$ROOT/backend/build-linux/rg-server" ] || { echo "[ERROR] 未产出 rg-server"; exit 1; }
echo "[OK] Linux 产物就绪：backend/build-linux/rg-server"

echo "=== ② 打运行镜像 $IMAGE ==="
docker build -t "$IMAGE" -f docker/Dockerfile.cangjie .
echo "[OK] 镜像就绪：$IMAGE"
