// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
//! 容器状态解析。原始事实来自 `docker ps -a --format`。

use crate::config::CONTAINERS;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ContainerPhase {
    /// Up，且健康检查通过（或该容器没有 healthcheck）。
    Running,
    /// Up，但健康检查未通过 —— 对应降级态。
    Unhealthy,
    /// Exited / Dead / Paused。
    Stopped,
    /// compose 中声明但尚未创建。
    Missing,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContainerState {
    pub name: String,
    pub phase: ContainerPhase,
    /// docker 原始状态串，供 UI 的 tooltip / 详情展示。
    pub detail: String,
}

impl ContainerState {
    pub fn parse(name: &str, raw: &str) -> Self {
        let phase = if raw.contains("(unhealthy)") {
            ContainerPhase::Unhealthy
        } else if raw.starts_with("Up") {
            ContainerPhase::Running
        } else {
            ContainerPhase::Stopped
        };
        Self {
            name: name.to_string(),
            phase,
            detail: raw.to_string(),
        }
    }

    pub fn missing(name: &str) -> Self {
        Self {
            name: name.to_string(),
            phase: ContainerPhase::Missing,
            detail: "未创建".to_string(),
        }
    }

    /// Running 与 Unhealthy 都算「进程在跑」，用于判断是否需要停止而非创建。
    pub fn is_running(&self) -> bool {
        matches!(self.phase, ContainerPhase::Running | ContainerPhase::Unhealthy)
    }

    /// UI 展示文案。中文，主动语态，不说「未知错误」。
    pub fn label(&self) -> &'static str {
        match self.phase {
            ContainerPhase::Running => "运行中",
            ContainerPhase::Unhealthy => "运行异常",
            ContainerPhase::Stopped => "已停止",
            ContainerPhase::Missing => "未创建",
        }
    }

    pub fn is_app(&self) -> bool {
        self.name == crate::config::APP_CONTAINER
    }
}

/// 按 compose 声明顺序返回对应的状态，缺失项补 Missing。
pub fn ordered<'a>(states: &'a [ContainerState]) -> Vec<&'a ContainerState> {
    CONTAINERS
        .iter()
        .map(|name| {
            states
                .iter()
                .find(|s| s.name == *name)
                .unwrap_or_else(|| unreachable!("collect 保证补齐"))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_docker_status() {
        assert_eq!(
            ContainerState::parse("rg_cj_app", "Up 3 minutes (healthy)").phase,
            ContainerPhase::Running
        );
        assert_eq!(
            ContainerState::parse("rg_cj_app", "Up 3 minutes (unhealthy)").phase,
            ContainerPhase::Unhealthy
        );
        assert_eq!(
            ContainerState::parse("rg_cj_db", "Exited (0) 5 minutes ago").phase,
            ContainerPhase::Stopped
        );
        assert_eq!(ContainerState::missing("x").phase, ContainerPhase::Missing);
    }

    #[test]
    fn ordered_keeps_compose_order() {
        let states = vec![
            ContainerState::missing("rg_cj_autoheal"),
            ContainerState::missing("rg_cj_app"),
            ContainerState::missing("rg_cj_opengauss"),
        ];
        let names: Vec<_> = ordered(&states).iter().map(|s| s.name.as_str()).collect();
        assert_eq!(names, CONTAINERS);
    }
}
