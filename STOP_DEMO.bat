@echo off
title Living Hoenn - stop demo
rem Double-click to run. Extra options can be passed after the name, e.g.
rem   STOP_DEMO.bat -Quiet      (never asks: leaves mGBA open and the model loaded)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0demo\demo.ps1" -Action stop %*
echo.
pause
