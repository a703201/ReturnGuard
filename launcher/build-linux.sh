#!/usr/bin/env bash
# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
# ReturnGuard 启动器 · Linux 构建入口
#
# 前置条件（Debian/Ubuntu）：
#   sudo apt-get install -y libgtk-4-dev pkg-config build-essential
#   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
#
# 用法（在 launcher/ 目录）：
#   bash build-linux.sh

set -euo pipefail
cd "$(dirname "$0")"

echo '==> 校验系统依赖'
pkg-config --modversion gtk4

echo '==> 校验 Rust 工具链'
cargo --version
rustc --version

echo '==> 核心引擎自检'
cargo test -p rg-core

echo '==> 构建 GTK4 启动器（release）'
cargo build --release -p rg-gtk

echo "构建完成：$(pwd)/target/release/rg-gtk"
