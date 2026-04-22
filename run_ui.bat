@echo off
REM ============================================================
REM  Launch the CS 1.6 demo highlights web UI
REM  Opens http://localhost:8765 in your default browser
REM ============================================================
setlocal

REM --- prefer the .exe if it's already built ---
set "EXE=%~dp0cs16_ui.exe"
if exist "%EXE%" (
    "%EXE%"
    goto :end
)

REM --- otherwise run the Python script directly ---
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python not found and cs16_ui.exe is missing.
        echo Either build the .exe via build_exe.bat, or install Python.
        pause
        exit /b 1
    )
    set "PY=py"
) else (
    set "PY=python"
)

if not exist "%~dp0cs16_ui.py" (
    echo [ERROR] cs16_ui.py not found next to this .bat
    pause
    exit /b 1
)

"%PY%" "%~dp0cs16_ui.py"

:end
endlocal
