@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare-runtime32.ps1"
if errorlevel 1 pause
