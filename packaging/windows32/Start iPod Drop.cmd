@echo off
setlocal
cd /d "%~dp0"

if exist "runtime32\pythonw.exe" goto run

echo Preparing the 32-bit Python runtime. This is needed only on the first launch.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare-runtime32.ps1"

if exist "runtime32\pythonw.exe" goto run

rem Fall back to a 32-bit Python installed on this PC.
py -3-32 -c "import sys;raise SystemExit(0 if sys.maxsize<2**32 and sys.version_info>=(3,9) else 1)" >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3-32 "%~dp0app\server.py"
    exit /b 0
)

python -c "import sys;raise SystemExit(0 if sys.maxsize<2**32 and sys.version_info>=(3,9) else 1)" >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%~dp0app\server.py"
    exit /b 0
)

echo.
echo No 32-bit Python 3.9+ runtime is available.
echo Run "prepare 32-bit runtime.cmd" again, or install the official 32-bit Python 3.13.
echo Download page: https://www.python.org/downloads/windows/
pause
exit /b 1

:run
start "" "%~dp0runtime32\pythonw.exe" "%~dp0app\server.py"
exit /b 0
