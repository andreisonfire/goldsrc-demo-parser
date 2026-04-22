@echo off
REM ============================================================
REM  CS 1.6 round multikills (4+ kills in a single round)
REM  Drag one or more .dem files onto this .bat
REM ============================================================
setlocal enabledelayedexpansion

where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python not found in PATH.
        pause
        exit /b 1
    )
    set "PY=py"
) else (
    set "PY=python"
)

set "SCRIPT=%~dp0cs16_killfeed.py"
if not exist "%SCRIPT%" (
    echo [ERROR] cs16_killfeed.py not found next to this .bat
    pause
    exit /b 1
)

REM --- Config: how many kills count as a round multikill ---
REM   4 = quads + aces, 5 = aces only
set "MIN_KILLS=4"

if "%~1"=="" (
    echo.
    echo   CS 1.6 round multikills extractor
    echo   =================================
    echo.
    echo   Drag one or more .dem files onto this .bat.
    echo   Output: ^<demo^>_multikills.txt with %MIN_KILLS%+ kill streaks per round.
    echo.
    pause
    exit /b 0
)

:loop
if "%~1"=="" goto done
echo.
echo ============================================================
echo  Processing: %~nx1
echo ============================================================
"%PY%" "%SCRIPT%" "%~1" --rounds %MIN_KILLS% --flat
if errorlevel 1 echo  [!] Script exited with error on %~nx1
shift
goto loop

:done
echo.
echo ============================================================
echo  All done.
echo ============================================================
pause
endlocal
