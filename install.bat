@echo off
setlocal enabledelayedexpansion

:: --------------------------------------------------
:: Drive Cutter — one-time setup (Windows)
:: --------------------------------------------------
:: Run this as: double-click, or right-click > Run as administrator
:: Installs: Python 3, FFmpeg, venv + deps, Chrome extension setup
:: --------------------------------------------------

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%venv"
set "HOST_NAME=com.drivecutter.host"
set "HOST_BAT=%SCRIPT_DIR%native-host\host.bat"
set "EXT_ID=cmddahdpalfapiiiepdfmelnmpcihgie"

echo.
echo   ========================================
echo       Drive Cutter — Windows Setup
echo   ========================================
echo.

:: ==========================================================
::  STEP 1: Check / Install Python 3
:: ==========================================================
echo   [1/5] Python 3

python --version >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
    echo   + Python !PY_VER! found
    set "PYTHON_CMD=python"
    goto :check_python3
)

python3 --version >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=2 delims= " %%v in ('python3 --version 2^>^&1') do set "PY_VER=%%v"
    echo   + Python !PY_VER! found
    set "PYTHON_CMD=python3"
    goto :check_python3
)

echo   X Python 3 not found.
echo.
echo   Installing Python via winget...
winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements >nul 2>&1
if %errorlevel% equ 0 (
    echo   + Python installed. Refreshing PATH...
    :: Refresh PATH
    set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
    set "PYTHON_CMD=python"
) else (
    echo   X Could not auto-install Python.
    echo     Download from: https://python.org/downloads
    echo     IMPORTANT: Check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

:check_python3
:: Verify version is 3.9+
%PYTHON_CMD% -c "import sys; exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo   X Python 3.9+ required. Please update Python.
    echo     Download from: https://python.org/downloads
    pause
    exit /b 1
)

:: ==========================================================
::  STEP 2: Check / Install FFmpeg
:: ==========================================================
echo.
echo   [2/5] FFmpeg

ffmpeg -version >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=1-3" %%a in ('ffmpeg -version 2^>^&1') do (
        echo   + %%a %%b %%c
        goto :ffmpeg_done
    )
) else (
    echo   X FFmpeg not found.
    echo.
    echo   Installing FFmpeg via winget...
    winget install Gyan.FFmpeg --accept-package-agreements --accept-source-agreements >nul 2>&1
    if !errorlevel! equ 0 (
        echo   + FFmpeg installed. You may need to restart this script for PATH to update.
    ) else (
        echo   X Could not auto-install FFmpeg.
        echo     Option 1: winget install Gyan.FFmpeg
        echo     Option 2: Download from https://ffmpeg.org/download.html
        echo              Extract and add the bin\ folder to your PATH.
        echo.
        set /p "CONT=  Continue anyway? [y/N] "
        if /i not "!CONT!"=="y" exit /b 1
    )
)
:ffmpeg_done

:: ==========================================================
::  STEP 3: Check Chrome
:: ==========================================================
echo.
echo   [3/5] Google Chrome

set "CHROME_PATH="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
) else if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
) else if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
)

if defined CHROME_PATH (
    echo   + Google Chrome found
) else (
    echo   X Google Chrome not found.
    echo     Download from: https://google.com/chrome
    echo     Install it, then re-run this script.
    pause
    exit /b 1
)

:: ==========================================================
::  STEP 4: Python virtual environment
:: ==========================================================
echo.
echo   [4/5] Python environment

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo   Creating virtual environment...
    %PYTHON_CMD% -m venv "%VENV_DIR%"
)
"%VENV_DIR%\Scripts\pip.exe" install -q -r "%SCRIPT_DIR%requirements.txt"
echo   + Dependencies installed

:: ==========================================================
::  STEP 5: Chrome extension + native messaging
:: ==========================================================
echo.
echo   [5/5] Chrome extension

:: ---- Register native messaging host via registry ----
set "REG_KEY=HKCU\Software\Google\Chrome\NativeMessagingHosts\%HOST_NAME%"
set "MANIFEST_PATH=%SCRIPT_DIR%native-host\%HOST_NAME%.json"

:: Write the native messaging manifest with Windows paths
(
echo {
echo   "name": "%HOST_NAME%",
echo   "description": "Drive Cutter — starts the local server on demand",
echo   "path": "%HOST_BAT:\=\\%",
echo   "type": "stdio",
echo   "allowed_origins": [
echo     "chrome-extension://%EXT_ID%/"
echo   ]
echo }
) > "%MANIFEST_PATH%"

:: Register in Windows registry
reg add "%REG_KEY%" /ve /t REG_SZ /d "%MANIFEST_PATH%" /f >nul 2>&1
echo   + Native messaging host registered

:: ---- Open Chrome extensions page + Explorer ----
echo.
echo   ================================================
echo.
echo   Almost done! Load the extension in Chrome:
echo.
echo     1. Turn on Developer mode (top-right toggle)
echo     2. Click "Load unpacked"
echo     3. Select the extension folder (opening it now)
echo.
echo   ================================================
echo.

:: Open Chrome to extensions page
start "" "%CHROME_PATH%" "chrome://extensions"
timeout /t 2 /nobreak >nul

:: Open Explorer to the extension folder
explorer "%SCRIPT_DIR%extension"

echo   Press any key once you've loaded the extension...
pause >nul

:: ---- Done ----
echo.
echo   ========================================
echo.
echo   Setup complete!
echo.
echo   Close Chrome completely and reopen it.
echo   Then go to any Google Drive or WeTransfer
echo   video page — the panel appears
echo   automatically in the bottom-right.
echo.
echo   ========================================
echo.
pause
