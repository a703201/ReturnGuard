// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
//! ReturnGuard 启动器 · Linux 版（GTK4）。
//! 与 Windows 版共用 rg-core 与同一套 apple.com 设计令牌：
//! 零投影、明度分层、单一蓝、字重仅 400/600/700、克制动效、reduced-motion。

use std::{
    cell::Cell,
    env,
    rc::Rc,
    sync::mpsc::{self, Receiver, Sender, TryRecvError},
    thread,
    time::Duration,
};

use gtk4::{
    glib::{self, ControlFlow},
    prelude::*,
    Application, ApplicationWindow, Box as GBox, Button, Label, Orientation, ScrolledWindow,
    Spinner, TextView,
};
use rg_core::{
    apply_action,
    config::LauncherConfig,
    logs::preview,
    status::ContainerPhase,
    Action, AppSnapshot,
};

const APP_ID: &str = "cn.returnguard.launcher";
const POLL_SECONDS: u64 = 3;

/// 与 web/theme.css 同值的浅色令牌。深色/减弱动效由 Rust 读 gtk4::Settings 切换，
/// GTK 的 CSS 解析器不支持 @media（4.6 会静默忽略，见 apply_system_preferences）。
const CSS: &str = r#"
window.returnguard {
  background: #f5f5f7;
  font-family: -apple-system, "SF Pro Text", "Noto Sans CJK SC", "PingFang SC", system-ui, sans-serif;
  font-size: 14px;
}
.window-inner { margin: 24px 28px; }
.rg-title { font-size: 30px; font-weight: 700; color: #1d1d1f; }
.rg-sub { font-size: 13px; color: #515154; }
.rg-url { font-size: 12px; color: #0071e3; }
.rg-card {
  background: #ffffff;
  border: 1px solid rgba(0,0,0,0.07);
  border-radius: 24px;
  padding: 22px;
}
.rg-card-soft {
  background: #ffffff;
  border: 1px solid rgba(0,0,0,0.07);
  border-radius: 18px;
  padding: 16px;
}
.rg-headline { font-size: 24px; font-weight: 700; color: #1d1d1f; }
.rg-headline.running { color: #1d8a4f; }
.rg-headline.degraded { color: #a05a00; }
.rg-headline.busy { color: #0071e3; }
.rg-health { font-size: 14px; color: #515154; }
.rg-row-label { min-width: 86px; color: #515154; font-size: 13px; }
.rg-row-state { min-width: 78px; font-weight: 600; font-size: 13px; }
.rg-row-state.running { color: #1d1d1f; }
.rg-row-state.degraded { color: #a05a00; }
.rg-row-detail { color: #6e6e73; font-size: 12px; }
.dot { min-width: 8px; min-height: 8px; border-radius: 4px; background: #6e6e73; }
.dot.running { background: #1d8a4f; }
.dot.degraded { background: #a05a00; }
.dot.missing { background: rgba(0,0,0,0.08); }
button.rg {
  border-radius: 999px;
  padding: 7px 16px;
  font-weight: 600;
  background: #ffffff;
  color: #1d1d1f;
  border: 1px solid rgba(0,0,0,0.16);
  transition: background 150ms ease-out, color 150ms ease-out;
}
button.rg:hover { background: #e8e8ed; }
button.rg:active { background: #dcdce1; }
button.rg.accent { background: #0071e3; color: #ffffff; border-color: #0071e3; }
button.rg.accent:hover { background: #0077ed; }
button.rg.accent:active { background: #0066cc; }
.rg-notice { font-size: 13px; color: #6e6e73; }
.rg-notice.ok { color: #1d8a4f; }
.rg-notice.error { color: #c0392b; }
.rg-log { font-family: "SF Mono", "Cascadia Code", Consolas, monospace; font-size: 12px; color: #515154; }
.log-view { min-height: 190px; }
spinner { min-width: 20px; min-height: 20px; }

"#;

/// GTK 的 CSS 解析器不支持 @media；深色与减弱动效必须由 Rust 侧读取
/// gtk4::Settings 后切换 class 实现（见 apply_system_preferences）。
const CSS_DARK: &str = r#"
window.returnguard { background: #000000; }
.rg-title, .rg-headline, .rg-row-state.running { color: #f5f5f7; }
.rg-sub, .rg-health, .rg-log, .rg-row-label, .rg-row-detail { color: #c7c7cc; }
.rg-card, .rg-card-soft { background: #1c1c1e; border-color: rgba(255,255,255,0.1); }
.rg-url { color: #0a84ff; }
.rg-headline.running, .rg-notice.ok { color: #30d158; }
.rg-headline.degraded, .rg-row-state.degraded, .dot.degraded { color: #ff9f0a; }
.dot.degraded { background: #ff9f0a; }
.dot.missing { background: rgba(255,255,255,0.1); }
button.rg { background: #1c1c1e; color: #f5f5f7; border-color: rgba(255,255,255,0.22); }
button.rg:hover { background: #2c2c2e; }
button.rg.accent { background: #0a84ff; border-color: #0a84ff; color: #1d1d1f; }
"#;
const CSS_REDUCED_MOTION: &str = "button.rg { transition: none; }";

/// 读取系统偏好，把深色 / 减弱动效作为独立 CSS provider 叠加。
/// 不再依赖 @media —— GTK 4.6 会静默忽略它。
fn apply_system_preferences(window: &ApplicationWindow) {
    let Some(settings) = gtk4::Settings::default() else {
        return;
    };
    let screen = gtk4::prelude::RootExt::display(window);

    if settings.is_gtk_application_prefer_dark_theme() {
        let provider = gtk4::CssProvider::new();
        provider.load_from_data(CSS_DARK);
        gtk4::style_context_add_provider_for_display(
            &screen,
            &provider,
            gtk4::STYLE_PROVIDER_PRIORITY_APPLICATION,
        );
    }
    if !settings.is_gtk_enable_animations() {
        let provider = gtk4::CssProvider::new();
        provider.load_from_data(CSS_REDUCED_MOTION);
        gtk4::style_context_add_provider_for_display(
            &screen,
            &provider,
            gtk4::STYLE_PROVIDER_PRIORITY_APPLICATION,
        );
    }
}

#[derive(Debug, Clone)]
enum Message {
    Snapshot(AppSnapshot),
    Busy(Option<Action>),
    Notice { ok: bool, text: String },
    Logs(String),
}

fn main() -> glib::ExitCode {
    let app = Application::builder().application_id(APP_ID).build();
    app.connect_activate(build_ui);
    app.run()
}

fn build_ui(app: &Application) {
    load_css();

    let config = match LauncherConfig::discover() {
        Ok(config) => config,
        Err(err) => {
            eprintln!("{err}");
            return;
        }
    };

    let window = ApplicationWindow::builder()
        .application(app)
        .title("ReturnGuard 退货情报站")
        .default_width(940)
        .default_height(690)
        .build();
    apply_system_preferences(&window);
    window.add_css_class("returnguard");

    let root = GBox::builder()
        .orientation(Orientation::Vertical)
        .spacing(18)
        .build();
    root.add_css_class("window-inner");

    // ---- 头部 ----
    let title = Label::builder()
        .label("ReturnGuard")
        .css_classes(["rg-title"])
        .xalign(0.0)
        .build();
    let subtitle = Label::builder()
        .label(format!(
            "退货情报站 · 本地服务 · v{}",
            config.version
        ))
        .css_classes(["rg-sub"])
        .xalign(0.0)
        .build();
    let url = Label::builder()
        .label(config.base_url.clone())
        .css_classes(["rg-url"])
        .xalign(0.0)
        .selectable(true)
        .build();
    let header = GBox::builder()
        .orientation(Orientation::Vertical)
        .spacing(5)
        .build();
    header.append(&title);
    header.append(&subtitle);
    header.append(&url);
    root.append(&header);

    // ---- 状态卡 ----
    let headline = Label::builder()
        .label("正在读取状态")
        .css_classes(["rg-headline"])
        .xalign(0.0)
        .build();
    let health = Label::builder()
        .label("正在探测服务")
        .css_classes(["rg-health"])
        .xalign(0.0)
        .build();
    let state_card = GBox::builder()
        .orientation(Orientation::Vertical)
        .spacing(14)
        .build();
    state_card.add_css_class("rg-card");
    state_card.append(&headline);
    state_card.append(&health);

    let mut rows = Vec::new();
    for (name, label_text) in [
        ("rg_cj_opengauss", "数据库"),
        ("rg_cj_app", "应用服务"),
        ("rg_cj_autoheal", "自愈守护"),
    ] {
        let row = GBox::builder()
            .orientation(Orientation::Horizontal)
            .spacing(10)
            .build();
        let dot = Label::builder().label("").build();
        dot.set_width_request(8);
        dot.set_height_request(8);
        dot.add_css_class("dot");
        let name_label = Label::builder()
            .label(label_text)
            .css_classes(["rg-row-label"])
            .xalign(0.0)
            .build();
        let state_label = Label::builder()
            .label("未创建")
            .css_classes(["rg-row-state"])
            .xalign(0.0)
            .build();
        let detail_label = Label::builder()
            .label("")
            .css_classes(["rg-row-detail"])
            .xalign(0.0)
            .hexpand(true)
            .build();
        row.append(&dot);
        row.append(&name_label);
        row.append(&state_label);
        row.append(&detail_label);
        state_card.append(&row);
        rows.push((name.to_string(), dot, state_label, detail_label));
    }
    root.append(&state_card);

    // ---- 操作按钮 ----
    // glib 0.20 已移除 MainContext::channel：用 std mpsc + timeout_add_local
    // 在主线程轮询消息队列，Sender 可安全跨线程克隆到后台任务。
    let (sender, receiver): (Sender<Message>, Receiver<Message>) = mpsc::channel();

    let actions = GBox::builder()
        .orientation(Orientation::Horizontal)
        .spacing(9)
        .build();

    let mut buttons: Vec<(Action, Button)> = Vec::new();
    for (label, action, accent) in [
        ("启动服务", Action::Start, true),
        ("重启应用", Action::Restart, false),
        ("停止服务", Action::Stop, false),
        ("打开控制台", Action::OpenBrowser, false),
        // Rebuild 会重编仓颉镜像（分钟级），文案直接说明代价，不弹多余确认。
        ("重新构建镜像", Action::Rebuild, false),
        ("查看日志", Action::Logs, false),
        ("刷新", Action::Refresh, false),
    ] {
        let button = Button::builder().label(label).build();
        button.add_css_class("rg");
        if accent {
            button.add_css_class("accent");
        }
        let sender = sender.clone();
        let config = config.clone();
        let act = action;
        button.connect_clicked(move |_| {
            let sender = sender.clone();
            let config = config.clone();
            thread::spawn(move || {
                // 日志走专用通道，避免把 200 行文本塞进提示条。
                if act == Action::Logs {
                    let text = apply_action(Action::Logs, &config)
                        .unwrap_or_else(|err| format!("读取日志失败：{err}"));
                    let _ = sender.send(Message::Logs(text));
                    return;
                }
                // 刷新立即采集，不等下一轮 3 秒轮询。
                if act == Action::Refresh {
                    let _ = sender.send(Message::Snapshot(AppSnapshot::collect(&config)));
                    return;
                }

                if act.is_mutating() {
                    let _ = sender.send(Message::Busy(Some(act)));
                }
                let result = apply_action(act, &config);
                if act.is_mutating() {
                    let _ = sender.send(Message::Busy(None));
                }
                match result {
                    Ok(text) => {
                        let _ = sender.send(Message::Notice {
                            ok: true,
                            text: if text.is_empty() {
                                format!("{}完成", act.label())
                            } else {
                                text
                            },
                        });
                        if act.is_mutating() {
                            let _ = sender.send(Message::Snapshot(AppSnapshot::collect(&config)));
                        }
                    }
                    Err(err) => {
                        let _ = sender.send(Message::Notice {
                            ok: false,
                            text: format!("{}未完成：{err}", act.label()),
                        });
                    }
                }
            });
        });
        actions.append(&button);
        buttons.push((action, button));
    }

    let spinner = Spinner::new();
    let action_bar = GBox::builder()
        .orientation(Orientation::Horizontal)
        .spacing(12)
        .build();
    action_bar.append(&actions);
    action_bar.append(&spinner);
    root.append(&action_bar);

    let notice = Label::builder()
        .label("")
        .css_classes(["rg-notice"])
        .xalign(0.0)
        .build();
    root.append(&notice);

    // ---- 日志区（按需加载） ----
    let log_card = GBox::builder()
        .orientation(Orientation::Vertical)
        .spacing(8)
        .build();
    log_card.add_css_class("rg-card-soft");
    let log_heading = Label::builder()
        .label("运行日志")
        .css_classes(["rg-sub"])
        .xalign(0.0)
        .build();
    let log_view = TextView::builder()
        .editable(false)
        .css_classes(["rg-log"])
        .build();
    // 不显式设 WrapMode::None：该变体受 pango v1_56 feature 门控，
    // 而 Ubuntu 22.04 自带 pango 1.50 / GTK 4.6。默认 Word 换行更适合日志阅读。
    log_view.buffer().set_text(
        "点击「查看日志」读取 rg_cj_app 最近 200 行；打开后每约 12 秒自动刷新。",
    );
    let log_scroll = ScrolledWindow::builder()
        .min_content_height(190)
        .child(&log_view)
        .build();
    log_scroll.add_css_class("log-view");
    log_card.append(&log_heading);
    log_card.append(&log_scroll);
    root.append(&log_card);

    let scroll_root = ScrolledWindow::builder().child(&root).build();
    window.set_child(Some(&scroll_root));

    // ---- 消息通道：所有 UI 更新都在主线程 ----
    let headline_weak = headline.clone();
    let health_weak = health.clone();
    let notice_weak = notice.clone();
    let log_view_weak = log_view.clone();
    let spinner_weak = spinner.clone();
    let buttons_weak = buttons.clone();
    let sender_for_poll = sender.clone();
    let config_for_poll = config.clone();
    // 日志面板打开后轻量自动刷新（每 4 轮约 12 秒），Cell 只在主线程访问。
    let logs_open = Rc::new(Cell::new(false));
    let poll_count = Rc::new(Cell::new(0u32));
    let logs_open_rx = logs_open.clone();
    let poll_count_rx = poll_count.clone();
    let sender_for_logs = sender.clone();
    let config_for_logs = config.clone();

    glib::timeout_add_local(Duration::from_millis(100), move || {
        // 一次 tick 内排空队列，避免高频消息时 UI 落后；主线程独占 receiver。
        loop {
            let message = match receiver.try_recv() {
                Ok(m) => m,
                Err(TryRecvError::Empty) | Err(TryRecvError::Disconnected) => break,
            };
            match message {
                Message::Snapshot(snapshot) => {
                    let count = poll_count_rx.get().wrapping_add(1);
                    poll_count_rx.set(count);
                    if logs_open_rx.get() && count % 4 == 0 {
                        let sender = sender_for_logs.clone();
                        let config = config_for_logs.clone();
                        thread::spawn(move || {
                            let text = apply_action(Action::Logs, &config)
                                .unwrap_or_else(|err| format!("读取日志失败：{err}"));
                            let _ = sender.send(Message::Logs(text));
                        });
                    }

                    let (text, class) = if snapshot.docker_error.is_some() {
                        ("Docker 不可用，请检查服务", "degraded")
                    } else if snapshot.is_ready() {
                        ("服务运行中", "running")
                    } else if snapshot.is_degraded() {
                        ("服务需要关注", "degraded")
                    } else if snapshot.containers.iter().all(|c| c.phase == ContainerPhase::Missing) {
                        ("服务尚未创建", "")
                    } else {
                        ("服务已停止", "")
                    };
                    headline_weak.set_label(text);
                    headline_weak.set_css_classes(&["rg-headline", class]);
                    let detail = snapshot
                        .docker_error
                        .clone()
                        .unwrap_or_else(|| snapshot.health.label());
                    health_weak.set_label(&detail);

                    for (name, dot, state_label, detail_label) in &rows {
                        if let Some(state) = snapshot.containers.iter().find(|c| c.name == *name) {
                            let phase_class = match state.phase {
                                ContainerPhase::Running => "running",
                                ContainerPhase::Unhealthy => "degraded",
                                ContainerPhase::Missing => "missing",
                                ContainerPhase::Stopped => "",
                            };
                            dot.set_css_classes(&["dot", phase_class]);
                            state_label.set_label(state.label());
                            state_label.set_css_classes(&["rg-row-state", phase_class]);
                            detail_label.set_label(&state.detail);
                        }
                    }

                    let running = snapshot.containers.iter().any(|c| c.is_running());
                    for (action, button) in &buttons_weak {
                        let enabled = match action {
                            Action::Start => !running,
                            Action::Restart | Action::Stop => running,
                            _ => true,
                        };
                        button.set_sensitive(enabled);
                    }
                }
                Message::Busy(active) => {
                    spinner_weak.set_spinning(active.is_some());
                    // 分钟级操作给出明确文案；3 秒后的 Snapshot 会恢复真实状态。
                    let title = match active {
                        Some(Action::Rebuild) => Some("正在重新构建镜像…"),
                        Some(Action::Start) => Some("正在启动服务…"),
                        Some(Action::Stop) => Some("正在停止服务…"),
                        Some(Action::Restart) => Some("正在重启应用…"),
                        _ => None,
                    };
                    if let Some(t) = title {
                        headline_weak.set_label(t);
                        headline_weak.set_css_classes(&["rg-headline", "busy"]);
                    }
                    for (action, button) in &buttons_weak {
                        if action.is_mutating() {
                            button.set_sensitive(active.is_none());
                        }
                    }
                }
                Message::Notice { ok, text } => {
                    notice_weak.set_label(&text);
                    notice_weak.set_css_classes(&["rg-notice", if ok { "ok" } else { "error" }]);
                }
                Message::Logs(text) => {
                    logs_open_rx.set(true);
                    log_view_weak.buffer().set_text(&preview(&text, 6000));
                }
            }
        }
        ControlFlow::Continue
    });

    // ---- 轮询线程：采集在后台，渲染在主线程 ----
    thread::spawn(move || loop {
        let snapshot = AppSnapshot::collect(&config_for_poll);
        let _ = sender_for_poll.send(Message::Snapshot(snapshot));
        thread::sleep(Duration::from_secs(POLL_SECONDS));
    });

    window.present();
}

fn load_css() {
    let provider = gtk4::CssProvider::new();
    // load_from_string 受 gtk v4_12 feature 门控；Ubuntu 22.04 是 GTK 4.6。
    // load_from_data 语义等价且无版本要求。
    provider.load_from_data(CSS);
    if let Some(display) = gtk4::gdk::Display::default() {
        gtk4::style_context_add_provider_for_display(
            &display,
            &provider,
            gtk4::STYLE_PROVIDER_PRIORITY_APPLICATION,
        );
    }

    if env::var("RG_REDUCE_MOTION")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
    {
        if let Some(settings) = gtk4::Settings::default() {
            settings.set_gtk_enable_animations(false);
        }
    }
}
