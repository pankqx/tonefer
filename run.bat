@echo off
REM Start tonefer on Windows. First run sets up a private virtual environment.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Setting up tonefer ^(first run^)...
  py -3 -m venv .venv || python -m venv .venv || (echo Install Python 3 from python.org first & pause & exit /b 1)
  .venv\Scripts\python -m pip install -q --upgrade pip
  .venv\Scripts\python -m pip install -q -r requirements.txt
)
.venv\Scripts\python server.py %*
pause
