@echo off
REM ============================================================
REM  CS 1.6 demo killfeed extractor - drag & drop launcher
REM  Usage: drag one or more .dem files onto this .bat
REM
REM  Tries cs16_killfeed.exe first, falls back to cs16_killfeed.py
REM  through Python if the .exe isn't next to this .bat.
REM ============================================================
setlocal enabledelayedexpansion

REM --- Locate the runner: .exe or .py + Python ---
set "RUNNER="
if exist "%~dp0cs16_killfeed.exe" (
    set "RUNNER=%~dp0cs16_killfeed.exe"
) else if exist "%~dp0cs16_killfeed.py" (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "RUNNER=python %~dp0cs16_killfeed.py"
    ) else (
        where py >nul 2>nul
        if not errorlevel 1 set "RUNNER=py %~dp0cs16_killfeed.py"
    )
)

if "%RUNNER%"=="" (
    echo [ERROR] Neither cs16_killfeed.exe nor cs16_killfeed.py+Python found next to this .bat.
    pause
    exit /b 1
)

if "%~1"=="" (
    echo.
    echo   CS 1.6 demo killfeed extractor
    echo   ==============================
    echo.
    echo   Drag one or more .dem files onto this .bat file.
    echo.
    echo   Output: ^<demo^>_multikills.txt next to each input demo.
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
%RUNNER% "%~1"
if errorlevel 1 (
    echo.
    echo  [!] Script exited with error on %~nx1
)
shift
goto loop

:done
echo.
echo ============================================================
echo  All done.
echo ============================================================
pause
endlocal
