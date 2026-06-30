@echo off
REM ###########################################################################
REM # Helper functions to import in other scripts
REM ###########################################################################

REM Pause execution until user presses a key
:space_to_continue
ECHO Press any key to continue or Ctrl+C to exit...
PAUSE > nul
EXIT /B

REM Print a horizontal line
:print_horizontal_line
ECHO ------------------------------------------------------------
EXIT /B

REM Print a heading with horizontal lines
:print_heading
CALL :print_horizontal_line
ECHO -*- %~1
CALL :print_horizontal_line
EXIT /B

REM Print info message
:print_info
ECHO -*- %~1
EXIT /B 