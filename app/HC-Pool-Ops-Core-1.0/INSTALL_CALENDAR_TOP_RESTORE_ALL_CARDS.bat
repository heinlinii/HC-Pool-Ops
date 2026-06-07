@echo off
echo Putting calendar directly under top card and restoring all dashboard cards...
copy /Y "app\templates\dashboard.html" "%CD%\app\templates\dashboard.html"
echo DONE. Restart PoolOps and hard refresh phone Safari.
pause
