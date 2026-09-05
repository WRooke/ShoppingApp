@echo off
setlocal
cd /d "%~dp0"

echo === ShoppingApp: update (pull latest + restart, run on the NUC) ===

if not exist ".venv\Scripts\python.exe" (
    echo No virtual environment found. Run start.bat first to set one up.
    exit /b 1
)
call ".venv\Scripts\activate.bat"

python -m scripts.update
if errorlevel 1 (
    echo.
    echo Update aborted - see above. The server has NOT been touched.
    exit /b 1
)

echo.
echo Stopping the running server, if any...
call stop.bat

echo.
echo Starting the updated server...
call start.bat

endlocal
