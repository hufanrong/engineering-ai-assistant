@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

rem ============================================================
rem  v0.1.221 - double-click friendly launcher.
rem
rem  Why this file is pure ASCII: cmd reads a .bat byte-by-byte, and
rem  after `chcp 65001` it loses sync on multi-byte (Chinese) lines --
rem  a `rem` line gets split and the tail is executed as a command
rem  ("'<garbage>' is not recognized..."). Verified 2026-11-09.
rem  Python output is still Chinese and renders fine under 65001.
rem
rem  Bugs fixed here (all observed on a real user machine):
rem  1) Only relied on python/git being on PATH. On this machine the
rem     real user PATH has neither, so double-click died immediately.
rem     Now both are located by absolute-path probing.
rem  2) git push failed with rc=128 and empty stderr: ~/.gitconfig
rem     points github.com at a "!"-prefixed credential helper
rem     (gh auth git-credential). "!" requires a shell -> needs
rem     sh.exe, which lives in PortableGit\usr\bin. Not on PATH =
rem     silent failure. Now we prepend it.
rem  3) Console was GBK. Selftest phase 2 prints docx bytes and died
rem     with UnicodeEncodeError, truncating the phase from 9 checks
rem     to 4. Now console and Python are both UTF-8.
rem ============================================================

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

cd /d "%~dp0"

echo ============================================================
echo   Fangong AI - WORKbuddy auto loop
echo   Checks GitHub every 5 HOURS, pulls, runs ALL phases, reports back
echo ============================================================
echo.

rem ---------- 1. locate git, expose sh.exe to PATH ----------
set "GITBIN="
for %%G in (git.exe) do set "GITBIN=%%~$PATH:G"
if not defined GITBIN (
  for %%P in (
    "%~dp0..\vendor\PortableGit\mingw64\bin\git.exe"
    "%ProgramFiles%\Git\mingw64\bin\git.exe"
    "%ProgramFiles(x86)%\Git\mingw64\bin\git.exe"
    "%LOCALAPPDATA%\Programs\Git\mingw64\bin\git.exe"
    "%LOCALAPPDATA%\Programs\WorkBuddy\resources\vendor\PortableGit\mingw64\bin\git.exe"
    "%ProgramFiles%\WorkBuddy\resources\vendor\PortableGit\mingw64\bin\git.exe"
  ) do if not defined GITBIN if exist %%P set "GITBIN=%%~fP"
)
if not defined GITBIN (
  for /f "delims=" %%D in ('dir /b /ad "%LOCALAPPDATA%\Programs\WorkBuddy\resources\vendor\PortableGit\versions" 2^>nul') do (
    if not defined GITBIN if exist "%LOCALAPPDATA%\Programs\WorkBuddy\resources\vendor\PortableGit\versions\%%D\mingw64\bin\git.exe" (
      set "GITBIN=%LOCALAPPDATA%\Programs\WorkBuddy\resources\vendor\PortableGit\versions\%%D\mingw64\bin\git.exe"
    )
  )
)
if not defined GITBIN if exist "D:/WorkBuddy/work/data/binaries/PortableGit/versions" (
  for /f "delims=" %%D in ('dir /b /ad "D:/WorkBuddy/work/data/binaries/PortableGit/versions" 2^>nul') do (
    if not defined GITBIN if exist "D:/WorkBuddy/work/data/binaries/PortableGit/versions/%%D/mingw64/bin/git.exe" (
      set "GITBIN=D:/WorkBuddy/work/data/binaries/PortableGit/versions/%%D/mingw64/bin/git.exe"
    )
  )
)
if not defined GITBIN (
  echo [ERROR] git.exe not found - cannot pull code or push reports.
  echo         Install Git for Windows and try again.
  pause
  exit /b 1
)

set "GITDIR=%~dp0"
for %%D in ("%GITBIN%") do set "GITDIR=%%~dpD"
if exist "%GITDIR%..\..\usr\bin\sh.exe" (
  set "PATH=%GITDIR%;%GITDIR%..\..\bin;%GITDIR%..\..\usr\bin;%PATH%"
)
echo [INFO] git    : %GITBIN%

rem ---------- 2. locate a Python that can import fastapi ----------
set "PY="
call :trypy "%~dp0.venv\Scripts\python.exe"
if defined PY goto :pydone
call :trypy "%~dp0venv\Scripts\python.exe"
if defined PY goto :pydone
for %%G in (python.exe) do call :trypy "%%~$PATH:G"
if defined PY goto :pydone
for /f "delims=" %%D in ('dir /b /ad "%LOCALAPPDATA%\Programs\Python\Python3*" 2^>nul') do (
  if not defined PY call :trypy "%LOCALAPPDATA%\Programs\Python\%%D\python.exe"
)
if defined PY goto :pydone
for /f "delims=" %%D in ('dir /b /ad "%ProgramFiles%\Python3*" 2^>nul') do (
  if not defined PY call :trypy "%ProgramFiles%\%%D\python.exe"
)
if defined PY goto :pydone
for /f "delims=" %%D in ('dir /b /ad "%ProgramFiles(x86)%\Python3*" 2^>nul') do (
  if not defined PY call :trypy "%ProgramFiles(x86)%\%%D\python.exe"
)
if defined PY goto :pydone
rem Python runtime shipped next to WorkBuddy (on many machines this is the only one)
for /f "delims=" %%D in ('dir /b /ad "%LOCALAPPDATA%\Programs\WorkBuddy\resources" 2^>nul') do (
  if not defined PY call :trypy "%LOCALAPPDATA%\Programs\WorkBuddy\work\data\binaries\python\versions\current\python.exe"
)
if defined PY goto :pydone
for /f "delims=" %%D in ('dir /b /ad "D:/WorkBuddy/work/data/binaries/python/versions" 2^>nul') do (
  if not defined PY call :trypy "D:/WorkBuddy/work/data/binaries/python/versions/%%D/python.exe"
)
:pydone

if not defined PY (
  echo [ERROR] No usable Python found ^(fastapi must be importable^).
  echo         Tried: project .venv, PATH, user Python, Program Files,
  echo         bundled runtime.
  echo         Run install.bat first, then double-click this file again.
  pause
  exit /b 1
)
echo [INFO] python : %PY%
echo [INFO] repo   : %~dp0..
echo.

rem ---------- 3. start the loop ----------
rem 18000s = 5 hours. Owner decision 2026-11-10: a full pass every 5 hours,
rem and it must cover EVERY phase (1-6, including the AutoCAD drawing
rem cleanup one) so the report answers "is this actually usable on a real
rem project", not just "did the API return 200".
rem Override by passing your own args, e.g.
rem   run_loop.bat --once --phases 1,2,3,6
set "ARGS=%*"
if "%ARGS%"=="" set "ARGS=--interval 18000 --phases all"

echo Schedule : every 5 hours, ALL phases (1-6)
echo NOTE     : each round restarts the workbench service, so the web page
echo            may be unreachable for about 1 minute at that moment.
echo            If you are uploading a large batch, just wait and retry.
echo Close this window to stop the loop.
echo ============================================================
echo.

"%PY%" "%~dp0tools\wb_loop.py" %ARGS%

echo.
echo [INFO] loop exited, code=%errorlevel%
pause
exit /b 0

rem ---------- helper: accept %1 as PY if it exists and imports fastapi ----------
:trypy
if defined PY goto :eof
if not exist %1 goto :eof
%1 -c "import fastapi" >nul 2>&1
if errorlevel 1 goto :eof
set "PY=%~1"
goto :eof
