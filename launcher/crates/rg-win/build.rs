// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
//! Stage Windows App SDK 运行时，使启动器自包含（用户无需预装 WinAppSDK）。
//!
//! CI 只做类型检查时可设 `RG_SKIP_WINAPP_STAGE=1` 跳过 nuget 下载与 DLL 拷贝；
//! 正式发布构建必须保持默认（执行 staging），否则产物缺少运行时 DLL。

fn main() {
    if std::env::var_os("RG_SKIP_WINAPP_STAGE").is_some() {
        println!("cargo:warning=跳过 WinAppSDK runtime staging（RG_SKIP_WINAPP_STAGE）；此产物不可分发");
        return;
    }
    windows_reactor_setup::as_self_contained();
}
