@echo off
chcp 65001 >nul
title Fangong AI Workbench (foreground)
setlocal enabledelayedexpansion

rem ============================================================
rem  v0.1.224 - start the workbench in THIS window (foreground,
rem  logs visible, Ctrl+C stops it). Double-click entry point.
rem
rem  Two real defects fixed here, both hit on 2026-11-10:
rem   1) The file was saved as UTF-8 WITH BOM. cmd then reads the
rem      first line as "?@echo off", never enables echo-off, and
rem      floods the window with every command it runs. Verified:
rem      with BOM -> "'?@echo' is not recognized ..."; without BOM
rem      -> normal output.
rem   2) It hard-required venv\Scripts\activate.bat. venv DOES exist
rem      on this machine, so this was not the cause of the missing
rem      workbench - but a fresh copy or a moved folder has no venv
rem      and then this script just says 'run install.bat' and exits.
rem      Now it probes the same python locations as open_or_start.bat
rem      (venv -> .venv -> PATH -> LOCALAPPDATA -> bundled runtime)
rem      so it degrades gracefully instead of dead-ending.
rem
rem ============================================================
rem  v0.1.224 - start the workbench in THIS window (foreground,
rem  logs visible, Ctrl+C stops it). Double-click entry point.
rem
rem  Two real defects fixed here, both hit on 2026-11-10:
rem   1) The file was saved as UTF-8 WITH BOM. cmd then reads the
rem      first line as "?@echo off", never enables echo-off, and
rem      floods the window with every command it runs. Verified:
rem      with BOM -> "'?@echo' is not recognized ..."; without BOM
rem      -> normal output.
rem   2) It required venv\Scripts\activate.bat. On this machine
rem      there is NO venv, so double-clicking simply printed
rem      "[hint] dependencies not installed, run install.bat" and
rem      exited - the user could never open the workbench. Now it
rem      probes the same python locations as open_or_start.bat and
rem      falls back to the system interpreter.
rem
rem  Keep all `rem` comments ASCII. Chinese appears only inside
rem  `echo` lines (renders fine under chcp 65001, verified).
rem ============================================================

set PORT=8756
set URL=http://127.0.0.1:%PORT%
set HERE=%~dp0
cd /d "%HERE%"

echo ============================================================
echo   繁工AI 本地解析工作台
echo   URL: %URL%
echo   关闭本窗口即停止服务（扫描/解析进行中请先等它跑完）
echo ============================================================
echo.

rem ---------- already running? ----------
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do set FOUND=1
if "!FOUND!"=="1" (
    echo [信息] 工作台已经在运行了，不用再启动。
    echo [地址] %URL%
    echo.
    echo 直接打开上面的地址即可；要重启服务请先关闭已有的服务窗口。
    echo.
    pause
    exit /b 0
)

rem ---------- locate python ----------
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
    for /f "delims=" %%D in ('dir /b /ad "D:/WorkBuddy/work/data/binaries/python/versions" 2^>nul') do (
        if not defined PY if exist "D:/WorkBuddy/work/data/binaries/python/versions/%%D/python.exe" set "PY=D:/WorkBuddy/work/data/binaries/python/versions/%%D/python.exe"
    )
)

if not defined PY (
    echo [错误] 找不到可用的 Python。
    echo        请先运行 install.bat 安装依赖，或直接双击 open_or_start.bat。
    echo.
    pause
    exit /b 1
)

echo [信息] 使用 Python: %PY%
echo [信息] 正在启动服务，启动过程约 5-15 秒，请稍候...
echo.

"%PY%" start.py
set RC=%ERRORLEVEL%
echo.
echo [信息] 服务已退出，返回码 %RC%
if not "%RC%"=="0" echo        若不是你按 Ctrl+C 主动停止，请把上面的报错整段发给维护人员。
pause
exit /b %RC%
