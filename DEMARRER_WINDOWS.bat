@echo off
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
 echo Python est introuvable. Installe Python 3.10 ou plus puis relance ce fichier.
 pause
 exit /b 1
)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if errorlevel 1 (
 echo Echec d'installation des dependances.
 pause
 exit /b 1
)
echo Site: http://127.0.0.1:8000
echo API:  http://127.0.0.1:8000/docs
start "" http://127.0.0.1:8000
python -m uvicorn server:app --host 127.0.0.1 --port 8000
pause
