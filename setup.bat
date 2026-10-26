@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "scripts\setup_windows.ps1"
pause
