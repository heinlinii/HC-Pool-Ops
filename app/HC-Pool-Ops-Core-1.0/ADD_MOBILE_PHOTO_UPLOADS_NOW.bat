@echo off
cd /d "%~dp0"
echo Closing local PoolOps Python/Uvicorn servers...
taskkill /F /IM python.exe /T >nul 2>nul
py -3 jarvis_import_package\scripts\add_mobile_photo_uploads.py
if errorlevel 1 (
  echo.
  echo PATCH FAILED. Send Jarvis this screen.
  pause
  exit /b 1
)
echo.
echo Starting PoolOps with phone access...
python -m uvicorn app.app:app --host 0.0.0.0 --port 8000 --reload
pause
