// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
//! ReturnGuard 启动器核心引擎。
//!
//! 设计约束：
//! - 只依赖标准库，Windows / Linux 两侧都能编译与自检。
//! - 只管理仓颉版三容器栈（`docker-compose.cangjie.yml`）；不感知任何旧栈。
//! - 所有破坏性动作（stop / restart / down）必须由 UI 显式触发，核心层不擅自执行。

pub mod compose;
pub mod config;
pub mod health;
pub mod logs;
pub mod status;
pub mod system;

use std::fmt;

/// 核心层统一错误。UI 层按变体决定提示文案与恢复动作。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CoreError {
    /// 找不到项目根目录（缺少 VERSION 或 compose 文件）。
    ProjectRootNotFound(String),
    /// 本机没有可用的 docker / docker compose 命令。
    DockerNotFound,
    /// 外部命令执行失败。
    CommandFailed {
        command: String,
        code: Option<i32>,
        stderr: String,
    },
    /// 输出格式与预期不符（compose / docker 版本差异）。
    Parse(String),
    /// 网络探测失败。
    Network(String),
    /// 用户配置有问题，例如端口非法。
    InvalidConfig(String),
}

impl fmt::Display for CoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::ProjectRootNotFound(p) => {
                write!(f, "未找到 ReturnGuard 项目根目录（已尝试: {p}）")
            }
            Self::DockerNotFound => {
                write!(f, "未找到 docker 命令。请安装 Docker 并确保 docker 在 PATH 中。")
            }
            Self::CommandFailed {
                command,
                code,
                stderr,
            } => {
                let detail = stderr.trim();
                if detail.is_empty() {
                    write!(f, "命令执行失败（退出码 {code:?}）: {command}")
                } else {
                    write!(f, "命令执行失败（退出码 {code:?}）: {command}\n{detail}")
                }
            }
            Self::Parse(msg) => write!(f, "无法解析命令输出: {msg}"),
            Self::Network(msg) => write!(f, "网络探测失败: {msg}"),
            Self::InvalidConfig(msg) => write!(f, "配置无效: {msg}"),
        }
    }
}

impl std::error::Error for CoreError {}

pub type Result<T> = std::result::Result<T, CoreError>;

/// 一次用户动作的描述。UI 用它展示「正在做什么」并驱动进度动画。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Action {
    Start,
    Stop,
    Restart,
    Rebuild,
    Refresh,
    OpenBrowser,
    Logs,
}

impl Action {
    /// 动效标签： Windows / GTK 两侧共用，保证两端节奏一致。
    pub fn label(self) -> &'static str {
        match self {
            Self::Start => "启动服务",
            Self::Stop => "停止服务",
            Self::Restart => "重启服务",
            Self::Rebuild => "重新构建",
            Self::Refresh => "刷新状态",
            Self::OpenBrowser => "打开控制台",
            Self::Logs => "查看日志",
        }
    }

    /// 是否会改变容器状态。UI 据此决定是否进入「处理中」并禁用按钮。
    pub fn is_mutating(self) -> bool {
        matches!(self, Self::Start | Self::Stop | Self::Restart | Self::Rebuild)
    }
}

/// 统一动作入口。两端 UI 只调用这里，保证操作语义完全一致。
/// 同步阻塞；UI 必须在后台线程调用，主线程只负责渲染「处理中」状态。
pub fn apply_action(action: Action, config: &config::LauncherConfig) -> Result<String> {
    match action {
        Action::Refresh => Ok("状态已刷新".to_string()),
        Action::OpenBrowser => {
            // 浏览器打不开不是服务故障：给出手动地址即可，不报成操作失败。
            let _ = system::open_browser(&config.base_url);
            Ok(system::browser_hint(&config.base_url))
        }
        Action::Logs => logs::app(config),
        Action::Start | Action::Stop | Action::Restart | Action::Rebuild => {
            let compose = compose::Compose::detect().ok_or(CoreError::DockerNotFound)?;
            match action {
                Action::Start => {
                    // 与 start_rg.py 一致：已有容器用 start 保留运行态，否则首次创建。
                    if compose.app_exists()? {
                        compose.start()
                    } else {
                        compose.up(true)
                    }
                }
                Action::Stop => compose.stop(),
                Action::Restart => compose.restart_app(),
                Action::Rebuild => {
                    compose.build_image()?;
                    compose.up(true)
                }
                _ => unreachable!("已在前置 match 中处理"),
            }
        }
    }
}

/// 聚合快照：UI 一次刷新拿到全部需要渲染的数据。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AppSnapshot {
    pub version: String,
    pub base_url: String,
    pub containers: Vec<status::ContainerState>,
    pub health: health::HealthState,
    /// Docker 命令缺失或守护进程异常时的原因。为 Some 时 containers 不可信，
    /// UI 必须优先展示此错误，而不是误报「服务尚未创建」。
    pub docker_error: Option<String>,
}

impl AppSnapshot {
    /// 采集顺序：先容器（本地事实），再 HTTP 健康（运行态事实）。
    /// Docker 不可用时保留错误原因，让 UI 明确提示而不是静默当作「未创建」。
    pub fn collect(config: &config::LauncherConfig) -> Self {
        let (containers, docker_error) = match compose::Compose::detect() {
            None => (
                Vec::new(),
                Some("未找到 docker 命令，或 docker compose 不可用".to_string()),
            ),
            Some(c) => match c.container_states() {
                Ok(states) => (states, None),
                Err(err) => (
                    Vec::new(),
                    Some(format!("Docker 守护进程无响应：{err}")),
                ),
            },
        };
        let health = health::probe(&config.base_url, health::DEFAULT_TIMEOUT_MS);
        Self {
            version: config.version.clone(),
            base_url: config.base_url.clone(),
            containers,
            health,
            docker_error,
        }
    }

    /// 全部容器已启动，且健康探针为 200。
    pub fn is_ready(&self) -> bool {
        self.containers.len() == config::CONTAINERS.len()
            && self.containers.iter().all(|c| c.is_running())
            && matches!(self.health, health::HealthState::Healthy { .. })
    }

    /// 服务进程在跑但健康探针未通过 —— 对应「降级」态，需要提示用户看日志。
    pub fn is_degraded(&self) -> bool {
        self.containers.iter().any(|c| c.is_running())
            && !matches!(self.health, health::HealthState::Healthy { .. })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn snapshot_with(docker_error: Option<String>) -> AppSnapshot {
        AppSnapshot {
            version: "3.1.0".to_string(),
            base_url: "http://127.0.0.1:58080".to_string(),
            containers: Vec::new(),
            health: health::HealthState::Unreachable {
                reason: "未探测".to_string(),
            },
            docker_error,
        }
    }

    #[test]
    fn docker_error_is_not_mistaken_for_not_created() {
        let s = snapshot_with(Some("Docker 守护进程无响应".to_string()));
        // 关键回归：空容器列表本身不能让 UI 误判为「尚未创建」。
        assert!(s.docker_error.is_some());
        assert!(!s.is_ready());
        assert!(!s.is_degraded());
    }

    #[test]
    fn missing_containers_without_error_is_clean_state() {
        let s = snapshot_with(None);
        assert!(s.docker_error.is_none());
        assert!(s.containers.is_empty());
    }

    #[test]
    fn browser_hint_always_contains_url() {
        // 浏览器不可用时仍要给用户可手动访问的地址（CI 无浏览器，不能依赖真实调用）。
        let hint = system::browser_hint("http://127.0.0.1:58080");
        assert!(hint.contains("http://127.0.0.1:58080"));
    }
}
