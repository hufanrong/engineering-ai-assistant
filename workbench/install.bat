@echo off
chcp 65001 >nul
title 繁工AI 本地解析工作台 - 安装依赖
cd /d "%~dp0"
echo ============================================
echo   繁工AI 本地解析工作台 - 首次安装
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python。请先安装 Python 3.10 或以上版本
    echo        安装时务必勾选 Add Python to PATH。
    echo        下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [0/4] 检查 Python 版本 ...
python -c "import sys;v=sys.version_info;print('  当前 Python %%d.%%d.%%d'%%(v[0],v[1],v[2]));sys.exit(0 if v[:2]>=(3,9) else 1)"
if errorlevel 1 (
    echo [错误] Python 版本过低，需要 3.9 或以上。
    pause
    exit /b 1
)

echo [1/4] 创建虚拟环境 venv ...
if not exist venv (
    python -m venv venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败。请确认 Python 安装完整（含 venv 模块）。
        pause
        exit /b 1
    )
)
call venv\Scripts\activate.bat

echo [2/4] 升级 pip ...
python -m pip install --upgrade pip -q

echo [3/4] 安装核心依赖（约 3-8 分钟，取决于网络）...
echo       说明：requirements.txt 内含按 Python 版本分流的版本标记，
echo             3.9~3.12 与 3.13+ 会自动选各自的可用组合，无需手工改。
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败。常见原因与处理：
    echo   1. 网络不通或需要代理：设置 HTTPS_PROXY 后重试
    echo      set HTTPS_PROXY=http://127.0.0.1:7890
    echo   2. 公司内网限制了 pypi.org：改用内部镜像
    echo      pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo   3. 缺少 C 编译环境（源码构建失败）：换 Python 3.12 LTS 版本重装
    echo.
    echo   完整错误见上方 pip 输出。修复后重新双击 install.bat 即可（已装的包会跳过）。
    pause
    exit /b 1
)

echo.
echo [4/4] 安装完成！
echo.
echo 提示：首次解析文件时会自动下载 embedding 模型（约 470MB），
echo       该步骤需要联网一次，之后完全离线可用。
echo       若网络慢，首次解析可能等待数分钟，界面不会卡死，请耐心等待。
echo.
echo 可选依赖（按需安装，提升解析能力）：
echo   图片 OCR（约1.5GB）:  pip install -r requirements-ocr.txt
echo   CAD 解析:             pip install ezdxf
echo   （DWG 转 DXF 需另装 ODA File Converter 免费工具，见 README）
echo.
echo 现在可以启动：双击 run_workbench.bat
pause
