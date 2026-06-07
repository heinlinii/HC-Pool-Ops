@echo off
echo Installing dashboard monthly calendar patch...
copy /Y "app\templates\dashboard.html" "%CD%\app\templates\dashboard.html" >nul
if exist "%CD%\app\static\style.css" (
  findstr /C:"dashboard_calendar_patch" "%CD%\app\static\style.css" >nul
  if errorlevel 1 (
    echo.>> "%CD%\app\static\style.css"
    type "app\static\dashboard_calendar_patch.css" >> "%CD%\app\static\style.css"
  )
)
echo DONE. Restart server and refresh dashboard.
pause
