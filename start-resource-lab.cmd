@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe scripts\resource_lab.py up
pause
