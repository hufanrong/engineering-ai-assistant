@echo off
chcp 65001 >nul
title 繁工AI 本地解析工作台 - 全套安装（核心 + OCR + CAD）
echo ============================================
echo   繁工AI 本地解析工作台 - 单机全套部署
echo   （核心解析 + 图片OCR + CAD图纸 一键安装）
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python。请先安装 Python 3.10+（安装时勾选 Add Python to PATH）。
    echo 下载: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/4] 创建虚拟环境 venv ...
if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate.bat

echo [2/4] 安装核心依赖（约 1-3 分钟）...
python -m pip install --upgrade pip -q
pip install -r requirements.txt

echo [3/4] 安装图片 OCR（PaddleOCR，较大约 1.5GB，请耐心等待）...
pip install -r requirements-ocr.txt

echo [4/4] 安装完成！
echo.
echo   OCR 与 CAD 依赖已装好，程序会自动探测并启用对应解析，无需改配置。
echo   DWG 图纸还需安装免费转换工具 ODA File Converter（见 README）：
echo     https://www.opendesign.com/guestfiles/oda_file_converter
echo.
echo 现在可以启动：双击 run_workbench.bat
pause
