@echo off
chcp 65001 >nul
title 繁工AI 本地解析工作台
cd /d "%~dp0"
if not exist venv (
    echo [提示] 尚未安装依赖，先运行 install.bat
    pause
    exit /b 1
)
call venv\Scripts\activate.bat
echo 启动中... 浏览器将自动打开 http://127.0.0.1:8756
echo 关闭本窗口即停止服务（扫描任务请等待完成后再关）。
python start.py
pause
