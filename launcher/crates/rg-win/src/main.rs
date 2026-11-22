// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
//! ReturnGuard 启动器 · Windows 版（WinUI 3 via windows-reactor）。
//!
//! 视觉语言沿用 returnguard/web/src/styles/theme.css 的 apple.com 令牌：
//! 零投影、明度分层、单一蓝、字重仅 400/600/700、胶囊与矩形分层、克制动效。
//! 不使用渐变、霓虹、发光球、彩色 emoji 或逐元素弹跳。

use std::{env, thread, time::Duration};

use rg_core::{
    apply_action,
    config::LauncherConfig,
    logs::preview,
    status::{ContainerPhase, ContainerState},
    Action, AppSnapshot,
};
use windows_reactor::*;

// ---------- 设计令牌（与 web/theme.css 浅色令牌同值） ----------
const SURFACE: Color = Color::rgb(255, 255, 255);
const INK: Color = Color::rgb(29, 29, 31);
const INK_2: Color = Color::rgb(81, 81, 84);
const INK_3: Color = Color::rgb(110, 110, 115);
const BLUE: Color = Color::rgb(0, 113, 227);
const SUCCESS: Color = Color::rgb(29, 138, 79);
const WARNING: Color = Color::rgb(160, 90, 0);
const HAIRLINE: Color = Color::argb(20, 0, 0, 0);

const WINDOW_W: f64 = 940.0;
const WINDOW_H: f64 = 690.0;
const POLL_SECONDS: u64 = 3;

struct Launcher {
    config: LauncherConfig,
    snapshot: AppSnapshot,
    busy: Option<Action>,
    notice: Option<(InfoBarSeverity, String)>,
    logs: Option<String>,
    /// 日志面板打开后按轮询周期轻量刷新（每 4 轮约 12 秒），避免用户反复点按钮。
    poll_count: u32,
    reduce_motion: bool,
}

#[derive(Clone, Debug)]
enum Message {
    /// 轮询链：延迟后采集新快照。
    Refresh,
    Snapshot(AppSnapshot),
    Act(Action),
    Done {
        action: Action,
        text: String,
        error: Option<String>,
    },
    AppendLogs(String),
    Dismiss,
}

impl Component for Launcher {
    type Input = LauncherConfig;
    type Message = Message;

    fn create(input: &Self::Input, context: &ComponentContext<Self>) -> Self {
        let reduce_motion = env::var("RG_REDUCE_MOTION")
            .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
            .unwrap_or(false);

        // 启动轮询链。所有阻塞调用都在 Windows 线程池上，主线程只负责渲染。
        context.spawn_background(|_| Message::Refresh);

        Self {
            config: input.clone(),
            snapshot: AppSnapshot::collect(input),
            busy: None,
            notice: None,
            logs: None,
            poll_count: 0,
            reduce_motion,
        }
    }

