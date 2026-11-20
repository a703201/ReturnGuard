#!/bin/bash
# ============================================================
# ReturnGuard 仓颉后端 · 本机构建脚本（cjc 子包粒度）
# ------------------------------------------------------------
# 参考档案管理系统（AMS）scripts/build.sh 的成熟做法：
#   - cjpm 在本机 Windows 触发堆损坏，故用 cjc 逐包 staticlib + exe 链接；
#   - 子包必须独立目录（同一 src 目录只能有一个 package 声明）；
#   - 链接参数含 stdx 动态库，且必须禁用 MSYS 参数转换（否则 -l:xxx 被转义成 -l;xxx）。
#
# 用法：
#   bash build.sh              # 全量构建
#   bash build.sh --clean      # 清理后重建
#   bash build.sh --run        # 构建后前台运行服务
# 产物：build/rg-server.exe
# ============================================================
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BUILD_DIR="build"
CJC="E:/Cangjie/bin/cjc.exe"
STDX_DIR="E:/CangjieLibs/windows_x86_64_cjnative/dynamic/stdx"

CLEAN=0; RUN=0
for arg in "$@"; do case "$arg" in --clean) CLEAN=1;; --run) RUN=1;; esac; done
[ "$CLEAN" = "1" ] && rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

if [ ! -f "$CJC" ]; then echo "[ERROR] 找不到 cjc: $CJC"; exit 1; fi
if [ ! -d "$STDX_DIR" ]; then echo "[ERROR] 找不到 stdx: $STDX_DIR"; exit 1; fi

# 编译顺序按依赖从低到高（下游 import 上游 .cjo）
PKGS=(
  "rg-kernel" "rg-kernel/error" "rg-kernel/log" "rg-kernel/json"
  "rg-data" "rg-data/store" "rg-data/db"
  "rg-security" "rg-security/crypto" "rg-security/totp" "rg-security/audit" "rg-security/authn" "rg-security/quota" "rg-security/oauth"
  "rg-ai"
  "rg-app" "rg-app/config" "rg-app/auth" "rg-app/insights"
  "rg-api" "rg-api/http" "rg-api/server" "rg-api/routes"
)

SYSROOT="$BUILD_DIR"
# 🔴 路径含中文时 cjc 无法解析 MSYS 风格（/e/... 乱码）；所有 --import-path / -L
# 一律用 Windows 风格（E:/...），与 AMS build.sh 的 win_path() 同思路。
ROOT_WIN="$(cygpath -m "$ROOT")"
DRV_WIN="$ROOT_WIN/drv"
# 收集 stdx 动态库链接参数（-l:完整文件名）；禁用 MSYS 转换后再传给 cjc
STDX_LIBS=()
for dll in "$STDX_DIR"/libstdx*.dll; do [ -f "$dll" ] && STDX_LIBS+=("-l:$(basename "$dll")"); done

echo "=== ReturnGuard 仓颉后端构建 ==="
LINK_LIBS=()
for pkg in "${PKGS[@]}"; do
  # 目录 -> (包名, 源目录)：顶层 dir/src；子包 dir/src/<sub>
  top="${pkg%%/*}"
  topname="${top#rg-}"          # rg-kernel -> kernel
  if [[ "$pkg" == "$top" ]]; then
    fullname="rg.${topname}"
    subdir="$top/src"
  else
    sub="${pkg#*/}"             # kernel/error 里的 error
    fullname="rg.${topname}.${sub//\//.}"
    subdir="$top/src/$sub"
  fi
  [ ! -d "$subdir" ] && continue
  ls "$subdir"/*.cj >/dev/null 2>&1 || continue
  printf "  [BUILD] %-24s " "$fullname"
  rm -f "$BUILD_DIR/$fullname.cjo" "$BUILD_DIR/lib$fullname.a"
  MSYS2_ARG_CONV_EXCL='*' "$CJC" -O2 -p "$subdir" \
      --import-path "$SYSROOT" --import-path "$STDX_DIR" --import-path "$DRV_WIN" \
      --output-type staticlib --output-dir "$BUILD_DIR" > /tmp/rg_build.log 2>&1
  if [ -f "$BUILD_DIR/lib$fullname.a" ]; then
    echo "OK"
    LINK_LIBS+=("$(cygpath -m "$ROOT/$BUILD_DIR/lib$fullname.a")")
  else
    echo "FAILED"
    grep -n -A5 "error:" /tmp/rg_build.log | head -30 | sed 's/^/           /'
    exit 1
  fi
done

# 入口包 rg.server（rg-server/src）
echo "  [BUILD] rg.server (exe)"
rm -f "$BUILD_DIR/rg-server.exe"
# 驱动静态库：opengauss-driver 的 14 个 .a（链接顺序在本包之后）
DRV_LIBS=""
for a in "$ROOT/drv"/*.a; do [ -f "$a" ] && DRV_LIBS="$DRV_LIBS $(cygpath -m "$a")"; done
LINK_STR="${LINK_LIBS[*]} $DRV_LIBS -L$STDX_DIR ${STDX_LIBS[*]}"
MSYS2_ARG_CONV_EXCL='*' "$CJC" -O2 -p rg-server/src \
    --import-path "$SYSROOT" --import-path "$STDX_DIR" --import-path "$DRV_WIN" \
    --output-type exe -o "$BUILD_DIR/rg-server.exe" \
    --link-options "$LINK_STR" > /tmp/rg_build.log 2>&1
if [ -f "$BUILD_DIR/rg-server.exe" ]; then
  echo "OK -> build/rg-server.exe"
else
  echo "FAILED"
  grep -n -A5 "error:" /tmp/rg_build.log | head -40 | sed 's/^/           /'
  exit 1
fi

# Windows 下把 stdx 与运行时 DLL 拷到 exe 同目录：
# lld 默认从 exe 所在目录找 DLL，避免 Git Bash 里 PATH（MSYS/Windows 风格混用）踩坑。
for dll in "$STDX_DIR"/libstdx*.dll "E:/Cangjie/runtime/lib/windows_x86_64_cjnative"/*.dll; do
  [ -f "$dll" ] && cp -f "$dll" "$BUILD_DIR/" 2>/dev/null
done

if [ "$RUN" = "1" ]; then
  echo "=== RUN ==="
  exec "$BUILD_DIR/rg-server.exe"
fi
