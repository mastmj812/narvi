@echo off
REM narvi dev launcher - double-click this file.
REM Runs start.ps1 with execution-policy bypass (no "Run with PowerShell" needed)
REM and keeps this window open so any error stays visible.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
echo.
echo (launcher finished - press any key to close this window)
pause >nul
