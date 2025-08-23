@echo off
:: 检查是否以管理员权限运行
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 请求管理员权限...
    PowerShell -Command "Start-Process '%~dpnx0' -Verb RunAs"
    exit /b
)

:: 切换到脚本所在目录
cd /d %~dp0

:: 运行 Python 脚本
python main.py
pause