@echo off
REM ============================================================
REM  CS 1.6 demo killfeed extractor — drag & drop launcher
REM  Usage: drag one or more .dem files onto this .bat
REM ============================================================
setlocal enabledelayedexpansion

REM --- locate python ---
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python not found in PATH.
        echo Install Python 3 from https://www.python.org/downloads/
        echo Make sure to check "Add Python to PATH" during install.
        pause
        exit /b 1
    )
    set "PY=py"
) else (
    set "PY=python"
)

REM --- locate the script next to this .bat ---
set "SCRIPT=%~dp0cs16_killfeed.py"
if not exist "%SCRIPT%" (
    echo [ERROR] cs16_killfeed.py not found next to this .bat
    echo Expected location: %SCRIPT%
    pause
    exit /b 1
)

REM --- no files dropped? ---
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

REM --- process each dropped file ---
:loop
if "%~1"=="" goto done
echo.
echo ============================================================
echo  Processing: %~nx1
echo ============================================================
"%PY%" "%SCRIPT%" "%~1"
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
