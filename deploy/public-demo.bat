@echo off
REM ============================================================
REM  ReturnGuard · 公网体验一键拉起（Cloudflare Named Tunnel）
REM  固定地址: https://rg.a703201sworld.top  （测试账号 demo / demo123）
REM  注意: 本机 Windows 非提权进程无法绑定 0.0.0.0 低端口，
REM        故 app 绑 127.0.0.1:65432，由 cloudflared 反代出公网。
REM ============================================================
REM 路径可经环境变量覆盖（P2-11）；PY 默认用当前用户下的受管 venv，去除硬编码本机用户名。
if not defined PY set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not defined CF set "CF=D:\cloudflared.exe"
if not defined CFG set "CFG=D:\Codes\Project\跨境\returnguard\deploy\rg-tunnel.yml"
set DEMO=D:\Codes\Project\跨境\returnguard\demo

echo [1/2] 启动 ReturnGuard app (127.0.0.1:65432) ...
start "" "%PY%" -m uvicorn main:app --host 127.0.0.1 --port 65432
timeout /t 5 >nul

echo [2/2] 启动 Cloudflare named tunnel (rg.a703201sworld.top) ...
start "" "%CF%" tunnel --config "%CFG%" run rg

echo.
echo ============================================================
echo   固定公网地址:  https://rg.a703201sworld.top
echo   测试账号:      demo / demo123
echo ============================================================
echo 提示: 关闭此窗口会终止 app 与隧道进程。
echo       重开机后双击本文件即可一键恢复。
echo.
pause
