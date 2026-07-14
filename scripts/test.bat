@echo off
REM ###########################################################################
REM # Run tests for agno library
REM # Usage: scripts\test.bat
REM ###########################################################################

SETLOCAL ENABLEDELAYEDEXPANSION

REM Get current directory
SET "CURR_DIR=%~dp0"
SET "REPO_ROOT=%CURR_DIR%\.."
SET "AGNO_DIR=%REPO_ROOT%\libs\agno"

REM Function to print headings
CALL :print_heading "Running tests for agno library"

REM Check if agno directory exists
IF NOT EXIST "%AGNO_DIR%" (
    ECHO [ERROR] AGNO_DIR: %AGNO_DIR% does not exist
    EXIT /B 1
)

REM Run tests for agno library
SET AGNO_TEST=%AGNO_DIR%\scripts\test.bat
IF EXIST "%AGNO_TEST%" (
    ECHO [INFO] Running %AGNO_TEST%
    CALL "%AGNO_TEST%"
    IF %ERRORLEVEL% NEQ 0 (
        ECHO [ERROR] %AGNO_TEST% failed with exit code %ERRORLEVEL%
        EXIT /B %ERRORLEVEL%
    )
) ELSE (
    ECHO [ERROR] %AGNO_TEST% does not exist
    EXIT /B 1
)

IF %ERRORLEVEL% EQU 0 (
    ECHO [INFO] All tests completed successfully
)
GOTO :EOF

REM Helper functions
:print_horizontal_line
ECHO ------------------------------------------------------------
EXIT /B

:print_heading
CALL :print_horizontal_line
ECHO -*- %~1
CALL :print_horizontal_line
EXIT /B

:print_info
ECHO -*- %~1
EXIT /B
