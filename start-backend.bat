@echo off
chcp 65001 >nul
title 九旅比价爬虫 - 后端

rem 隔离 Roaming 用户目录旧包污染（双保险，正常情况已不需要）
set PYTHONNOUSERSITE=1

rem Python 环境路径（本机 conda 环境，可用环境变量 PYTHON_EXE 覆盖）
if "%PYTHON_EXE%"=="" set "PYTHON_EXE=D:\anaconda\envs\spider_jp_worldlink\python.exe"

cd /d %~dp0backend

rem 端口 8000 已被占用时给出友好提示，而不是 uvicorn 报错
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo.
    echo [!] 端口 8000 已被占用，后端可能已经在运行了。
    echo     直接访问 http://127.0.0.1:5173 即可使用。
    echo.
    pause
    exit /b 0
)

echo 启动后端中... 浏览器访问 http://127.0.0.1:5173
"%PYTHON_EXE%" -m uvicorn main:app --port 8000

echo.
echo 后端已退出。
pause
