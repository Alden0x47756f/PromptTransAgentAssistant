@echo off
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\build_exe.py"
if errorlevel 1 pause
