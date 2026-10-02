@echo off
REM =================================================================
REM   DESKTOP APP - launches WITHOUT the black console window,
REM   so there is no window you can accidentally close/kill.
REM   (The scanner keeps running 24/7 - just minimize the app.)
REM =================================================================
cd /d "%~dp0"

set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"

start "" "%PYW%" "%~dp0app.py"
