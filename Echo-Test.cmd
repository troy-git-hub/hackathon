@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Project Python environment is missing.
  pause
  exit /b 1
)
set ECHO_TEST_BUILD=1
start "" ".venv\Scripts\pythonw.exe" "main.py"
