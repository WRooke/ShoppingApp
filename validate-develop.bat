@echo off
REM Validate the develop branch before pushing
REM
REM Checks:
REM  - Working tree is clean (all changes committed)
REM  - Currently on the develop branch
REM  - All tests pass
REM
REM Usage: validate-develop.bat (from project root)

setlocal enabledelayedexpansion

REM Activate venv if not already active
if not defined VIRTUAL_ENV (
    if exist .venv\Scripts\activate.bat (
        call .venv\Scripts\activate.bat
    ) else (
        echo Error: Virtual environment not found. Run start.bat first.
        exit /b 1
    )
)

REM Run the validation script
python -m scripts.validate_develop
exit /b %ERRORLEVEL%
