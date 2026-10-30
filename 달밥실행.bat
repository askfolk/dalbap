@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Install from https://www.python.org/downloads/
  pause
  exit /b
)
python -m pip install -q -r requirements.txt
start "" pythonw main.py
