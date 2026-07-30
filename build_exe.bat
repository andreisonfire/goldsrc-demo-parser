@echo off
REM ============================================================
REM  Build cs16_killfeed.exe + gsdp.exe (standalone) for v2.0.
REM
REM  gsdp.exe is a desktop app powered by pywebview — no
REM  browser needed. Uses the system's WebView2 runtime, which
REM  is present on all Windows 10 / 11 machines by default.
REM
REM  Run once. Distribute files from the 'release' folder.
REM ============================================================
setlocal

cd /d "%~dp0"
if errorlevel 1 (
    echo [ERROR] Could not cd into script directory.
    pause
    exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python not found. Install from https://www.python.org/downloads/
        echo Make sure to check "Add Python to PATH" during install.
        pause
        exit /b 1
    )
    set "PY=py"
) else (
    set "PY=python"
)

echo.
echo === Step 1/5: installing PyInstaller ===
%PY% -m pip install --user --upgrade pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller.
    pause
    exit /b 1
)

echo.
echo === Step 2/5: installing pywebview (v2.0 UI runtime) ===
%PY% -m pip install --user --upgrade pywebview
if errorlevel 1 (
    echo [ERROR] Failed to install pywebview.
    pause
    exit /b 1
)

REM --- Wipe any leftover build artefacts from previous runs.
if exist _build_tmp rmdir /s /q _build_tmp
if exist release    rmdir /s /q release

echo.
echo === Step 3/5: building cs16_killfeed.exe (CLI / drag-and-drop) ===
%PY% -m PyInstaller --onefile --console --name cs16_killfeed ^
    --distpath release ^
    --workpath _build_tmp ^
    --specpath _build_tmp ^
    cs16_killfeed.py
if errorlevel 1 (
    echo [ERROR] CLI build failed.
    pause
    exit /b 1
)

echo.
echo === Step 4/5: building gsdp.exe (desktop app) ===
REM --- --windowed: no console popup on launch (this is the whole
REM     point of v2.0 — the app should look like a real app).
REM --- --collect-all webview: pywebview installs as PyPI package
REM     `pywebview` but imports as `webview` — module name, not package
REM     name, is what PyInstaller wants. This pulls in WebView2Loader.dll
REM     and the winforms/edgechromium platform backends.
REM --- --icon: embeds app_icon.ico into the .exe so Windows Explorer,
REM     the taskbar, and Alt+Tab all show our icon instead of the
REM     default PyInstaller feather.
REM --- --add-data with %~dp0: --specpath moves the .spec into _build_tmp\,
REM     which is also where PyInstaller resolves relative data paths.
REM     %~dp0 expands to the batch file's directory (with trailing \), so
REM     the icon is found regardless of where .spec is placed.
%PY% -m PyInstaller --onefile --windowed --name gsdp ^
    --distpath release ^
    --workpath _build_tmp ^
    --specpath _build_tmp ^
    --paths . ^
    --collect-all webview ^
    --icon "%~dp0app_icon.ico" ^
    --add-data "%~dp0app_icon.ico;." ^
    cs16_ui.py
if errorlevel 1 (
    echo [ERROR] UI build failed.
    pause
    exit /b 1
)

echo.
echo === Step 5/5: bundling launchers and docs ===
if exist run_ui.bat                copy /Y run_ui.bat                release\ >nul
if exist run_round_multikills.bat  copy /Y run_round_multikills.bat  release\ >nul
if exist run_all_kills.bat         copy /Y run_all_kills.bat         release\ >nul
if exist README.txt                copy /Y README.txt                release\ >nul

echo.
echo === DONE ===
echo.
echo Your distribution package is in: %cd%\release
echo.
echo   gsdp.exe              ^<-- double-click for the desktop app (main entry point)
echo   cs16_killfeed.exe     ^<-- CLI core used by the drag+drop bats
echo   run_ui.bat            ^<-- wrapper around gsdp.exe (kept for compat)
echo   run_round_multikills.bat, run_all_kills.bat  ^<-- drag+drop tools
echo   README.txt
echo.
echo Zip the 'release' folder and send it to friends.
echo They do NOT need Python installed. On Windows 10 or newer,
echo WebView2 is already present as part of the OS.
echo.
pause
endlocal
