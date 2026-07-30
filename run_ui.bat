@echo off
REM ============================================================
REM  GoldSrc Demo Parser - desktop app launcher
REM  Opens a native window where you can drag .dem files in and
REM  export highlights as CSV or TXT. No browser involved.
REM
REM  This launcher tries the compiled gsdp.exe first, then the
REM  older cs16_ui.exe name, and finally falls back to running
REM  cs16_ui.py through Python if no .exe sits next to this .bat.
REM ============================================================
setlocal

REM --- Try the .exe first (release/production layout) ---
if exist "%~dp0gsdp.exe" (
    echo Starting GoldSrc Demo Parser...
    "%~dp0gsdp.exe"
    exit /b %errorlevel%
)

REM --- Accept the pre-2.0 exe name so old release folders keep working ---
if exist "%~dp0cs16_ui.exe" (
    echo Starting GoldSrc Demo Parser...
    "%~dp0cs16_ui.exe"
    exit /b %errorlevel%
)

REM --- Fall back to running the .py through Python (dev layout) ---
if exist "%~dp0cs16_ui.py" (
    where python >nul 2>nul
    if errorlevel 1 (
        where py >nul 2>nul
        if errorlevel 1 (
            echo [ERROR] Neither gsdp.exe nor Python were found.
            echo Either put gsdp.exe next to this .bat, or install Python 3
            echo from https://www.python.org/downloads/ (check "Add to PATH").
            pause
            exit /b 1
        )
        set "PY=py"
    ) else (
        set "PY=python"
    )

    REM The desktop window needs pywebview; the .exe has it bundled but a
    REM source checkout may not, so check before launching to avoid a bare
    REM ModuleNotFoundError traceback.
    "%PY%" -c "import webview" >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] The 'pywebview' package is missing.
        echo Install it with:
        echo   %PY% -m pip install pywebview
        pause
        exit /b 1
    )

    echo Starting GoldSrc Demo Parser (from source)...
    "%PY%" "%~dp0cs16_ui.py"
    exit /b %errorlevel%
)

echo [ERROR] Neither gsdp.exe nor cs16_ui.py was found next to this .bat.
echo Expected one of:
echo   %~dp0gsdp.exe
echo   %~dp0cs16_ui.py
pause
exit /b 1
endlocal
