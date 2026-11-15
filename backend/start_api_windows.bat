@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Create backend\.venv and install backend\requirements-local.txt first. See README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8000 %*
if errorlevel 1 (
  echo.
  echo Server failed to start. Check backend\.venv dependencies and whether port 8000 is already in use.
  pause
)
