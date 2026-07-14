@echo off
REM ###########################################################################
REM # Run tests for the agno library
REM # Usage: libs\agno\scripts\test.bat
REM ###########################################################################

SET "CURR_DIR=%~dp0"
SET "AGNO_DIR=%CURR_DIR%\.."

ECHO ------------------------------------------------------------
ECHO -*- Running tests for agno
ECHO ------------------------------------------------------------

ECHO ------------------------------------------------------------
ECHO -*- Running: pytest %AGNO_DIR% with coverage
ECHO ------------------------------------------------------------

pytest "%AGNO_DIR%\tests\unit" ^
    --cov="agno" ^
    --cov-report=term-missing ^
    --cov-report=html ^
    --continue-on-collection-errors ^
    --disable-warnings ^
    --maxfail=0