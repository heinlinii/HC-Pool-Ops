@echo off
echo Restoring Invisible Office...
python jarvis_tools\apply_invisible_office.py
echo.
echo DONE. Now restart PoolOps:
echo uvicorn app.app:app --host 0.0.0.0 --port 8000 --reload
pause
