@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo No virtual environment found. Run start.bat first to set one up.
    exit /b 1
)
call ".venv\Scripts\activate.bat"

rem Usage: restore.bat                -> list backups
rem        restore.bat latest         -> dry run
rem        restore.bat latest --yes   -> actually restore
python -m scripts.restore %*

endlocal
