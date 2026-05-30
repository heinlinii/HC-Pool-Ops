@echo off
cd /d "%~dp0"
echo.
echo ===============================================
echo   JARVIS POOL OPS EMERGENCY FIX
echo ===============================================
echo.
echo Closing any running local Python/Uvicorn server...
taskkill /F /IM python.exe /T >nul 2>nul

echo.
echo Rebuilding PoolOps UI tables from imported data...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" ".\jarvis_import_package\scripts\jarvis_fix_poolops_now.py"
) else (
    python ".\jarvis_import_package\scripts\jarvis_fix_poolops_now.py"
)

echo.
echo Starting PoolOps now...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m uvicorn app.app:app --reload
) else (
    python -m uvicorn app.app:app --reload
)

pause
