@echo off
REM ###########################################################################
REM # Format the cookbook using ruff
REM # Usage: cookbook\scripts\format.bat
REM ###########################################################################

SETLOCAL ENABLEDELAYEDEXPANSION

REM Get current directory
SET "CURR_DIR=%~dp0"
SET "COOKBOOK_DIR=%CURR_DIR%\.."

ECHO.
ECHO ##################################################
ECHO # Formatting cookbook
ECHO ##################################################
ECHO.

REM Check if ruff is installed
python -c "import ruff" 2>nul
IF %ERRORLEVEL% NEQ 0 (
    ECHO [ERROR] ruff is not installed. Please install it with: pip install ruff
    EXIT /B 1
)

ECHO.
ECHO ##################################################
ECHO # Running: ruff format %COOKBOOK_DIR%
ECHO ##################################################
ECHO.

python -m ruff format "%COOKBOOK_DIR%"

ECHO.
ECHO ##################################################
ECHO # Running: ruff check --select I --fix %COOKBOOK_DIR%
ECHO ##################################################
ECHO.

python -m ruff check --select I --fix "%COOKBOOK_DIR%"

ECHO [INFO] cookbook formatting complete.
EXIT /B 