@echo off
chcp 65001 >nul
title Fangong AI Workbench
setlocal enabledelayedexpansion

rem ============================================================
rem  v0.1.221 - open the workbench, start it if not running.
rem
rem  Why the comments here are ASCII-only:
rem  cmd reads a .bat byte-by-byte. With a UTF-8 BOM the first line
rem  becomes "?@echo off" and is executed as a garbage command, so
rem  echo-off never takes effect and every line gets echoed. Combined
rem  with `chcp 65001`, multi-byte (Chinese) `rem` lines then lose
rem  sync and get split into bogus commands. Result: the window
rem  flashes by, no address is shown, browser may never open.
rem  Verified on this machine 2026-11-10.
rem
rem  Chinese below appears only inside `echo`, which renders
rem  correctly under 65001. Verified.
rem ============================================================

set PORT=8756
set URL=http://127.0.0.1:%PORT%
set HERE=%~dp0

echo ============================================================
echo   繁工AI 本地解析工作台
echo   URL: %URL%
echo ============================================================
echo.

rem ---------- 1. is the service already listening? ----------
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do set FOUND=1

if "!FOUND!"=="1" (
    echo [信息] 工作台已在运行，正在打开浏览器...
    echo [地址] %URL%
    echo.
    start "" "%URL%"
    echo 如果没有自动弹出，请手动把上面的地址复制到浏览器打开。
    echo.
    pause
    exit /b 0
)

rem ---------- 2. not running: start it ----------
echo [信息] 工作台未运行，正在启动...
cd /d "%HERE%"

set "PY="
if exist "%HERE%venv\Scripts\python.exe" set "PY=%HERE%venv\Scripts\python.exe"
if not defined PY if exist "%HERE%.venv\Scripts\python.exe" set "PY=%HERE%.venv\Scripts\python.exe"
if not defined PY for %%G in (python.exe) do set "PY=%%~$PATH:G"
if not defined PY (
    for /f "delims=" %%D in ('dir /b /ad "%LOCALAPPDATA%\Programs\Python\Python3*" 2^>nul') do (
        if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\%%D\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\%%D\python.exe"
    )
)
if not defined PY (
    for /f "delims=" %%D in ('dir /b /ad "D:\WorkBuddy\work\data\binaries\python\versions" 2^>nul') do (
        if not defined PY if exist "D:\WorkBuddy\work\data\binaries\python\versions\%%D\python.exe" set "PY=D:\WorkBuddy\work\data\binaries\python\versions\%%D\python.exe"
    )
)

if not defined PY (
    echo [错误] 找不到可用的 Python。
    echo         请先运行 install.bat 安装依赖，然后重新双击本文件。
    echo.
    pause
    exit /b 1
)

echo [信息] 使用 Python: %PY%
if not exist "%HERE%updates" mkdir "%HERE%updates"
start "Fangong Workbench" /min cmd /c ""%PY%" start.py >> "%HERE%updates\start.log" 2>&1"

echo [信息] 等待服务就绪（最多 60 秒）...
set WAIT=0
:waitloop
timeout /t 1 /nobreak >nul
set /a WAIT+=1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do goto ready
if !WAIT! LSS 60 goto waitloop

echo.
echo [警告] 60 秒内服务没有起来。
echo         log: %HERE%updates\start.log
echo         常见原因 - 依赖没装全，或 8756 端口被其它程序占用。
echo.
pause
exit /b 1

:ready
echo [完成] 服务已就绪，正在打开浏览器...
echo [地址] %URL%
echo.
start "" "%URL%"
echo 如果没有自动弹出，请手动把上面的地址复制到浏览器打开。
echo 上传入口在页面的「上传与解析」区域，可以把文件或整个文件夹拖进去。
echo.
pause
exit /b 0
