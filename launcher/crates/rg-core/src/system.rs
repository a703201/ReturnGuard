// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
//! 操作系统交互：打开浏览器。只使用系统默认浏览器，不内置 WebView。

use crate::{CoreError, Result};

/// 用系统默认浏览器打开控制台地址。
/// Windows 用 `cmd /C start "" <url>`（空标题不可省，否则含空格的参数被当标题）；
/// Linux 用 `xdg-open`。
pub fn open_browser(url: &str) -> Result<()> {
    #[cfg(target_os = "windows")]
    {
        use std::process::Command;
        let status = Command::new("cmd")
            .args(["/C", "start", "", url])
            .status()
            .map_err(|e| CoreError::CommandFailed {
                command: format!("cmd /C start \"\" {url}"),
                code: None,
                stderr: e.to_string(),
            })?;
        if !status.success() {
            return Err(CoreError::CommandFailed {
                command: format!("cmd /C start \"\" {url}"),
                code: status.code(),
                stderr: "系统未能打开默认浏览器".to_string(),
            });
        }
        Ok(())
    }

    #[cfg(target_os = "linux")]
    {
        use std::process::Command;
        let status = Command::new("xdg-open")
            .arg(url)
            .status()
            .map_err(|e| CoreError::CommandFailed {
                command: format!("xdg-open {url}"),
                code: None,
                stderr: e.to_string(),
            })?;
        if !status.success() {
            return Err(CoreError::CommandFailed {
                command: format!("xdg-open {url}"),
                code: status.code(),
                stderr: "系统未能打开默认浏览器".to_string(),
            });
        }
        Ok(())
    }

    #[cfg(not(any(target_os = "windows", target_os = "linux")))]
    {
        let _ = url;
        Err(CoreError::InvalidConfig(
            "当前平台不支持自动打开浏览器，请手动复制地址".to_string(),
        ))
    }
}

/// 供 UI 展示的「打开控制台」提示文案。
pub fn browser_hint(url: &str) -> String {
    format!("如浏览器未自动打开，请访问 {url}")
}
