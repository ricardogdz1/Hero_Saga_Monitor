@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" web_poc\run.py
) else (
    python web_poc\run.py
)
