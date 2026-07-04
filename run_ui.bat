@echo off
REM ============================================================
REM  CS 1.6 demo highlights - Web UI launcher
REM  Opens a browser at http://localhost:8765 where you can
REM  drag .dem files in and export highlights as CSV or TXT.
REM
REM  This launcher tries the compiled cs16_ui.exe first, and
REM  falls back to running cs16_ui.py through Python if the
REM  .exe isn't next to this .bat.
REM ============================================================
setlocal

REM --- Try the .exe first (release/production layout) ---
if exist "%~dp0cs16_ui.exe" (
    echo Starting GoldSrc Demo Parser UI...
    echo The browser should open automatically. If not, visit:
    echo   http://localhost:8765
    echo.
    echo Press Ctrl+C to stop the server.
    echo.
    "%~dp0cs16_ui.exe"
    exit /b %errorlevel%
)

REM --- Fall back to running the .py through Python (dev layout) ---
if exist "%~dp0cs16_ui.py" (
    where python >nul 2>nul
    if errorlevel 1 (
        where py >nul 2>nul
        if errorlevel 1 (
            echo [ERROR] Neither cs16_ui.exe nor Python were found.
            echo Either put cs16_ui.exe next to this .bat, or install Python 3
            echo from https://www.python.org/downloads/ (check "Add to PATH").
            pause
            exit /b 1
        )
        set "PY=py"
    ) else (
        set "PY=python"
    )
    echo Starting GoldSrc Demo Parser UI (from source)...
    echo The browser should open automatically. If not, visit:
    echo   http://localhost:8765
    echo.
    echo Press Ctrl+C to stop the server.
    echo.
    "%PY%" "%~dp0cs16_ui.py"
    exit /b %errorlevel%
)

echo [ERROR] Neither cs16_ui.exe nor cs16_ui.py was found next to this .bat.
echo Expected one of:
echo   %~dp0cs16_ui.exe
echo   %~dp0cs16_ui.py
pause
exit /b 1
endlocal
