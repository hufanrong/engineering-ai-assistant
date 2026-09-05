@echo off
chcp 65001 >nul
title 繁工AI 本地解析工作台 - 安装依赖
echo ============================================
echo   繁工AI 本地解析工作台 - 首次安装
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python。请先安装 Python 3.10+（安装时勾选 Add Python to PATH）。
    echo 下载: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] 创建虚拟环境 venv ...
if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate.bat

echo [2/3] 安装核心依赖（约 1-3 分钟，首次会下载 embedding 模型约 470MB）...
python -m pip install --upgrade pip -q
pip install -r requirements.txt

echo.
echo [3/3] 安装完成！
echo.
echo 可选依赖（按需安装，提升解析能力）：
echo   图片 OCR（约1.5GB）:  pip install -r requirements-ocr.txt
echo   CAD 解析:             pip install ezdxf
echo   （DWG 转 DXF 需另装 ODA File Converter 免费工具，见 README）
echo.
echo 现在可以启动：双击 run_workbench.bat
pause
