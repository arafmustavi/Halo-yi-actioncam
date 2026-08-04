@echo off
REM ============================================================
REM  Halo — portable EXE builder (Windows)
REM
REM    build.bat          -> LITE build  (gallery, no AI) : dist\Halo.exe
REM    build.bat ai       -> FULL build  (with YOLO)      : dist\Halo\Halo.exe
REM
REM  Needs only Python 3.9+ on PATH. Everything else is set up automatically.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Halo - Portable Builder

set MODE=lite
if /I "%~1"=="ai"  set MODE=ai
if /I "%~1"=="full" set MODE=ai

echo.
echo ============================================================
echo    Halo portable builder   [mode: %MODE%]
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python 3.9+ not found on PATH. Install from https://python.org
  pause & exit /b 1
)

if not exist ".venv-build" (
  echo Creating build environment...
  python -m venv .venv-build
)
call ".venv-build\Scripts\activate.bat"

echo Installing base dependencies + PyInstaller...
python -m pip install --upgrade pip >nul
pip install flask requests waitress pillow pyinstaller >nul

if "%MODE%"=="ai" (
  echo Installing AI stack ^(ultralytics + torch^)... this is large, please wait.
  pip install ultralytics
  echo.
  echo Building FULL AI app ^(one-folder^)...
  pyinstaller Halo-AI.spec --noconfirm --clean
  set OUT=dist\Halo\Halo.exe
) else (
  echo.
  echo Building LITE app ^(single file^)...
  pyinstaller Halo.spec --noconfirm --clean
  set OUT=dist\Halo.exe
)

echo.
if exist "!OUT!" (
  echo ============================================================
  echo    SUCCESS ^!   Portable app ready:
  echo        !OUT!
  if "%MODE%"=="ai" (
     echo    Ship the whole  dist\Halo\  folder ^(zip it^).
  ) else (
     echo    Copy that single .exe anywhere - even a USB stick.
  )
  echo ============================================================
) else (
  echo [ERROR] Build failed - see messages above.
)
echo.
pause
