
@echo off
:: FORCE UTF-8 ENCODING to fix the logo
chcp 65001 >nul
setlocal EnableDelayedExpansion

:: ############################################################################
:: 
::    Agno Demo Environment Setup
:: 
::    Usage: scripts\demo_setup.bat
::    Run:   python cookbook/01_demo/run.py
:: 
:: ############################################################################

:: Determine paths
set "CURR_DIR=%~dp0"
:: Remove trailing backslash for consistency
set "CURR_DIR=%CURR_DIR:~0,-1%"

:: Get Repo Root (Parent of scripts folder)
for %%I in ("%CURR_DIR%\..") do set "REPO_ROOT=%%~fI"

set "AGNO_DIR=%REPO_ROOT%\libs\agno"
set "VENV_DIR=%REPO_ROOT%\.venvs\demo"

:: Colors for the Banner (Orange is hard in batch, using Yellow)
set "ESC="
set "ORANGE=%ESC%[38;5;208m"
set "GRAY=%ESC%[90m"
set "BOLD=%ESC%[1m"
set "RESET=%ESC%[0m"

echo.
echo %ORANGE%     █████╗  ██████╗ ███╗   ██╗ ██████╗%RESET%
echo %ORANGE%    ██╔══██╗██╔════╝ ████╗  ██║██╔═══██╗%RESET%
echo %ORANGE%    ███████║██║  ███╗██╔██╗ ██║██║   ██║%RESET%
echo %ORANGE%    ██╔══██║██║   ██║██║╚██╗██║██║   ██║%RESET%
echo %ORANGE%    ██║  ██║╚██████╔╝██║ ╚████║╚██████╔╝%RESET%
echo %ORANGE%    ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝%RESET%
echo     Demo Environment Setup
echo.

:: Preflight Checks
if defined VIRTUAL_ENV (
    echo     Deactivate your current venv first.
    exit /b 1
)

where uv >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo     uv not found. Install: https://docs.astral.sh/uv/
    exit /b 1
)

:: Setup
echo     %GRAY%Removing old environment...%RESET%
echo     %GRAY%^> rmdir /s /q "%VENV_DIR%"%RESET%
if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%"

echo.
echo     %GRAY%Creating Python 3.12 venv...%RESET%
echo     %GRAY%^> uv venv "%VENV_DIR%" --python 3.12%RESET%
uv venv "%VENV_DIR%" --python 3.12 --quiet
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo.
echo     %GRAY%Installing agno[demo]...%RESET%
echo     %GRAY%^> set VIRTUAL_ENV=%VENV_DIR% ^& uv pip install -e "%AGNO_DIR%[demo]"%RESET%

:: In batch, we can set the variable just for this command by chaining or wrapping
set "VIRTUAL_ENV=%VENV_DIR%"
uv pip install -e "%AGNO_DIR%[demo]" --quiet
if %ERRORLEVEL% NEQ 0 (
    :: Clear VENV variable before exiting on error
    set "VIRTUAL_ENV="
    exit /b %ERRORLEVEL%
)
set "VIRTUAL_ENV="

:: Copy activation command to clipboard
set "ACTIVATE_CMD=.venvs\demo\Scripts\activate"
echo | set /p="%ACTIVATE_CMD%" | clip

echo.
echo     %BOLD%Done.%RESET%
echo.
echo     %GRAY%Activate:%RESET%  %ACTIVATE_CMD%
echo     %GRAY%Run Demo:%RESET%  python cookbook/01_demo/run.py
echo.
echo     %GRAY%(Activation command copied to clipboard. Just paste and hit enter.)%RESET%
echo.

endlocal