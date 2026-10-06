@echo off
setlocal
cd /d "%~dp0"

echo === ShoppingApp: stopping ===

rem Stops every python.exe running this app AND whatever still listens on the app's port,
rem reports anything it could not stop, and waits for the port to be free (exit code 1 if it
rem is not). See scripts\stop_server.ps1 for why this is more than killing by command line.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_server.ps1"
set "STOP_RESULT=%errorlevel%"

if not "%STOP_RESULT%"=="0" (
    echo.
    echo *** The old server is STILL RUNNING. Phones will keep getting old code. ***
)

echo Done.
endlocal & exit /b %STOP_RESULT%
