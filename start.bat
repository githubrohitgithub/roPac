@echo off
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\activate.bat (
  echo Running first-time setup...
  call setup.bat
  if errorlevel 1 exit /b 1
)

call .venv\Scripts\activate.bat

curl -sf http://127.0.0.1:11434/api/tags >nul 2>&1
if errorlevel 1 (
  echo ERROR: Ollama is not running. Install from https://ollama.com and start the app.
  exit /b 1
)

python assistant.py %*
