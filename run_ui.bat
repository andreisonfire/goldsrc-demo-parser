@echo off
REM ============================================================
REM  CS 1.6 demo highlights — Web UI launcher
REM  Opens a browser at http://localhost:8765 where you can
REM  drag .dem files in and export highlights as CSV or TXT.
REM ============================================================
setlocal

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

set "SCRIPT=%~dp0cs16_ui.py"
if not exist "%SCRIPT%" (
    echo [ERROR] cs16_ui.py not found next to this .bat
    pause
    exit /b 1
)

echo Starting GoldSrc Demo Parser UI...
echo The browser should open automatically. If not, visit:
echo   http://localhost:8765
echo.
echo Press Ctrl+C in this window to stop the server.
echo.
"%PY%" "%SCRIPT%"
pause
endlocal
