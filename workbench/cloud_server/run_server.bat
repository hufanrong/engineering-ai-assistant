@echo off
chcp 65001 >nul
title 繁工AI 云端合并主库
echo ========================================
echo   繁工AI 云端合并主库  v0.1.11
echo   服务地址: http://0.0.0.0:8760
echo   数据目录: %~dp0cloud_data
echo ========================================
echo.
cd /d %~dp0
python -m pip install -r requirements.txt -q
python app.py
pause
