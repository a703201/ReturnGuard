# 启动器 GUI / 动作链路验证证据

本目录保存 Linux 启动器的**验证产物**，不是产品代码。

## 文件

- `rg-gtk-screen.png`：Xvfb 虚拟显示下的 GTK 启动器界面（证明 GUI 能真实渲染）。
- `shot-initial.png`：挂载 host `docker.sock` 后的初始状态（三容器全绿）。
- `rg-verify-main.rs`：临时集成验证器源码，直接调用 `apply_action`（GUI 按钮的唯一入口），
  在容器内挂载 `docker.sock` 后依次验证 `refresh` / `logs` / `stop` / `start` / `restart` 链路。

## 复现方式

```bash
# 容器内（Ubuntu 22.04 + GTK4 + docker CLI + compose + Xvfb + xdotool + Rust）
docker run -d --name rg-launcher-e2e \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "<repo>:/project" ubuntu:22.04 sleep 7200

# 源码复制到 overlay 编译（避免 Windows 挂载路径 I/O 瓶颈）
cp -a /project/launcher /root/build/launcher
cd /root/build/launcher && cargo build -p rg-gtk

# GUI 启动（无 docker.sock 时走「Docker 不可用」分支）
DISPLAY=:99 RG_PROJECT_ROOT=/project Xvfb :99 -screen 0 1280x900x24 &
DISPLAY=:99 RG_PROJECT_ROOT=/project target/debug/rg-gtk &

# 动作链路（挂载 sock 后）：把 rg-verify-main.rs 放入临时 crate 编译后
RG_PROJECT_ROOT=/project target/debug/rg-verify refresh
RG_PROJECT_ROOT=/project target/debug/rg-verify logs
RG_PROJECT_ROOT=/project target/debug/rg-verify stop
RG_PROJECT_ROOT=/project target/debug/rg-verify start   # 必须执行以恢复服务
RG_PROJECT_ROOT=/project target/debug/rg-verify restart
```

⚠️ `stop` / `start` / `restart` 会真实操作 host 容器。测试后务必确认三容器 healthy、
`curl http://127.0.0.1:58080/health` 返回 200。

## 未覆盖

- **WinAppSDK runtime staging**：交叉编译刻意跳过（`RG_SKIP_WINAPP_STAGE=1`），
  正式分发须在未跳过 staging 的 Windows + MSVC 环境构建。
- **鼠标点击 GUI 按钮**：无窗口管理器的 Xvfb 下 xdotool 点击不可靠；
  因此改为直接验证按钮调用的 `apply_action` 入口（更本质且可确定性复现）。
