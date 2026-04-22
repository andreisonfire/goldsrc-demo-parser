@echo off
REM ============================================================
REM  CS 1.6 full killfeed (every single kill in the demo)
REM  Drag one or more .dem files onto this .bat
REM ============================================================
setlocal enabledelayedexpansion

set "EXE=%~dp0cs16_killfeed.exe"
if not exist "%EXE%" (
    echo [ERROR] cs16_killfeed.exe not found next to this .bat
    pause
    exit /b 1
)

if "%~1"=="" (
    echo.
    echo   CS 1.6 full killfeed
    echo   ====================
    echo.
    echo   Drag one or more .dem files onto this .bat.
    echo   Output: ^<demo^>_multikills.txt with every kill in the demo.
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
"%EXE%" "%~1" --all-kills
if errorlevel 1 echo  [!] Error on %~nx1
shift
goto loop

:done
echo.
echo ============================================================
echo  All done.
echo ============================================================
pause
endlocal
