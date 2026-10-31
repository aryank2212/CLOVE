@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
)
if "%1"=="--text" (
  .venv\Scripts\python.exe agent.py --text %2 %3 %4 %5
) else if "%1"=="--devices" (
  .venv\Scripts\python.exe agent.py --devices
) else if "%1"=="--doctor" (
  .venv\Scripts\python.exe agent.py --doctor
) else (
  .venv\Scripts\python.exe agent.py %*
)