    fn update(&mut self, message: Self::Message, context: &ComponentContext<Self>) {
        match message {
            Message::Refresh => {
                let config = self.config.clone();
                context.spawn_background(move |_| {
                    thread::sleep(Duration::from_secs(POLL_SECONDS));
                    Message::Snapshot(AppSnapshot::collect(&config))
                });
            }
            Message::Snapshot(snapshot) => {
                self.snapshot = snapshot;
                self.poll_count = self.poll_count.wrapping_add(1);
                if self.logs.is_some() && self.poll_count % 4 == 0 {
                    let config = self.config.clone();
                    context.spawn_background(move |_| {
                        let text = apply_action(Action::Logs, &config)
                            .unwrap_or_else(|err| format!("读取日志失败：{err}"));
                        Message::AppendLogs(text)
                    });
                }
                // 续上下一轮，保持约 3 秒的刷新节奏。
                context.spawn_background(|_| Message::Refresh);
            }
            Message::Act(action) => {
                if self.busy.is_some() && action.is_mutating() {
                    return;
                }
                if action == Action::Refresh {
                    let config = self.config.clone();
                    context.spawn_background(move |_| {
                        Message::Snapshot(AppSnapshot::collect(&config))
                    });
                    return;
                }
                if action == Action::Logs {
                    let config = self.config.clone();
                    context.spawn_background(move |_| {
                        let text = apply_action(Action::Logs, &config)
                            .unwrap_or_else(|err| format!("读取日志失败：{err}"));
                        Message::AppendLogs(text)
                    });
                    return;
                }
                self.busy = Some(action);
                self.notice = None;
                let config = self.config.clone();
                context.spawn_background(move |_| match apply_action(action, &config) {
                    Ok(text) => Message::Done {
                        action,
                        text,
                        error: None,
                    },
                    Err(err) => Message::Done {
                        action,
                        text: String::new(),
                        error: Some(err.to_string()),
                    },
                });
            }
            Message::Done {
                action,
                text,
                error,
            } => {
                self.busy = None;
                self.notice = Some(match error {
                    Some(err) => (
                        InfoBarSeverity::Error,
                        format!("{}未完成：{err}", action.label()),
                    ),
                    None => (
                        InfoBarSeverity::Success,
                        if text.is_empty() {
                            format!("{}完成", action.label())
                        } else {
                            text
                        },
                    ),
                });
                let config = self.config.clone();
                context.spawn_background(move |_| Message::Snapshot(AppSnapshot::collect(&config)));
            }
            Message::AppendLogs(text) => self.logs = Some(text),
            Message::Dismiss => self.notice = None,
        }
    }

