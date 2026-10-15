@echo off
title Living Hoenn - restart bridge
rem Double-click to run. Extra options can be passed after the name, e.g.
rem   RESTART_BRIDGE.bat -Model qwen3:8b
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0demo\demo.ps1" -Action restart-bridge %*
echo.
pause
