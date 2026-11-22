// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
//! Compose / Docker 命令封装。
//! 与 `start_rg.py` 的语义保持一致：容器已存在时优先 `docker start` 保留运行态，
//! 只有首次创建或显式重建才 `compose up --build`。

use std::{
    ffi::OsString,
    path::PathBuf,
    process::{Command, Output},
};

use crate::{
    config::{LauncherConfig, APP_CONTAINER, CONTAINERS},
    status::ContainerState,
    CoreError, Result,
};

/// 停止顺序：应用 → 自愈 → 数据库。
/// 不是简单的 CONTAINERS 逆序（那是 autoheal → app → db）：
/// 自愈守护必须先停，否则它会把刚停掉的应用又拉起来。
/// 独立成函数便于测试锁定这三个约束。
fn stop_order() -> [&'static str; 3] {
    [APP_CONTAINER, CONTAINERS[2], CONTAINERS[0]]
}

/// compose 命令来源。优先插件式 `docker compose`，回退独立 `docker-compose`。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ComposeKind {
    Plugin,
    Standalone,
}

#[derive(Debug, Clone)]
pub struct Compose {
    kind: ComposeKind,
    repo_root: PathBuf,
    compose_file: PathBuf,
}

impl Compose {
    /// 探测可用命令。只探测，不执行任何有副作用的操作。
    pub fn detect() -> Option<Self> {
        let root = LauncherConfig::discover().ok()?;
        let probe = |bin: &str, args: &[&str]| -> bool {
            Command::new(bin)
                .args(args)
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .status()
                .map(|s| s.success())
                .unwrap_or(false)
        };

        let kind = if probe("docker", &["compose", "version"]) {
            ComposeKind::Plugin
        } else if probe("docker-compose", &["--version"]) {
            ComposeKind::Standalone
        } else {
            return None;
        };

        Some(Self {
            kind,
            repo_root: root.repo_root,
            compose_file: root.compose_file,
        })
    }

    /// 供测试/调用方显式构造。
    pub fn new(kind: ComposeKind, repo_root: PathBuf, compose_file: PathBuf) -> Self {
        Self {
            kind,
            repo_root,
            compose_file,
        }
    }

    pub fn kind(&self) -> ComposeKind {
        self.kind.clone()
    }

    /// 首次创建 / 显式重建：`docker compose -f <file> up -d --build`。
    pub fn up(&self, build: bool) -> Result<String> {
        let mut args: Vec<OsString> = vec!["-f".into(), self.compose_file.clone().into()];
        args.push("up".into());
        args.push("-d".into());
        if build {
            args.push("--build".into());
        }
        self.run_compose(&args)
    }

    /// 容器已存在：恢复运行态，不重建、不丢容器内改动。
    /// 顺序沿用 CONTAINERS：[db, app, autoheal] —— 数据库先就绪，自愈守护最后起。
    pub fn start(&self) -> Result<String> {
        let mut args: Vec<OsString> = vec!["start".into()];
        args.extend(CONTAINERS.iter().map(OsString::from));
        self.run_docker(&args)
    }

    /// 停止三容器（保留容器与卷，不删数据）。
    /// 顺序必须是应用 → 自愈 → 数据库：先停库会让仍在运行的应用刷一屏连接错误。
    /// `docker stop` 会按给定顺序逐个停止，所以这里显式逆序排列。
    pub fn stop(&self) -> Result<String> {
        let mut args: Vec<OsString> = vec!["stop".into()];
        args.extend(stop_order().iter().map(OsString::from));
        self.run_docker(&args)
    }

    /// 仅重启应用容器：数据库与自愈守护保持不动，重启后重新加载内存 Store。
    pub fn restart_app(&self) -> Result<String> {
        self.run_docker(&["restart".into(), APP_CONTAINER.into()])
    }

    /// 完整拆除（含网络，不含具名卷）。仅在用户显式确认后由 UI 调用。
    pub fn down(&self) -> Result<String> {
        self.run_compose(&["-f".into(), self.compose_file.clone().into(), "down".into()])
    }

    /// 读取容器日志尾部（非流式，UI 定时刷新即可）。
    pub fn logs(&self, container: &str, tail: usize) -> Result<String> {
        let out = self.run_docker_allow_fail(&[
            OsString::from("logs"),
            OsString::from("--tail"),
            OsString::from(tail.to_string()),
            OsString::from(container),
        ])?;
        if out.status.success() {
            Ok(String::from_utf8_lossy(&out.stdout).to_string())
        } else {
            // 容器尚未创建时 docker logs 会失败；按「空日志」处理，不视为 UI 错误。
            Ok(String::from_utf8_lossy(&out.stderr).to_string())
        }
    }

    /// 采集三容器状态。缺失的容器显式补 `Missing`，UI 不展示空白。
    pub fn container_states(&self) -> Result<Vec<ContainerState>> {
        let args = [
            OsString::from("ps"),
            OsString::from("-a"),
            OsString::from("--format"),
            OsString::from("{{.Names}}\t{{.Status}}"),
        ];
        let out = self.run_docker_allow_fail(&args)?;
        let text = finish(out, format!("docker {}", join_os(&args)))?;
        let mut found: std::collections::HashMap<String, String> = std::collections::HashMap::new();
        for line in text.lines() {
            if let Some((name, status)) = line.split_once('\t') {
                found.insert(name.trim().to_string(), status.trim().to_string());
            }
        }
        Ok(CONTAINERS
            .iter()
            .map(|name| match found.get(*name) {
                Some(s) => ContainerState::parse(name, s),
                None => ContainerState::missing(name),
            })
            .collect())
    }

