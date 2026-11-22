// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
//! 日志读取。UI 以「查看日志」按钮触发，默认尾部 200 行；
//! 不提供实时流式，避免长时间持有 docker 进程。

use crate::{
    compose::Compose,
    config::{LauncherConfig, APP_CONTAINER},
    CoreError, Result,
};

/// 读取 app 容器日志尾部。db / autoheal 也可通过 `tail` 指定容器名查看。
pub fn read(config: &LauncherConfig, container: &str, tail: usize) -> Result<String> {
    let compose = Compose::detect().ok_or(CoreError::DockerNotFound)?;
    let _ = config; // compose 路径由 Compose::detect 自行推导，此处保留参数以稳定 API。
    compose.logs(container, tail)
}

/// 默认查看应用容器日志。
pub fn app(config: &LauncherConfig) -> Result<String> {
    let tail = config.log_tail();
    read(config, APP_CONTAINER, tail)
}

/// 把 docker 日志压成 UI 可展示的末尾片段，避免超长文本撑破布局。
pub fn preview(text: &str, max_chars: usize) -> String {
    let chars: Vec<char> = text.chars().collect();
    if chars.len() <= max_chars {
        return text.to_string();
    }
    let tail: String = chars[chars.len() - max_chars..].iter().collect();
    format!("…（已省略前 {} 字符）\n{tail}", chars.len() - max_chars)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preview_keeps_tail() {
        let s: String = (0..100).map(|_| 'x').collect();
        let p = preview(&s, 10);
        assert!(p.starts_with('…'));
        assert!(p.ends_with("xxxxxxxxxx"));
    }
}
