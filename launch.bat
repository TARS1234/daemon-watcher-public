@echo off
REM Daemon Watcher - Windows Launcher
REM Double-click this file to start the setup wizard

cd /d "%~dp0"
python install_wizard_standalone.py
pause
