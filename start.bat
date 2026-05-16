@echo off
cd /d "%~dp0"
call venv\Scripts\activate
start "" "chrome.exe" "http://127.0.0.1:8000"
cd src
uvicorn main:app --host 127.0.0.1 --port 8000
