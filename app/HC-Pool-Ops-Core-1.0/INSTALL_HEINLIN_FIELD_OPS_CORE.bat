@echo off
set ROOT=%CD%
set BACKUP=%ROOT%jarvis_backups\before_hfo_core_%DATE:~-4%%DATE:~4,2%%DATE:~7,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%
set BACKUP=%BACKUP: =0%
echo Backing up current app to %BACKUP%
mkdir "%BACKUP%" 2>nul
xcopy /E /I /Y "%ROOT%app" "%BACKUP%\app" >nul
copy /Y "%ROOT%poolops2_local.db" "%BACKUP%\poolops2_local.db" >nul 2>nul
copy /Y "%ROOT%poolops_local.db" "%BACKUP%\poolops_local.db" >nul 2>nul
echo Installing Heinlin Field Ops Core...
xcopy /E /I /Y "app" "%ROOT%app" >nul
echo.
echo DONE.
echo This installed the stable core app with editable dashboard, clients, properties, jobs, photos, crew, schedule, field logs, estimates, job costing, QuickBooks prep, weather notes, map list, employee portal, and client portal.
echo.
echo Start it with:
echo uvicorn app.app:app --host 0.0.0.0 --port 8000 --reload
pause
