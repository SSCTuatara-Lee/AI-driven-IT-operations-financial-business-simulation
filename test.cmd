@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
pause
