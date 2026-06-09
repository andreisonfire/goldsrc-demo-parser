@echo off
REM ============================================================
REM  CS 1.6 highlight extractor (same logic as the web UI)
REM  Drag one or more .dem files onto this .bat
REM
REM  Output: <demo>_highlights.txt with all highlight categories:
REM    aces, quads, triples, doubles (awp/scout), fast 3hs combos,
REM    plus annotations like '(incl. triple)' / '(incl. double)'.
REM
REM  POV-aware (filters to recorder's own kills) and applies the
REM  HLTV warm-up filter automatically.
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

if "%~1"=="" (
    echo.
    echo   CS 1.6 highlights extractor
    echo   ===========================
    echo.
    echo   Drag one or more .dem files onto this .bat.
    echo   Output: ^<demo^>_highlights.txt
    echo.
    echo   Uses the same selection rules as the web UI:
    echo     - aces and quads
    echo     - fast 3hs (3 headshots in 5s with deagle/ak/m4a1)
    echo     - triple/double with awp or scout (one-shot multikills)
    echo     - subset annotations: '(incl. triple)' / '(incl. double)'
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
"%PY%" "%SCRIPT%" "%~1" --highlights
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
