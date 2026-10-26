@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First-time setup has not been run. Running it now...
  powershell -ExecutionPolicy Bypass -File "scripts\setup_windows.ps1"
  if errorlevel 1 ( pause & exit /b 1 )
)
echo Starting Bodycam Research Hub at http://localhost:8501 (close this window to stop it)
start "" cmd /c "timeout /t 5 >nul & start http://localhost:8501"
".venv\Scripts\python.exe" -m streamlit run app.py --server.port 8501
pause
