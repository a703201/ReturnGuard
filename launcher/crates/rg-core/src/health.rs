// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
//! `/health` 深探针。手写最小 HTTP/1.1 客户端，避免为一次 GET 引入 reqwest 依赖。
//! 仓颉后端的 /health 含 DB 探针，DB 坏时返回 503 —— 这正是 UI 需要区分的降级态。

use std::{
    io::{Read, Write},
    net::{TcpStream, ToSocketAddrs},
    time::{Duration, Instant},
};

pub const DEFAULT_TIMEOUT_MS: u64 = 3000;
pub const HEALTH_PATH: &str = "/health";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HealthState {
    /// 200，附带探测耗时，便于 UI 展示「就绪 · 42ms」。
    Healthy { elapsed_ms: u128 },
    /// 非 200（含 503 degraded）。
    Degraded { code: u16, elapsed_ms: u128 },
    /// 连接失败 / 超时 / URL 非法。
    Unreachable { reason: String },
}

impl HealthState {
    pub fn label(&self) -> String {
        match self {
            Self::Healthy { elapsed_ms } => format!("服务就绪 · {elapsed_ms}ms"),
            Self::Degraded { code, .. } => format!("服务返回 {code}，请查看日志"),
            Self::Unreachable { .. } => "尚未就绪".to_string(),
        }
    }
}

/// 单次探测，同步阻塞。UI 应在后台线程调用，避免冻结界面。
pub fn probe(base_url: &str, timeout_ms: u64) -> HealthState {
    let started = Instant::now();
    let timeout = Duration::from_millis(timeout_ms);

    let (host, port) = match parse_authority(base_url) {
        Ok(v) => v,
        Err(e) => return HealthState::Unreachable { reason: e },
    };

    let addrs = match (host.as_str(), port).to_socket_addrs() {
        Ok(a) => a.collect::<Vec<_>>(),
        Err(e) => {
            return HealthState::Unreachable {
                reason: e.to_string(),
            }
        }
    };

    let mut stream = None;
    let mut last_err = String::from("无可用地址");
    for addr in addrs {
        match TcpStream::connect_timeout(&addr, timeout) {
            Ok(s) => {
                stream = Some(s);
                break;
            }
            Err(e) => last_err = e.to_string(),
        }
    }
    let mut stream = match stream {
        Some(s) => s,
        None => return HealthState::Unreachable { reason: last_err },
    };

    let _ = stream.set_read_timeout(Some(timeout));
    let _ = stream.set_write_timeout(Some(timeout));

    let request = format!(
        "GET {HEALTH_PATH} HTTP/1.1\r\nHost: {host}:{port}\r\nAccept: */*\r\nConnection: close\r\n\r\n"
    );
    if let Err(e) = stream.write_all(request.as_bytes()) {
        return HealthState::Unreachable {
            reason: e.to_string(),
        };
    }

    let mut buf = Vec::with_capacity(2048);
    if let Err(e) = stream.read_to_end(&mut buf) {
        // 部分服务在 keep-alive 下不会主动关闭；已读到首行时仍可判定。
        if buf.is_empty() {
            return HealthState::Unreachable {
                reason: e.to_string(),
            };
        }
    }

    let text = String::from_utf8_lossy(&buf);
    let code = text
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|s| s.parse::<u16>().ok());

    let elapsed_ms = started.elapsed().as_millis();
    match code {
        Some(200) => HealthState::Healthy { elapsed_ms },
        Some(c) => HealthState::Degraded {
            code: c,
            elapsed_ms,
        },
        None => HealthState::Unreachable {
            reason: "响应缺少 HTTP 状态行".to_string(),
        },
    }
}

fn parse_authority(base_url: &str) -> std::result::Result<(String, u16), String> {
    let rest = base_url
        .strip_prefix("http://")
        .or_else(|| base_url.strip_prefix("https://"))
        .ok_or_else(|| "仅支持 http:// 地址".to_string())?;
    let authority = rest.split('/').next().unwrap_or(rest);
    let (host, port) = authority
        .rsplit_once(':')
        .ok_or_else(|| "地址缺少端口".to_string())?;
    if host.is_empty() {
        return Err("地址缺少主机名".to_string());
    }
    let port = port
        .parse::<u16>()
        .map_err(|_| format!("非法端口: {port}"))?;
    Ok((host.to_string(), port))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn authority_parsing() {
        assert_eq!(
            parse_authority("http://127.0.0.1:58080").unwrap(),
            ("127.0.0.1".to_string(), 58080)
        );
        assert!(parse_authority("ftp://x:1").is_err());
        assert!(parse_authority("http://127.0.0.1").is_err());
    }

    #[test]
    fn unreachable_port_returns_state_not_panic() {
        let state = probe("http://127.0.0.1:1", 200);
        assert!(matches!(state, HealthState::Unreachable { .. }));
    }
}
