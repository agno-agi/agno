@echo off
REM ###########################################################################
REM # Validate all libraries
REM # Usage: scripts\validate.bat
REM ###########################################################################

SETLOCAL ENABLEDELAYEDEXPANSION

REM Get current directory
SET "CURR_DIR=%~dp0"
SET "REPO_ROOT=%CURR_DIR%\.."
SET "AGNO_DIR=%REPO_ROOT%\libs\agno"
SET "AGNO_OS_DIR=%REPO_ROOT%\libs\agno_os"

REM Function to print headings
CALL :print_heading "Validating all libraries"

REM Check if directories exist
IF NOT EXIST "%AGNO_DIR%" (
    ECHO [ERROR] AGNO_DIR: %AGNO_DIR% does not exist
    EXIT /B 1
)

IF NOT EXIST "%AGNO_OS_DIR%" (
    ECHO [ERROR] AGNO_OS_DIR: %AGNO_OS_DIR% does not exist
    EXIT /B 1
)

REM Validate all libraries
SET AGNO_VALIDATE="%AGNO_DIR%\scripts\validate.bat"
IF EXIST %AGNO_VALIDATE% (
    ECHO [INFO] Running %AGNO_VALIDATE%
    CALL %AGNO_VALIDATE%
    IF %ERRORLEVEL% NEQ 0 (
        ECHO [ERROR] %AGNO_VALIDATE% failed with exit code %ERRORLEVEL%
        EXIT /B %ERRORLEVEL%
    )
) ELSE (
    ECHO [WARNING] %AGNO_VALIDATE% does not exist, skipping
)

SET AGNO_OS_VALIDATE="%AGNO_OS_DIR%\scripts\validate.bat"
IF EXIST %AGNO_OS_VALIDATE% (
    ECHO [INFO] Running %AGNO_OS_VALIDATE%
    CALL %AGNO_OS_VALIDATE%
    IF %ERRORLEVEL% NEQ 0 (
        ECHO [ERROR] %AGNO_OS_VALIDATE% failed with exit code %ERRORLEVEL%
        EXIT /B %ERRORLEVEL%
    )
) ELSE (
    ECHO [WARNING] %AGNO_OS_VALIDATE% does not exist, skipping
)

SET AGNO_AWS_VALIDATE="%AGNO_AWS_DIR%\scripts\validate.bat"
IF EXIST %AGNO_AWS_VALIDATE% (
    ECHO [INFO] Running %AGNO_AWS_VALIDATE%
    CALL %AGNO_AWS_VALIDATE%
    IF %ERRORLEVEL% NEQ 0 (
        ECHO [ERROR] %AGNO_AWS_VALIDATE% failed with exit code %ERRORLEVEL%
        EXIT /B %ERRORLEVEL%
    )
) ELSE (
    ECHO [WARNING] %AGNO_AWS_VALIDATE% does not exist, skipping
)

ECHO [INFO] All validations complete.
EXIT /B 0

REM Function to print headings
:print_heading
ECHO.
ECHO ##################################################
ECHO # %1
ECHO ##################################################
ECHO.
EXIT /B 