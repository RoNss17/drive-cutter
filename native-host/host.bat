@echo off
:: Native messaging host wrapper for Windows
:: Chrome can't execute .py directly — this .bat calls Python
set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "VENV_PYTHON=%PROJECT_DIR%\venv\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" "%SCRIPT_DIR%host.py"
) else (
    python "%SCRIPT_DIR%host.py"
)
