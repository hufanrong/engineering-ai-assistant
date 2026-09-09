@echo off
chcp 65001 >nul
title 繁工AI 工作台 - 智能启动
rem ============================================
rem  繁工AI 本地解析工作台 - 智能启动脚本 v1.0
rem  先检测 8756 端口：已有服务 → 直接打开网页
rem  未运行 → 启动服务并打开网页
rem  解决"服务已运行再点快捷方式报端口占用、窗口一闪而过"
rem ============================================
setlocal enabledelayedexpansion
set PORT=8756

rem ---- 检测端口占用 ----
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
    set FOUND=1
)

if "!FOUND!"=="1" (
    echo [信息] 工作台已在运行（端口 %PORT%），直接打开网页...
    start http://127.0.0.1:%PORT%
    exit /b 0
)

rem ---- 未运行：启动服务 ----
echo [信息] 工作台未运行，正在启动（端口 %PORT%）...
cd /d "%~dp0"

rem 优先使用 venv 中的 Python，其次系统 Python
set PY=python
if exist "%~dp0venv\Scripts\python.exe" (
    set "PY=%~dp0venv\Scripts\python.exe"
)

rem 后台启动并记录日志
start "繁工AI工作台" cmd /c ""%PY%" start.py >> "%~dp0updates\start.log" 2>&1"

rem 等待服务就绪后打开网页
echo [信息] 等待服务启动（最多 20 秒）...
set WAIT=0
:waitloop
timeout /t 1 /nobreak >nul
set /a WAIT+=1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
    echo [完成] 服务已就绪，打开网页...
    start http://127.0.0.1:%PORT%
    exit /b 0
)
if !WAIT! LSS 20 goto waitloop

echo [警告] 20 秒内未检测到服务，请查看 updates\start.log
pause
