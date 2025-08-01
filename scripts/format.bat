@echo off
REM ###########################################################################
REM # Format all libraries
REM # Usage: scripts\format.bat
REM ###########################################################################

SETLOCAL ENABLEDELAYEDEXPANSION

REM Get current directory
SET "CURR_DIR=%~dp0"
SET "REPO_ROOT=%CURR_DIR%\.."
SET "AGNO_DIR=%REPO_ROOT%\libs\agno"
SET "AGNO_OS_DIR=%REPO_ROOT%\libs\agno_os"
SET "COOKBOOK_DIR=%REPO_ROOT%\cookbook"

REM Function to print headings
CALL :print_heading "Formatting all libraries"

REM Check if directories exist
IF NOT EXIST "%AGNO_DIR%" (
    ECHO [ERROR] AGNO_DIR: %AGNO_DIR% does not exist
    EXIT /B 1
)

IF NOT EXIST "%AGNO_OS_DIR%" (
    ECHO [ERROR] AGNO_OS_DIR: %AGNO_OS_DIR% does not exist
    EXIT /B 1
)

IF NOT EXIST "%COOKBOOK_DIR%" (
    ECHO [ERROR] COOKBOOK_DIR: %COOKBOOK_DIR% does not exist
    EXIT /B 1
)

REM Format all libraries
SET AGNO_FORMAT="%AGNO_DIR%\scripts\format.bat"
IF EXIST %AGNO_FORMAT% (
    ECHO [INFO] Running %AGNO_FORMAT%
    CALL %AGNO_FORMAT%
) ELSE (
    ECHO [WARNING] %AGNO_FORMAT% does not exist, skipping
)

SET AGNO_OS_FORMAT="%AGNO_OS_DIR%\scripts\format.bat"
IF EXIST %AGNO_OS_FORMAT% (
    ECHO [INFO] Running %AGNO_OS_FORMAT%
    CALL %AGNO_OS_FORMAT%
) ELSE (
    ECHO [WARNING] %AGNO_OS_FORMAT% does not exist, skipping
)

REM Format all cookbook examples
SET COOKBOOK_FORMAT="%COOKBOOK_DIR%\scripts\format.bat"
IF EXIST %COOKBOOK_FORMAT% (
    ECHO [INFO] Running %COOKBOOK_FORMAT%
    CALL %COOKBOOK_FORMAT%
) ELSE (
    ECHO [WARNING] %COOKBOOK_FORMAT% does not exist, skipping
)

ECHO [INFO] All formatting complete.
EXIT /B

REM Function to print headings
:print_heading
ECHO.
ECHO ##################################################
ECHO # %1
ECHO ##################################################
ECHO.
EXIT /B 