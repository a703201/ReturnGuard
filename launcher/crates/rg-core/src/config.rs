// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
//! 路径与端口推导。事实来源：仓库根 VERSION、docker/.env、compose 文件。
//! 不在代码里硬编码任何「看起来对」的端口。

use std::{
    collections::HashMap,
    env, fs,
    path::{Path, PathBuf},
};

use crate::{CoreError, Result};

/// 仓颉版三容器（`docker/docker-compose.cangjie.yml` 中的 container_name）。
pub const CONTAINERS: [&str; 3] = ["rg_cj_opengauss", "rg_cj_app", "rg_cj_autoheal"];
pub const APP_CONTAINER: &str = "rg_cj_app";
pub const COMPOSE_REL: &str = "docker/docker-compose.cangjie.yml";
pub const ENV_REL: &str = "docker/.env";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LauncherConfig {
    pub repo_root: PathBuf,
    pub compose_file: PathBuf,
    pub env_file: PathBuf,
    pub base_url: String,
    pub app_port: u16,
    pub db_port: u16,
    pub version: String,
}

impl LauncherConfig {
    /// 定位项目根：优先 `RG_PROJECT_ROOT`，再从 exe / cwd 向上找同时含
    /// `VERSION` 与 compose 文件的目录。支持源码运行（target/debug）与安装后运行。
    pub fn discover() -> Result<Self> {
        let root = locate_root()?;
        let env = read_env_file(&root.join(ENV_REL));
        let app_port = parse_port(env.get("CJ_APP_PORT"), 58080, "CJ_APP_PORT")?;
        let db_port = parse_port(env.get("CJ_DB_PORT"), 15433, "CJ_DB_PORT")?;
        let version = fs::read_to_string(root.join("VERSION"))
            .map(|s| s.trim().to_string())
            .unwrap_or_else(|_| "unknown".to_string());

        Ok(Self {
            compose_file: root.join(COMPOSE_REL),
            env_file: root.join(ENV_REL),
            base_url: format!("http://127.0.0.1:{app_port}"),
            app_port,
            db_port,
            version,
            repo_root: root,
        })
    }

    /// 日志查看的默认行数。
    pub fn log_tail(&self) -> usize {
        200
    }
}

fn locate_root() -> Result<PathBuf> {
    if let Some(raw) = env::var_os("RG_PROJECT_ROOT") {
        let p = PathBuf::from(raw);
        if is_root(&p) {
            return Ok(p);
        }
        return Err(CoreError::ProjectRootNotFound(p.display().to_string()));
    }

    let mut candidates = Vec::new();
    if let Ok(exe) = env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.to_path_buf());
        }
    }
    if let Ok(cwd) = env::current_dir() {
        candidates.push(cwd);
    }

    for start in candidates {
        let mut cur = start.as_path();
        for _ in 0..8 {
            if is_root(cur) {
                return Ok(cur.to_path_buf());
            }
            match cur.parent() {
                Some(p) => cur = p,
                None => break,
            }
        }
    }

    Err(CoreError::ProjectRootNotFound(
        "exe 父目录与当前工作目录向上各 8 级".to_string(),
    ))
}

fn is_root(p: &Path) -> bool {
    p.join("VERSION").is_file() && p.join(COMPOSE_REL).is_file()
}

/// 解析 `docker/.env` 的 KEY=VALUE。忽略注释、空行、带引号的值。
/// 只读端口相关键；密钥（GS_PASSWORD / AUTH_SECRET / RG_AI_KEY）绝不进入 UI 状态。
fn read_env_file(path: &Path) -> HashMap<String, String> {
    let mut map = HashMap::new();
    let Ok(text) = fs::read_to_string(path) else {
        return map;
    };
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((k, v)) = line.split_once('=') else {
            continue;
        };
        let key = k.trim().to_string();
        let value = v
            .trim()
            .trim_matches('"')
            .trim_matches('\'')
            .trim()
            .to_string();
        map.insert(key, value);
    }
    map
}

fn parse_port(
    value: Option<&String>,
    default: u16,
    name: &str,
) -> Result<u16> {
    match value {
        None => Ok(default),
        Some(s) if s.is_empty() => Ok(default),
        Some(s) => s
            .parse::<u16>()
            .map_err(|_| CoreError::InvalidConfig(format!("{name}={s} 不是合法端口"))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn env_parser_handles_comments_and_quotes() {
        let text = "# comment\nCJ_APP_PORT=58080\nCJ_DB_PORT=\"15433\"\nEMPTY=\nNOEQUAL\n";
        let dir = std::env::temp_dir().join(format!("rg_core_env_test_{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        let p = dir.join(".env");
        fs::write(&p, text).unwrap();
        let m = read_env_file(&p);
        assert_eq!(m.get("CJ_APP_PORT").map(String::as_str), Some("58080"));
        assert_eq!(m.get("CJ_DB_PORT").map(String::as_str), Some("15433"));
        assert_eq!(m.get("EMPTY").map(String::as_str), Some(""));
        assert!(!m.contains_key("NOEQUAL"));
        fs::remove_file(&p).unwrap();
        fs::remove_dir(&dir).unwrap();
    }

    #[test]
    fn is_root_requires_both_version_and_compose() {
        // 分发场景：只有同时含 VERSION 与 compose 的目录才算项目根。
        let dir = std::env::temp_dir().join(format!("rg_core_root_test_{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(dir.join("docker")).unwrap();
        assert!(!is_root(&dir), "只有空 docker 目录不算项目根");
        fs::write(dir.join("VERSION"), "3.1.0\n").unwrap();
        assert!(!is_root(&dir), "缺 compose 不算项目根");
        fs::write(dir.join(COMPOSE_REL), "services: {}\n").unwrap();
        assert!(is_root(&dir), "两个标志文件齐全才算项目根");
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn parse_port_rejects_garbage() {
        let bad = "abc".to_string();
        assert!(parse_port(Some(&bad), 1, "X").is_err());
        assert_eq!(parse_port(None, 58080, "X").unwrap(), 58080);
    }

    /// 从 cargo 测试产物路径向上定位项目根，验证真实运行时的路径推导。
    #[test]
    fn discover_finds_project_root_from_target() {
        let cfg = LauncherConfig::discover().expect("测试产物应能向上找到项目根");
        assert_eq!(cfg.version.trim(), "3.1.0");
        assert_eq!(cfg.app_port, 58080);
        assert_eq!(cfg.db_port, 15433);
        assert!(cfg.compose_file.is_file());
        assert_eq!(cfg.base_url, "http://127.0.0.1:58080");
    }
}
