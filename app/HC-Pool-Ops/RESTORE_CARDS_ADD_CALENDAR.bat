@echo off
echo Restoring dashboard cards and adding monthly calendar...
copy /Y "app\templates\dashboard.html" "%CD%\app\templates\dashboard.html"
echo DONE.
echo Restart PoolOps, then hard refresh phone Safari.
pause
