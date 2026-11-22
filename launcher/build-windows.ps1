# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
# ReturnGuard 启动器 · Windows 构建入口
#
# 前置条件（缺一不可）：
#   1. Rust >= 1.95（windows-reactor 0.100 的最低要求），target x86_64-pc-windows-msvc
#   2. Visual Studio Build Tools —— “使用 C++ 的桌面开发” workload（提供 MSVC link.exe）
#   3. 构建机能访问 nuget.org —— build.rs 会 stage WinAppSDK Runtime 2.4.0
#
# 用法（在 launcher/ 目录）：
#   powershell -ExecutionPolicy Bypass -File .\build-windows.ps1

$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    Write-Host '==> 校验 Rust 工具链' -ForegroundColor Cyan
    cargo --version
    rustc --version

    Write-Host '==> 核心引擎自检' -ForegroundColor Cyan
    cargo test -p rg-core

    Write-Host '==> 构建 WinUI 3 启动器（release）' -ForegroundColor Cyan
    cargo build --release -p rg-win

    $exe = Join-Path $PSScriptRoot 'target\release\rg-win.exe'
    if (-not (Test-Path $exe)) {
        throw "未找到产物：$exe"
    }
    Write-Host "构建完成：$exe" -ForegroundColor Green
    Write-Host '注意：同目录的 WinAppSDK 运行时 DLL 是应用的一部分，分发时请整体复制 target\release 目录。' -ForegroundColor Yellow
}
finally {
    Pop-Location
}
