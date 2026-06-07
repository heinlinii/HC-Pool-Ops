@echo off
echo Fixing Invisible Office crash and restoring clean app.py...
copy /Y "app\app.py" "%CD%\app\app.py"
copy /Y "app\templates\base.html" "%CD%\app\templates\base.html"
copy /Y "app\templates\dashboard.html" "%CD%\app\templates\dashboard.html"
copy /Y "app\templates\invisible_office.html" "%CD%\app\templates\invisible_office.html"
echo DONE. Restart with:
echo uvicorn app.app:app --host 0.0.0.0 --port 8000 --reload
pause
