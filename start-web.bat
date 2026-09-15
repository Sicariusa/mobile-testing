@echo off
REM One-click launcher for the Mobile QA web control panel.
REM Double-click this file: it starts the local server and opens the panel.
cd /d "%~dp0"
start "" cmd /c "timeout /t 2 >nul & start http://localhost:8765"
py cli.py web
