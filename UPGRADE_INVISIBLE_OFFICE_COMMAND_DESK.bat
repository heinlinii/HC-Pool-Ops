@echo off
echo Upgrading Invisible Office Command Desk...
python jarvis_tools\upgrade_invisible_office_command_desk.py
echo.
echo DONE. Now restart PoolOps:
echo uvicorn app.app:app --host 0.0.0.0 --port 8000 --reload
pause
