@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo No virtual environment found. Run start.bat first to set one up.
    exit /b 1
)
call ".venv\Scripts\activate.bat"

python -m scripts.backup
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo Backup failed - see logs\app.log
)

endlocal & exit /b %RC%
