@echo off
chcp 65001 >nul
title 繁工AI 工作台 - 增强解析依赖一键安装
echo ============================================
echo  繁工AI 工作台 - 增强解析依赖一键安装
echo  安装内容：ezdxf（DWG/DXF图纸解析）
echo             paddleocr（图片OCR文字提取）
echo             faster-whisper（语音本地转写）
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+ 并勾选 Add to PATH
    pause
    exit /b 1
)

echo [1/3] 安装 ezdxf（图纸解析）...
pip install ezdxf --quiet
if errorlevel 1 (
    echo [警告] ezdxf 安装失败，请检查网络后重试
) else (
    echo [完成] ezdxf 已安装
)
echo.

echo [2/3] 安装 paddleocr（图片OCR，约需几分钟）...
echo       若网络较慢可跳过：注释掉下面一行后重新运行本脚本
pip install paddleocr --quiet
if errorlevel 1 (
    echo [警告] paddleocr 安装失败（可跳过，图片将只保存不提取文字）
) else (
    echo [完成] paddleocr 已安装
)
echo.

echo [3/3] 安装 faster-whisper（语音转写）...
pip install faster-whisper --quiet
if errorlevel 1 (
    echo [警告] faster-whisper 安装失败（语音将进入"待转写清单"人工补录）
) else (
    echo [完成] faster-whisper 已安装
)
echo.

echo ============================================
echo  安装完成！请重启"繁工AI 本地解析工作台"。
echo  提示：DWG 图纸还需 ODA File Converter（你已装 27.1.0，
echo  平台会自动搜索 Program Files 下的任意版本目录）。
echo ============================================
pause
