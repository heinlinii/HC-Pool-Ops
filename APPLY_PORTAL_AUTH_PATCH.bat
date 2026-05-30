@echo off
echo Installing PoolOps employee/client portal login patch...
python .\jarvis_tools\apply_portal_patch.py
echo.
echo DONE. Now restart PoolOps with:
echo uvicorn app.app:app --host 0.0.0.0 --port 8000 --reload
echo.
pause
