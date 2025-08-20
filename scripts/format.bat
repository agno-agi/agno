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
SET "AGNO_INFRA_DIR=%REPO_ROOT%\libs\agno_infra"
SET "COOKBOOK_DIR=%REPO_ROOT%\cookbook"

REM Function to print headings
CALL :print_heading "Formatting all libraries"

REM Check if directories exist
IF NOT EXIST "%AGNO_DIR%" (
    ECHO [ERROR] AGNO_DIR: %AGNO_DIR% does not exist
    EXIT /B 1
)

IF NOT EXIST "%AGNO_INFRA_DIR%" (
    ECHO [ERROR] AGNO_INFRA_DIR: %AGNO_INFRA_DIR% does not exist
    EXIT /B 1
)

IF NOT EXIST "%COOKBOOK_DIR%" (
    ECHO [ERROR] COOKBOOK_DIR: %COOKBOOK_DIR% does not exist
    EXIT /B 1
)

SET AGNO_FORMAT="%AGNO_DIR%\scripts\format.bat"
IF EXIST %AGNO_FORMAT% (
    ECHO [INFO] Running %AGNO_FORMAT%
    CALL %AGNO_FORMAT%
) ELSE (
    ECHO [WARNING] %AGNO_FORMAT% does not exist, skipping
)

SET AGNO_INFRA_FORMAT="%AGNO_INFRA_DIR%\scripts\format.bat"
IF EXIST %AGNO_INFRA_FORMAT% (
    ECHO [INFO] Running %AGNO_INFRA_FORMAT%
    CALL %AGNO_INFRA_FORMAT%
) ELSE (
    ECHO [WARNING] %AGNO_INFRA_FORMAT% does not exist, skipping
)

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