    /// 是否已创建 app 容器（决定 UI 首按钮是「启动」还是「创建并启动」）。
    pub fn app_exists(&self) -> Result<bool> {
        let args = [
            OsString::from("ps"),
            OsString::from("-a"),
            OsString::from("--filter"),
            OsString::from(format!("name=^{}$", APP_CONTAINER)),
            OsString::from("--format"),
            OsString::from("{{.Names}}"),
        ];
        let out = self.run_docker_allow_fail(&args)?;
        let text = finish(out, format!("docker {}", join_os(&args)))?;
        Ok(text.contains(APP_CONTAINER))
    }

    /// 预构建自定义镜像：仓颉 Linux 镜像需在工具链容器中生成，
    /// 脚本位于 `docker/build-cangjie-docker.sh`。
    pub fn build_image(&self) -> Result<String> {
        let script = self.repo_root.join("docker").join("build-cangjie-docker.sh");
        if !script.is_file() {
            return Err(CoreError::InvalidConfig(format!(
                "缺少构建脚本 {}",
                script.display()
            )));
        }
        let out = self.command("bash")
            .arg(&script)
            .current_dir(&self.repo_root)
            .output()
            .map_err(|e| CoreError::CommandFailed {
                command: format!("bash {}", script.display()),
                code: None,
                stderr: e.to_string(),
            })?;
        finish(out, format!("bash {}", script.display()))
    }

    // ---- 内部 ----

    fn command(&self, bin: &str) -> Command {
        Command::new(bin)
    }

    fn compose_bin(&self) -> (&'static str, &'static [&'static str]) {
        match self.kind {
            ComposeKind::Plugin => ("docker", &["compose"]),
            ComposeKind::Standalone => ("docker-compose", &[]),
        }
    }

    fn run_compose(&self, args: &[OsString]) -> Result<String> {
        let (bin, prefix) = self.compose_bin();
        let mut cmd = self.command(bin);
        cmd.args(prefix).args(args).current_dir(&self.repo_root);
        let out = cmd.output().map_err(|e| CoreError::CommandFailed {
            command: format!("{bin} compose ..."),
            code: None,
            stderr: e.to_string(),
        })?;
        finish(out, format!("{bin} compose {}", join_os(args)))
    }

    fn run_docker(&self, args: &[OsString]) -> Result<String> {
        let out = self.run_docker_allow_fail(args)?;
        finish(out, format!("docker {}", join_os(args)))
    }

    fn run_docker_allow_fail(&self, args: &[OsString]) -> Result<Output> {
        self.command("docker")
            .args(args)
            .current_dir(&self.repo_root)
            .output()
            .map_err(|e| CoreError::CommandFailed {
                command: format!("docker {}", join_os(args)),
                code: None,
                stderr: e.to_string(),
            })
    }
}

fn finish(out: Output, command: String) -> Result<String> {
    if out.status.success() {
        Ok(String::from_utf8_lossy(&out.stdout).to_string())
    } else {
        Err(CoreError::CommandFailed {
            command,
            code: out.status.code(),
            stderr: String::from_utf8_lossy(&out.stderr).to_string(),
        })
    }
}

fn join_os(args: &[OsString]) -> String {
    args.iter()
        .map(|s| s.to_string_lossy().to_string())
        .collect::<Vec<_>>()
        .join(" ")
}

/// compose 文件绝对路径，供 UI 展示「正在操作哪一套栈」。
pub fn compose_display(config: &LauncherConfig) -> String {
    config
        .compose_file
        .strip_prefix(&config.repo_root)
        .unwrap_or(&config.compose_file)
        .to_string_lossy()
        .replace('\\', "/")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compose_display_is_relative_and_posix() {
        let cfg = LauncherConfig {
            repo_root: PathBuf::from("C:/repo"),
            compose_file: PathBuf::from("C:/repo/docker/docker-compose.cangjie.yml"),
            env_file: PathBuf::from("C:/repo/docker/.env"),
            base_url: "http://127.0.0.1:58080".into(),
            app_port: 58080,
            db_port: 15433,
            version: "3.1.0".into(),
        };
        assert_eq!(compose_display(&cfg), "docker/docker-compose.cangjie.yml");
    }

    #[test]
    fn container_list_is_fixed() {
        assert_eq!(CONTAINERS.len(), 3);
        assert!(CONTAINERS.contains(&APP_CONTAINER));
    }

    #[test]
    fn stop_order_shuts_app_before_database() {
        let order = stop_order();
        assert_eq!(order[0], APP_CONTAINER, "应用必须先停，避免数据库连接错误");
        assert_eq!(order[1], CONTAINERS[2], "自愈守护必须在应用之后停，否则会把它拉起");
        assert_eq!(order[2], CONTAINERS[0], "数据库必须最后停");
        assert_eq!(order.len(), CONTAINERS.len(), "三个容器都要停到");
    }
}
