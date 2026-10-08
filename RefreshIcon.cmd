@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RefreshIcon.ps1"
if errorlevel 1 pause