    fn view(&self, _input: &Self::Input, context: &mut ViewContext<Self>) -> View {
        context.window_title("ReturnGuard 退货情报站");
        context.window_visuals(
            WindowVisuals::new()
                .backdrop(WindowBackdrop::Mica)
                .theme(WindowTheme::Light)
                .client_size(WINDOW_W, WINDOW_H)
                .constraints(WindowConstraints {
                    min_width: Some(760.0),
                    min_height: Some(560.0),
                    ..Default::default()
                }),
        );

        let (headline, headline_color) = match self.busy {
            // 重建是分钟级阻塞操作，明确告诉用户正在做什么，别只给一个转圈。
            Some(Action::Rebuild) => ("正在重新构建镜像…".to_string(), BLUE),
            Some(Action::Start) => ("正在启动服务…".to_string(), BLUE),
            Some(Action::Stop) => ("正在停止服务…".to_string(), BLUE),
            Some(Action::Restart) => ("正在重启应用…".to_string(), BLUE),
            _ => headline(&self.snapshot),
        };
        let busy = self.busy.is_some();
        let running = self.snapshot.containers.iter().any(|c| c.is_running());

        let header = StackPanel::new().spacing(5.0).children((
            TextBlock::new()
                .text("ReturnGuard")
                .font_size(30.0)
                .font_weight(FontWeight::BOLD)
                .foreground(Brush::Solid(INK)),
            TextBlock::new()
                .text(format!(
                    "退货情报站 · 本地服务 · v{}",
                    self.config.version
                ))
                .font_size(13.0)
                .foreground(Brush::Solid(INK_2)),
            TextBlock::new()
                .text(self.config.base_url.clone())
                .font_size(12.0)
                .foreground(Brush::Solid(BLUE))
                .is_text_selection_enabled(true),
        ));

        // 状态卡：白卡浮在 Mica 画布上，零投影，靠明度差分层。
        let status_card = Border::new()
            .background(Brush::Solid(SURFACE))
            .border_thickness(Thickness::uniform(1.0))
            .border_brush(Brush::Solid(HAIRLINE))
            .corner_radius(CornerRadius::uniform(24.0))
            .padding(Thickness::uniform(22.0))
            .content(
                StackPanel::new().spacing(14.0).children((
                    fade(
                        TextBlock::new()
                            .text(headline)
                            .font_size(24.0)
                            .font_weight(FontWeight::BOLD)
                            .foreground(Brush::Solid(headline_color)),
                        self.reduce_motion,
                    ),
                    TextBlock::new()
                        .text(
                            self.snapshot
                                .docker_error
                                .clone()
                                .unwrap_or_else(|| self.snapshot.health.label()),
                        )
                        .font_size(14.0)
                        .foreground(Brush::Solid(INK_2)),
                    StackPanel::new().spacing(10.0).children((
                        container_row("数据库", self.state_of("rg_cj_opengauss"), self.reduce_motion),
                        container_row("应用服务", self.state_of("rg_cj_app"), self.reduce_motion),
                        container_row("自愈守护", self.state_of("rg_cj_autoheal"), self.reduce_motion),
                    )),
                )),
            );

        let refresh_button = Button::new()
            .min_width(78.0)
            .key_accelerators(KeyAccelerators::new([KeyAccelerator::new(
                AcceleratorKey::R,
                AcceleratorModifiers::Control,
                context.message(Message::Act(Action::Refresh)),
            )]))
            .on_click(context.message(Message::Act(Action::Refresh)))
            .content("刷新");

        // 两行布局：主操作 + 次操作，避免窄窗口下七个按钮挤成一行。
        let primary_actions = StackPanel::new()
            .orientation(Orientation::Horizontal)
            .spacing(9.0)
            .children((
                action_button("启动服务", Action::Start, !running && !busy, true, context),
                action_button("重启应用", Action::Restart, running && !busy, false, context),
                action_button("停止服务", Action::Stop, running && !busy, false, context),
                action_button("打开控制台", Action::OpenBrowser, !busy, false, context),
            ));
        let secondary_actions = StackPanel::new()
            .orientation(Orientation::Horizontal)
            .spacing(9.0)
            .children((
                // Rebuild 会重编仓颉镜像（分钟级），按钮文案直接说明代价，不弹多余确认。
                action_button("重新构建镜像", Action::Rebuild, !busy, false, context),
                action_button("查看日志", Action::Logs, !busy, false, context),
                refresh_button,
            ));

        let progress = ProgressRing::new()
            .width(20.0)
            .height(20.0)
            .is_indeterminate(true)
            .is_active(busy)
            .opacity(if busy { Some(1.0) } else { Some(0.0) });

        let action_bar = StackPanel::new().spacing(10.0).children((
            StackPanel::new()
                .orientation(Orientation::Horizontal)
                .spacing(12.0)
                .children((primary_actions, progress)),
            secondary_actions,
        ));

        let notice = InfoBar::new()
            .title("操作结果")
            .message(
                self.notice
                    .as_ref()
                    .map(|(_, text)| text.clone())
                    .unwrap_or_default(),
            )
            .severity(
                self.notice
                    .as_ref()
                    .map(|(severity, _)| *severity)
                    .unwrap_or(InfoBarSeverity::Informational),
            )
            .is_open(self.notice.is_some())
            .is_closable(true)
            .on_closed(context.message(Message::Dismiss));

        let log_text = self.logs.clone().unwrap_or_else(|| {
            "点击「查看日志」读取 rg_cj_app 最近 200 行；打开后每约 12 秒自动刷新。"
                .to_string()
        });
        let log_panel = Border::new()
            .background(Brush::Solid(SURFACE))
            .border_thickness(Thickness::uniform(1.0))
            .border_brush(Brush::Solid(HAIRLINE))
            .corner_radius(CornerRadius::uniform(18.0))
            .padding(Thickness::uniform(16.0))
            .content(
                StackPanel::new().spacing(8.0).children((
                    TextBlock::new()
                        .text("运行日志")
                        .font_size(15.0)
                        .font_weight(FontWeight::SEMI_BOLD)
                        .foreground(Brush::Solid(INK)),
                    ScrollView::new()
                        .height(210.0)
                        .content(
                            TextBlock::new()
                                .text(preview(&log_text, 6000))
                                .font_size(12.0)
                                .foreground(Brush::Solid(INK_2))
                                .text_wrapping(TextWrapping::NoWrap)
                                .is_text_selection_enabled(true),
                        ),
                )),
            );

        ScrollView::new().content(
            Border::new()
                .padding(Thickness::new(28.0, 24.0, 28.0, 28.0))
                .content(
                    StackPanel::new().spacing(18.0).children((
                        header,
                        status_card,
                        action_bar,
                        notice,
                        log_panel,
                    )),
                ),
        )
    }
}

