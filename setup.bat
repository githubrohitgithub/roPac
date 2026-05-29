@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo ERROR: Install Python 3.10+ from https://python.org
  exit /b 1
)

if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
)

call .venv\Scripts\activate.bat
pip install -q --upgrade pip
pip install -q -r requirements.txt

where ollama >nul 2>&1
if errorlevel 1 (
  echo ERROR: Install Ollama from https://ollama.com
  exit /b 1
)

curl -sf http://127.0.0.1:11434/api/tags >nul 2>&1
if errorlevel 1 (
  echo ERROR: Start the Ollama app, then run start.bat again.
  exit /b 1
)

for /f "delims=" %%M in ('python -c "import json; print(json.load(open('config.json'))['base_model'])"') do set BASE=%%M
for /f "delims=" %%M in ('python -c "import json; print(json.load(open('config.json'))['model'])"') do set MODEL=%%M

ollama show %MODEL% >nul 2>&1
if errorlevel 1 (
  echo Pulling base model %BASE%...
  ollama pull %BASE%
  echo Creating %MODEL%...
  ollama create %MODEL% -f Modelfile
)

echo RoPac is ready. Run: start.bat
