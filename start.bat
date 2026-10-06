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
rem NOT named PORT: a batch variable called PORT is inherited by python and overrides the PORT
rem in .env (config.py reads os.environ first), so a non-default port was silently ignored.
set "APP_PORT=8080"
for /f "usebackq delims=" %%P in (`python -c "from app.config import settings; print(settings.port)"`) do set "APP_PORT=%%P"

rem Refuse to start if an old server still holds the port. Without this the new process died on
rem "address already in use" while the OLD code kept serving - so an update looked like it had
rem worked but nothing changed (and the phone's update banner never fired).
python -m scripts.verify_server port-free --timeout 10
if errorlevel 1 (
    echo.
    echo Not starting: the port is still in use by an old server - see the message above.
    exit /b 1
)

echo Opening http://127.0.0.1:!APP_PORT!/ ...
start "" "http://127.0.0.1:!APP_PORT!/"

rem In the background, once the server answers, confirm it is serving the code now on disk and
rem say so (or say clearly why not). Result also goes to logs/app.log.
start "" /b python -m scripts.verify_server serving --timeout 90

echo Starting server (Ctrl+C to stop) ...
python -m app.main

endlocal
