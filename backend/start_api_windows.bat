@echo off
cd /d "%~dp0"
py -3.15 api_server.py
if errorlevel 1 (
  echo.
  echo Server failed to start. Check Python 3.15 and whether port 8765 is already in use.
  pause
)
