@echo off
REM ###########################################################################
REM # Format the agno library using ruff
REM # Usage: scripts\format.bat
REM ###########################################################################

SETLOCAL ENABLEDELAYEDEXPANSION

REM Get current directory and set AGNO_DIR to parent folder
SET "CURR_DIR=%~dp0"
SET "AGNO_DIR=%CURR_DIR%\.."
SET "VENV_PATH=%AGNO_DIR%\.venv"

REM Normalize paths
FOR %%I IN ("%AGNO_DIR%") DO SET "AGNO_DIR=%%~fI"
FOR %%I IN ("%VENV_PATH%") DO SET "VENV_PATH=%%~fI"

REM Try to activate virtual environment if it exists
IF EXIST "%VENV_PATH%\Scripts\activate.bat" (
    ECHO [INFO] Activating virtual environment: %VENV_PATH%
    CALL "%VENV_PATH%\Scripts\activate.bat"
) ELSE (
    ECHO [INFO] No virtual environment found at %VENV_PATH%
)

ECHO.
ECHO ##################################################
ECHO # Formatting agno
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
ECHO # Running: ruff format %AGNO_DIR%
ECHO ##################################################
ECHO.

python -m ruff format "%AGNO_DIR%"

ECHO.
ECHO ##################################################
ECHO # Running: ruff check --select I --fix %AGNO_DIR%
ECHO ##################################################
ECHO.

python -m ruff check --select I --fix "%AGNO_DIR%"

ECHO [INFO] agno formatting complete.
EXIT /B
