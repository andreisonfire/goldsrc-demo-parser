@echo off
REM ============================================================
REM  Build cs16_killfeed.exe + cs16_ui.exe (standalone)
REM  Run once. Distribute files from the 'release' folder.
REM ============================================================
setlocal

REM --- switch to the script's own directory so we can use plain
REM --- relative paths below. This avoids breakage when the folder
REM --- name contains spaces, parentheses, or other punctuation.
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
echo === Step 1/4: installing PyInstaller ===
%PY% -m pip install --user --upgrade pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller.
    pause
    exit /b 1
)

REM --- Wipe any leftover build artefacts from previous runs.
REM --- PyInstaller caches a .spec file with absolute paths inside
REM --- --specpath; if that .spec survives a failed build, the next
REM --- run will re-read the old (broken) paths from it.
if exist _build_tmp rmdir /s /q _build_tmp
if exist release    rmdir /s /q release

echo.
echo === Step 2/4: building cs16_killfeed.exe (CLI / drag-and-drop) ===
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
echo === Step 3/4: building cs16_ui.exe (web UI) ===
%PY% -m PyInstaller --onefile --console --name cs16_ui ^
    --distpath release ^
    --workpath _build_tmp ^
    --specpath _build_tmp ^
    --paths . ^
    cs16_ui.py
if errorlevel 1 (
    echo [ERROR] UI build failed.
    pause
    exit /b 1
)

echo.
echo === Step 4/4: bundling launchers and docs ===
if exist run_ui.bat                copy /Y run_ui.bat                release\ >nul
if exist run_round_multikills.bat  copy /Y run_round_multikills.bat  release\ >nul
if exist run_all_kills.bat         copy /Y run_all_kills.bat         release\ >nul
if exist README.txt                copy /Y README.txt                release\ >nul

echo.
echo === DONE ===
echo.
echo Your distribution package is in: %cd%\release
echo.
echo   cs16_ui.exe           ^<-- double-click for the web UI (recommended)
echo   run_ui.bat            ^<-- same thing, just a batch wrapper
echo   cs16_killfeed.exe     ^<-- CLI core used by the drag+drop bats
echo   run_round_multikills.bat, run_all_kills.bat  ^<-- drag+drop tools
echo   README.txt
echo.
echo Zip the entire 'release' folder and send it to friends.
echo They do NOT need Python installed.
echo.
pause
endlocal
