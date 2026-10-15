@echo off
title Living Hoenn - restart bridge
rem Double-click to run. Extra options can be passed after the name, e.g.
rem   START_DEMO.bat -Model qwen3:8b -SkipTests -State 1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0demo\demo.ps1" -Action restart-bridge %*
echo.
pause
