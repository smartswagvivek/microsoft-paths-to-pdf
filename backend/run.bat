@echo off
setlocal
cd /d "%~dp0.."
set "RUNTIME_DIR=%LOCALAPPDATA%\Learnfolio"
set "PYTHON_EXE=%RUNTIME_DIR%\venv\Scripts\python.exe"
set "PYTHONDONTWRITEBYTECODE=1"
if exist "%PYTHON_EXE%" goto run
py -3 -m venv "%RUNTIME_DIR%\venv"
if errorlevel 1 goto failed
"%PYTHON_EXE%" -m pip install -r backend\requirements.txt
if errorlevel 1 goto failed
"%PYTHON_EXE%" -m playwright install --no-shell chromium
if errorlevel 1 goto failed
:run
if not defined PORT set "PORT=8501"
if not "%~1"=="" set "PORT=%~1"
echo Open http://127.0.0.1:%PORT% in your browser.
echo Press Ctrl+C after exports finish to stop.
"%PYTHON_EXE%" -B backend\app.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Startup failed. Check the message above. Install Python 3.10 or later if missing.
echo To repair dependencies, run:
echo "%PYTHON_EXE%" -m pip install -r backend\requirements.txt
echo "%PYTHON_EXE%" -m playwright install --no-shell chromium
pause
exit /b 1
