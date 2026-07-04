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
%RUNNER% "%~1" --highlights
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