impl Launcher {
    fn state_of(&self, name: &str) -> Option<&ContainerState> {
        self.snapshot.containers.iter().find(|c| c.name == name)
    }
}

/// 状态标题：区分「尚未启动」「运行中」「需要关注」，不说「未知错误」。
fn headline(snapshot: &AppSnapshot) -> (String, Color) {
    // Docker 本身不可用时，容器状态不可信，必须优先说明，避免误导为「未创建」。
    if snapshot.docker_error.is_some() {
        ("Docker 不可用，请检查服务".to_string(), WARNING)
    } else if snapshot.is_ready() {
        ("服务运行中".to_string(), SUCCESS)
    } else if snapshot.is_degraded() {
        ("服务需要关注".to_string(), WARNING)
    } else if snapshot
        .containers
        .iter()
        .all(|c| c.phase == ContainerPhase::Missing)
    {
        ("服务尚未创建".to_string(), INK_2)
    } else {
        ("服务已停止".to_string(), INK_2)
    }
}

fn container_row(label: &str, state: Option<&ContainerState>, reduce: bool) -> View {
    let (phase, detail) = match state {
        Some(s) => (s.phase, s.detail.clone()),
        None => (ContainerPhase::Missing, "未创建".to_string()),
    };
    let dot_color = match phase {
        ContainerPhase::Running => SUCCESS,
        ContainerPhase::Unhealthy => WARNING,
        ContainerPhase::Stopped => INK_3,
        ContainerPhase::Missing => HAIRLINE,
    };
    let text_color = match phase {
        ContainerPhase::Running => INK,
        ContainerPhase::Unhealthy => WARNING,
        _ => INK_2,
    };
    let text = match state {
        Some(s) => s.label(),
        None => "未创建",
    };

    StackPanel::new()
        .orientation(Orientation::Horizontal)
        .spacing(10.0)
        .children((
            Border::new()
                .width(8.0)
                .height(8.0)
                .corner_radius(CornerRadius::uniform(4.0))
                .background(Brush::Solid(dot_color)),
            TextBlock::new()
                .text(label)
                .width(86.0)
                .font_size(13.0)
                .foreground(Brush::Solid(INK_2)),
            fade(
                TextBlock::new()
                    .text(text)
                    .width(78.0)
                    .font_size(13.0)
                    .font_weight(FontWeight::SEMI_BOLD)
                    .foreground(Brush::Solid(text_color)),
                reduce,
            ),
            TextBlock::new()
                .text(detail)
                .font_size(12.0)
                .foreground(Brush::Solid(INK_3))
                .text_trimming(TextTrimming::CharacterEllipsis),
        ))
}

fn action_button(
    label: &str,
    action: Action,
    enabled: bool,
    accent: bool,
    context: &ViewContext<Launcher>,
) -> View {
    Button::new()
        .min_width(94.0)
        .style(if accent {
            ButtonStyle::Accent
        } else {
            ButtonStyle::Default
        })
        .is_enabled(enabled)
        .on_click(context.message(Message::Act(action)))
        .content(label)
}

/// 克制的淡出转场。reduced motion 下完全关闭，不替换为弹跳。
fn fade<T: LayoutControl + Sized>(view: T, reduce: bool) -> T {
    if reduce {
        view
    } else {
        view.exit_transition(ExitTransition::fade(Duration::from_millis(160)))
    }
}

fn main() {
    let config = match LauncherConfig::discover() {
        Ok(config) => config,
        Err(err) => {
            eprintln!("{err}");
            std::process::exit(1);
        }
    };
    if let Err(err) = App::run_component::<Launcher>(config) {
        eprintln!("启动器无法运行：{err}");
        std::process::exit(1);
    }
}
