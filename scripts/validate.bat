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
SET "AGNO_INFRA_DIR=%REPO_ROOT%\libs\agno_infra"
SET "COOKBOOK_DIR=%REPO_ROOT%\cookbook"

REM Function to print headings
CALL :print_heading "Validating all libraries"

REM Check if directories exist
IF NOT EXIST "%AGNO_DIR%" (
    ECHO [ERROR] AGNO_DIR: %AGNO_DIR% does not exist
    EXIT /B 1
)

IF NOT EXIST "%AGNO_INFRA_DIR%" (
    ECHO [ERROR] AGNO_INFRA_DIR: %AGNO_INFRA_DIR% does not exist
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

SET AGNO_INFRA_VALIDATE="%AGNO_INFRA_DIR%\scripts\validate.bat"
IF EXIST %AGNO_INFRA_VALIDATE% (
    ECHO [INFO] Running %AGNO_INFRA_VALIDATE%
    CALL %AGNO_INFRA_VALIDATE%
    IF %ERRORLEVEL% NEQ 0 (
        ECHO [ERROR] %AGNO_INFRA_VALIDATE% failed with exit code %ERRORLEVEL%
        EXIT /B %ERRORLEVEL%
    )
) ELSE (
    ECHO [WARNING] %AGNO_INFRA_VALIDATE% does not exist, skipping
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
@REM )

@REM SET COOKBOOK_VALIDATE="%COOKBOOK_DIR%\scripts\validate.bat"
@REM IF EXIST %COOKBOOK_VALIDATE% (
@REM     ECHO [INFO] Running %COOKBOOK_VALIDATE%
@REM     CALL %COOKBOOK_VALIDATE%
@REM ) ELSE (
@REM     ECHO [WARNING] %COOKBOOK_VALIDATE% does not exist, skipping
@REM )

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
