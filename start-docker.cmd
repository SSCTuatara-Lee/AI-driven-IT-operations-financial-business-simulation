@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe scripts\start_docker.py
pause
