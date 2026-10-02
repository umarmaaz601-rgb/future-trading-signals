@echo off
title FUTURE TRADING SIGNAL SCANNER
cd /d "%~dp0"

set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

echo Starting scanner... (keep this window open)
"%PY%" scanner.py
pause
