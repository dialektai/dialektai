@echo off
REM dialekt backend startup script (Windows)
REM Activates the venv and starts the FastAPI server.

set SCRIPT_DIR=%~dp0
set VENV=%SCRIPT_DIR%venv

IF NOT EXIST "%VENV%" (
    echo Creating Python venv...
    python -m venv "%VENV%"
    "%VENV%\Scripts\pip" install --quiet -r "%SCRIPT_DIR%requirements.txt"
)

call "%VENV%\Scripts\activate.bat"
python "%SCRIPT_DIR%server.py" %*
