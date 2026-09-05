@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo === ShoppingApp: starting ===

if not exist ".venv\Scripts\python.exe" (
    echo No virtual environment found. Creating one with py -3 ...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo.
        echo Could not create the virtual environment. Is Python 3.11+ installed and on PATH?
        pause
        exit /b 1
    )
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Dependency install failed. See the output above.
        pause
        exit /b 1
    )
) else (
    call ".venv\Scripts\activate.bat"
)

if not exist ".env" (
    echo No .env file found. Copying .env.example to .env ...
    copy /y ".env.example" ".env" >nul
)

rem Resolve the configured port so we can open the right browser URL.
set "PORT=8080"
for /f "usebackq delims=" %%P in (`python -c "from app.config import settings; print(settings.port)"`) do set "PORT=%%P"

echo Opening http://127.0.0.1:!PORT!/ ...
start "" "http://127.0.0.1:!PORT!/"

echo Starting server (Ctrl+C to stop) ...
python -m app.main

endlocal
