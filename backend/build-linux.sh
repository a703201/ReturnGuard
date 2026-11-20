#!/bin/bash
# ============================================================
# ReturnGuard 仓颉后端 · Linux 容器内构建脚本（cjc 子包粒度）
# ------------------------------------------------------------
# 由 build.sh（Windows 本机版）移植而来，运行于 ams-cj 工具链镜像内：
#   -cjc 为 Linux 版（x86_64-unknown-linux-gnu），无需 MSYS 参数转换；
#   -stdx 为 /opt/cangjie-stdx/...，opengauss 驱动为 drv-linux/ 下的 Linux .a；
#   -产物为 build-linux/rg-server（ELF，无扩展名）。
#
# 用法（在容器内，由 build-linux-docker.sh 调用）：
#   AMS_BUILD_DIR=build-linux bash build-linux.sh
# ============================================================
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BUILD_DIR="${RG_BUILD_DIR:-build-linux}"
CJC="${CANGJIE_HOME:-/opt/cangjie}/bin/cjc"
STDX_DIR="${CANGJIE_STDX:-/opt/cangjie-stdx/linux_x86_64_cjnative}/dynamic/stdx"
DRV_DIR="$ROOT/drv-linux"

CLEAN=0
for arg in "$@"; do case "$arg" in --clean) CLEAN=1;; esac; done
[ "$CLEAN" = "1" ] && rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

if [ ! -f "$CJC" ]; then echo "[ERROR] 找不到 cjc: $CJC"; exit 1; fi
if [ ! -d "$STDX_DIR" ]; then echo "[ERROR] 找不到 stdx: $STDX_DIR"; exit 1; fi
if [ ! -d "$DRV_DIR" ]; then echo "[ERROR] 找不到 Linux 驱动库: $DRV_DIR"; exit 1; fi

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
# Linux 原生路径，直接用绝对路径，无需 cygpath / MSYS2_ARG_CONV_EXCL
# ⚠️ 不能把所有 libstdx*.so 全链上：Linux ld 不允许共享库存在链接期无法解析的符号。
# syntax / unittest / plugin.manager / 切面编织(fuzz/aspect_*) 是编译期/工具链专用模块，
# 依赖仓颉编译器前端（Cangjie::Parser/Lexer/AST），运行时不该进链接，
# 否则报 "undefined reference to Cangjie::Parser::..."。排除清单与 AMS build-linux.sh 一致。
STDX_LIBS=()
for so in "$STDX_DIR"/libstdx*.so; do
  [ -f "$so" ] || continue
  base="$(basename "$so")"
  case "$base" in
    libstdx.syntax.so|libstdx.unittest*.so|libstdx.plugin.manager.so|\
    libstdx.wave_aspects.so|libstdx.aspect_cj.so|libstdx.collect_aspects.so|\
    libstdx.fuzz.so) continue ;;
  esac
  STDX_LIBS+=("-l:$base")
done

echo "=== ReturnGuard 仓颉后端 Linux 构建 ==="
LINK_LIBS=()
for pkg in "${PKGS[@]}"; do
  top="${pkg%%/*}"
  topname="${top#rg-}"
  if [[ "$pkg" == "$top" ]]; then
    fullname="rg.${topname}"
    subdir="$top/src"
  else
    sub="${pkg#*/}"
    fullname="rg.${topname}.${sub//\//.}"
    subdir="$top/src/$sub"
  fi
  [ ! -d "$subdir" ] && continue
  ls "$subdir"/*.cj >/dev/null 2>&1 || continue
  printf "  [BUILD] %-24s " "$fullname"
  rm -f "$BUILD_DIR/$fullname.cjo" "$BUILD_DIR/lib$fullname.a"
  "$CJC" -O2 -p "$subdir" \
      --import-path "$SYSROOT" --import-path "$STDX_DIR" --import-path "$DRV_DIR" \
      --output-type staticlib --output-dir "$BUILD_DIR" > /tmp/rg_build_linux.log 2>&1
  if [ -f "$BUILD_DIR/lib$fullname.a" ]; then
    echo "OK"
    LINK_LIBS+=("$ROOT/$BUILD_DIR/lib$fullname.a")
  else
    echo "FAILED"
    grep -n -A5 "error:" /tmp/rg_build_linux.log | head -30 | sed 's/^/           /'
    exit 1
  fi
done

echo "  [BUILD] rg.server (exe)"
rm -f "$BUILD_DIR/rg-server"
DRV_LIBS=""
for a in "$DRV_DIR"/*.a; do [ -f "$a" ] && DRV_LIBS="$DRV_LIBS $a"; done
# 静态库间存在交叉引用（api → kernel/…），用 --start-group/--end-group
# 让 ld 反复解析符号，避免顺序导致的 undefined reference。
# 注意：cjc 把 --link-options 原样传给 ld，须用裸参数（无 -Wl, 前缀），
# 与 cjc 内部自动生成的 --start-group 保持一致。
LINK_STR="--start-group ${LINK_LIBS[*]} $DRV_LIBS --end-group -L$STDX_DIR ${STDX_LIBS[*]}"
"$CJC" -O2 -p rg-server/src \
    --import-path "$SYSROOT" --import-path "$STDX_DIR" --import-path "$DRV_DIR" \
    --output-type exe -o "$BUILD_DIR/rg-server" \
    --link-options "$LINK_STR" > /tmp/rg_build_linux.log 2>&1
if [ -f "$BUILD_DIR/rg-server" ]; then
  echo "OK -> $BUILD_DIR/rg-server"
else
  echo "FAILED"
  grep -n -A5 "error:" /tmp/rg_build_linux.log | head -40 | sed 's/^/           /'
  exit 1
fi

# 把 stdx + 运行时 .so 拷到 exe 同目录（Dockerfile 里设 LD_LIBRARY_PATH 指向此目录）
RUNTIME_DIR="${CANGJIE_HOME:-/opt/cangjie}/runtime/lib/linux_x86_64_cjnative"
for so in "$STDX_DIR"/libstdx*.so "$RUNTIME_DIR"/*.so; do
  [ -f "$so" ] && cp -f "$so" "$BUILD_DIR/" 2>/dev/null
done
# 补充动态加载器 FFI 库：部分 stdx.crypto（openssl 后端）在运行时按名加载，
# 不在 SDK runtime 目录，由 AMS Linux 备份提供（RG_EXTRA_SO_DIR 指定）。
EXTRA_SO_DIR="${RG_EXTRA_SO_DIR:-}"
if [ -n "$EXTRA_SO_DIR" ] && [ -d "$EXTRA_SO_DIR" ]; then
  for so in "$EXTRA_SO_DIR"/libcangjie*.so "$EXTRA_SO_DIR"/libstdx*.so; do
    [ -f "$so" ] && cp -f "$so" "$BUILD_DIR/" 2>/dev/null
  done
fi
echo "  runtime .so: $(ls "$BUILD_DIR"/*.so 2>/dev/null | wc -l)"
echo "[OK] Linux 产物就绪：$BUILD_DIR/rg-server"
