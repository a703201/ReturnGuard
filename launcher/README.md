# ReturnGuard 启动器

二进制桌面启动器：一个窗口管理 ReturnGuard 的**仓颉版本地服务**（`docker/docker-compose.cangjie.yml`），提供状态观测与全套操作。不管理、不展示任何旧技术栈。

## 定位与范围

| 项目 | 说明 |
| --- | --- |
| 管理对象 | `rg_cj_opengauss` / `rg_cj_app` / `rg_cj_autoheal` 三容器 |
| 默认地址 | `http://127.0.0.1:58080`（从 `docker/.env` 的 `CJ_APP_PORT` 读取，默认 58080） |
| 操作集合 | 启动、重启应用、停止、**重新构建镜像**、打开控制台、查看日志（打开后约 12 秒自动刷新）、刷新（Ctrl+R） |
| 数据边界 | 只读 `VERSION`、`docker/.env` 的端口键、`docker ps`、`/health`、`docker logs`；**不读取也不展示任何密钥** |
| 破坏性操作 | 停止/重启由按钮显式触发；不提供「删除容器/卷」按钮 |

## 技术栈

- **核心引擎 `rg-core`**：纯 Rust、零外部依赖，负责路径推导、compose 命令封装、容器状态解析、`/health` 深探针（手写最小 HTTP 客户端）、日志读取、浏览器打开。两端共用，操作语义完全一致。
- **Windows `rg-win`**：Rust + 微软官方 [`windows-reactor`](https://crates.io/crates/windows-reactor) 0.100（声明式 WinUI 3）。`windows-reactor-setup` 在构建时 stage Windows App SDK Runtime，产物自包含，用户机器无需预装 WinAppSDK。
- **Linux `rg-gtk`**：Rust + gtk-rs 4（GTK4），跟随系统明暗主题。

Rust 版本要求：`windows-reactor 0.100` 要求 **≥ 1.95**。本机经 USTC 镜像升级至 1.100.0。

## 视觉语言（沿用 `web/src/styles/theme.css`）

```
画布      Mica / #f5f5f7(浅) · #000000(深)
卡面      #ffffff(浅) · #1c1c1e(深)     ← 零投影，靠明度差分层
主文字    #1d1d1f / #f5f5f7
次文字    #515154 / #c7c7cc
弱文字    #6e6e73 / #8e8e93
强调蓝    #0071e3 / #0a84ff             ← 唯一强调色，只用于主按钮与链接
成功/警告 #1d8a4f / #a05a00
字重      400 / 600 / 700（不用 300/500/800）
圆角      交互胶囊 999px · 卡片 24px · 次级卡片 18px
```

刻意避免：彩色渐变、霓虹描边、发光球、装饰光斑、卡片投影堆叠、逐元素弹跳、彩色 emoji。图标用线性/几何元素（状态圆点由 CSS/Border 绘制）。

### 动效（适量、克制）

| 交互 | Windows | Linux | reduced-motion |
| --- | --- | --- | --- |
| 状态文字变化 | WinUI `ExitTransition::fade(160ms)` | CSS `transition 150ms ease-out` | 关闭淡出 / `gtk-enable-animations=false` |
| 按钮反馈 | WinUI 原生按下态 | `:hover` / `:active` 明度变化 | 保留即时反馈，去掉过渡 |
| 处理中 | `ProgressRing` 20px 不确定态 | `Spinner` 20px | 保留（状态指示，非装饰） |
| 轮询 | 3 秒后台采集，主线程只渲染 | 同左 | 不变 |

## 状态矩阵

| 状态 | 触发 | 界面反馈 | 恢复路径 |
| --- | --- | --- | --- |
| 默认 | 已安装容器、健康 200 | 「服务运行中 · Nms」+ 三行绿色状态点 | — |
| 加载 | 首次打开 / 轮询中 | 后台采集，旧状态保持可见，不闪空白 | 自动 |
| 动作进行中 | 点击启动/重建/停止/重启 | 标题显示「正在…」明确文案 + 按钮禁用 + 进度环；重建为分钟级 | 完成/失败后自动刷新状态并提示结果 |
| 未创建 | 三容器均 Missing | 「服务尚未创建」，只「启动服务」可用 | 点击启动（首次创建 + 构建） |
| 已停止 | 容器 Exited，健康不可达 | 「服务已停止」，启动可用、重启/停止禁用 | 点击启动（保留容器运行态） |
| 降级 | 进程在跑但 `/health` 非 200 | 「服务需要关注」+ 警告色 | 查看日志；仓颉后端 503 时 compose autoheal 会兜底重启 |
| 错误 | 命令失败 | InfoBar / 提示条显示「动作未完成：原因」 | 保留现场，可重试或看日志 |
| Docker 不可用 | 命令缺失或守护进程异常（如 E 盘满导致 daemon 只读） | **优先显示「Docker 不可用，请检查服务」**，附具体原因；不误报「尚未创建」 | 修复 Docker 后刷新；所有动作按钮仍可点以查看失败原因 |

## 文件结构

```
launcher/
├── Cargo.toml                  workspace（default-members = rg-core）
├── .cargo/config.toml          仅本目录的 crates.io 镜像（不改全局）
├── crates/
│   ├── rg-core/                跨平台核心引擎（可独立 cargo test）
│   ├── rg-win/                 Windows / WinUI 3 + build.rs（自包含 runtime）
│   └── rg-gtk/                 Linux / GTK4
├── build-windows.ps1
├── build-linux.sh
└── README.md
```

## 构建与运行

### Windows

前置：Rust ≥ 1.95（MSVC target）、Visual Studio Build Tools 的 **C++ 桌面开发** workload、可访问 nuget.org（build.rs 下载 WinAppSDK Runtime 2.4.0）。

```powershell
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1
```

产物 `target/release/rg-win.exe`。运行时 DLL 与 exe 同目录，分发时整体复制 `target/release/`。

### Linux

前置：`libgtk-4-dev pkg-config build-essential`、Rust 工具链。

```bash
sudo apt-get install -y libgtk-4-dev pkg-config build-essential
bash build-linux.sh
```

产物 `target/release/rg-gtk`。

### 核心引擎自检（两端通用，无需 GUI 依赖）

```bash
cargo test -p rg-core
```

### WSL / 容器内构建的性能注意

Windows 挂载路径（如 WSL 的 `/mnt/e/...`、Docker 的 `-v E:/...:/workspace`）上的 cargo I/O 很慢，
WSL 会弹「性能提示」。**先在 Linux 文件系统内编译**再同步产物：

```bash
# 容器内：源码复制到 overlay，而不是直接在挂载目录跑 cargo
cp -a /workspace/launcher /root/build/launcher
cd /root/build/launcher && cargo build -p rg-gtk
```

镜像配置放容器用户目录 `~/.cargo/config.toml`，不要改项目内的 `launcher/.cargo/config.toml`——
挂载目录是双向共享的，容器内删改会直接影响宿主机（本项目曾因此误删本机镜像配置）。

## 验证状态（诚实标注）

| 项目 | 状态 | 证据 / 命令 |
| --- | --- | --- |
| `rg-core` 编译 + 15 项单元测试 | ✅ 已验证 | `cargo test -p rg-core`：15 passed（含项目根定位、Docker 异常状态、浏览器容错、停止顺序） |
| `rg-win` 全量类型/API 检查 | ✅ 已验证 | `RG_SKIP_WINAPP_STAGE=1 cargo check -p rg-win`：通过 |
| `rg-win` exe 链接 | ✅ 已验证 | Linux 容器 + mingw-w64 交叉编译：`RG_SKIP_WINAPP_STAGE=1 cargo build -p rg-win --target x86_64-pc-windows-gnu` 成功；产物 61MB、格式 `pei-x86-64`。证明代码可完整链接为 Windows exe |
| WinAppSDK runtime staging | ❌ 未验证 | build.rs 需从 nuget.org 下载；交叉编译刻意跳过，**该产物不可分发**，正式分发须在未跳过 staging 的 Windows + MSVC 环境构建 |
| `rg-gtk` 真实构建（Linux 容器） | ✅ 已验证 | Ubuntu 22.04 容器 + GTK 4.6.9 + Rust 1.100，`cargo build -p rg-gtk` 成功；产物 55MB，`ldd` 确认链接 libgtk-4.so.1 / libglib-2.0.so.0。全程在容器 Linux overlay 上编译（避免 Windows 挂载路径 I/O 瓶颈） |
| `rg-gtk` 真实 GUI 运行 | ✅ 已验证 | Xvfb 虚拟显示 + `RG_PROJECT_ROOT=/project` 启动成功：进程存活、日志零错误、截图确认中文无乱码、7 按钮全可见、状态卡片正常。并由此发现 GTK CSS 不支持 `@media`，已改 Rust 侧读 `gtk4::Settings` |
| 真实启动/停止/日志按钮链路 | ❌ 未验证 | GUI 已能显示，但容器内无 docker 命令（走 Docker 不可用分支）；真正点击启停需在装有 Docker 的桌面上人工验收 |

**CI 分工**（`.github/workflows/ci.yml` 六路并行）：静态门禁（仓库根 `python scripts/ci_checks.py`，7 项）、
版本一致性、`rg-core` 测试、前端构建、**WinUI 真实构建**、**GTK4 真实构建**。
本地不具备的链接器 / 系统库已用 Linux 容器 + mingw-w64 / GTK4 补齐并验证；CI 仍保留
windows-latest 的原生 MSVC 构建（含 WinAppSDK staging），作为正式分发的唯一可信来源。

`windows-reactor` 的 build script 与 runtime staging 在具备 VS Build Tools 的 Windows 机器上应可直接工作；若 nuget.org 不可达，需预置 WinAppSDK Runtime 包到 `%LOCALAPPDATA%\windows-reactor-setup\temp`。
CI 只验证编译链接时设 `RG_SKIP_WINAPP_STAGE=1` 跳过 staging——**这种产物不可分发**。正式发布务必保持默认。

## 可访问性

- 所有操作均为原生按钮，Tab 可达、Enter/Space 激活，焦点由系统绘制。
- 刷新按钮绑定 Ctrl+R；Windows 版另有键盘加速器支持。
- 状态不只靠颜色区分：同时有文字标签（运行中 / 运行异常 / 已停止 / 未创建）。
- 提示条说明「发生了什么 + 如何恢复」，错误保留现场不自动重试。
- 触控/点击目标：按钮最小宽 94 DIP，高度遵循平台原生控件。
- 遵循 `RG_REDUCE_MOTION=1` 关闭非必要动效；GTK 版另遵循系统 reduced-motion。
- 文本缩放：GTK 版布局使用相对间距与 ScrolledWindow，放大后不截断主要信息；WinUI 版使用 WinUI 原生文本缩放。

## 数据事实来源

- 版本：`VERSION`（与 workspace `Cargo.toml`、`package.json` 的 3.1.0 一致）
- 端口：`docker/.env` → `CJ_APP_PORT` / `CJ_DB_PORT`
- 容器：`docker/docker-compose.cangjie.yml` 的 `container_name`
- 健康：`/health`（仓颉后端深探针，DB 故障时返回 503）
- 不硬编码任何端口或容器名（除 compose 声明的常量集中在 `rg-core/config.rs`）
