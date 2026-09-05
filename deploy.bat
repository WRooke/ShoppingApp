@echo off
setlocal
cd /d "%~dp0"

echo === ShoppingApp: deploy (commit/tag/push from dev PC) ===

if not exist ".venv\Scripts\python.exe" (
    echo No virtual environment found. Run start.bat first to set one up.
    exit /b 1
)
call ".venv\Scripts\activate.bat"

python -m scripts.deploy
set "RC=%ERRORLEVEL%"

endlocal & exit /b %RC%
