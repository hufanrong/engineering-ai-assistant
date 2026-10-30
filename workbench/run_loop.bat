@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   繁工AI - WORKbuddy 自动循环通道
echo   每 5 分钟检查 GitHub，有新代码就拉取、重启、自测、回传报告
echo ============================================================
echo.

rem 找 Python：优先项目内虚拟环境，其次系统 python
set "PY=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%~dp0venv\Scripts\python.exe"  set "PY=%~dp0venv\Scripts\python.exe"

"%PY%" --version >nul 2>&1
if errorlevel 1 (
  echo [错误] 找不到 Python。请先运行 install.bat 安装依赖，或确认 python 已加入 PATH。
  pause
  exit /b 1
)

echo [信息] 使用 Python: %PY%
echo [信息] 仓库目录: %~dp0..
echo.
echo 提示：第一次运行建议先跑 --once 确认一条完整链路：
echo     "%PY%" "%~dp0tools\wb_loop.py" --once
echo.
echo 现在启动常驻循环。关闭此窗口即停止。
echo ============================================================
echo.

"%PY%" "%~dp0tools\wb_loop.py" --interval 300

echo.
echo [信息] 循环已退出。
pause
